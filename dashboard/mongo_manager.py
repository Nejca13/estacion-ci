"""
mongo_manager.py - Gestor de persistencia asíncrono para MongoDB Atlas
Diseñado para Raspberry Pi Zero:
- No bloqueante (hilo daemon en segundo plano con cola acotada en RAM).
- Resiliente ante cortes de red o caídas de Wi-Fi/Tailscale.
- Soporte para múltiples dispositivos concurrentes (registra por cada nodo activo cada 5 min).
- Carga automática de .env con fallback nativo sin dependencias externas.
"""

import os
import sys
import time
import math
import queue
import datetime
import threading

# Carga ligera y nativa de .env sin obligar dependencias externas
def cargar_env():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    rutas = [
        os.path.join(base_dir, ".env"),
        os.path.join(base_dir, "..", ".env"),
        "/home/nico/dashboard/.env",
        ".env"
    ]
    for r in rutas:
        if os.path.exists(r):
            try:
                with open(r, "r", encoding="utf-8") as f:
                    for linea in f:
                        linea = linea.strip()
                        if not linea or linea.startswith("#") or "=" not in linea:
                            continue
                        k, v = linea.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"\'')
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
            except Exception as e:
                print(f"[MongoManager] Error leyendo {r}: {e}")

cargar_env()

# Intentar importar pymongo
try:
    import pymongo
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
    HAY_PYMONGO = True
except ImportError:
    pymongo = None
    PyMongoError = Exception
    ServerSelectionTimeoutError = Exception
    HAY_PYMONGO = False

class MongoManager:
    def __init__(self):
        self.uri = os.environ.get("MONGODB_URI", "").strip()
        self.db_name = os.environ.get("MONGODB_DB_NAME", "estacion-iot").strip()
        self.coll_name = os.environ.get("MONGODB_COLLECTION", "lecturas").strip()
        
        # Intervalo de guardado por dispositivo (default: 300 segundos = 5 minutos)
        try:
            self.intervalo = int(os.environ.get("MONGODB_INTERVALO_SEGUNDOS", "300"))
        except:
            self.intervalo = 300

        self.habilitado = bool(HAY_PYMONGO and self.uri)
        self.motivo_desactivado = ""
        if not HAY_PYMONGO:
            self.motivo_desactivado = "Librería pymongo no instalada (ejecutar: pip3 install pymongo[srv])"
        elif not self.uri:
            self.motivo_desactivado = "Variable MONGODB_URI no configurada en .env"

        self.conectado = False
        self.ultimo_error = None
        self.total_guardados = 0
        self.ultimo_doc_guardado = None
        
        # Diccionario para controlar el tiempo del último guardado de cada dispositivo
        # { clave_dispositivo: timestamp_float }
        self._ultimos_guardados = {}
        self._lock = threading.Lock()
        
        # Cola acotada para la Pi Zero (máx 200 lecturas para no desbordar memoria)
        self.cola = queue.Queue(maxsize=200)
        
        self.client = None
        self.collection = None
        self._worker_thread = None

        if self.habilitado:
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
            print(f"[MongoManager] Iniciado en segundo plano (Atlas: {self.db_name}.{self.coll_name}, cada {self.intervalo}s)")
        else:
            print(f"[MongoManager] Inactivo: {self.motivo_desactivado}")

    def _conectar_cliente(self):
        if not self.habilitado or pymongo is None:
            return False
        try:
            # Timeouts cortos (5s) para no demorar ni consumir recursos en Pi Zero
            self.client = pymongo.MongoClient(
                self.uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=5000,
                retryWrites=True
            )
            # Test rápido de liveness
            self.client.admin.command('ping')
            self.collection = self.client[self.db_name][self.coll_name]
            self.conectado = True
            self.ultimo_error = None
            print("[MongoManager] ✓ Conexión exitosa a MongoDB Atlas")
            return True
        except Exception as e:
            self.conectado = False
            self.ultimo_error = str(e)
            print(f"[MongoManager] Aviso: No se pudo conectar a Atlas ({e}). Reintentará en segundo plano...")
            return False

    def registrar_lectura(self, nodo_id, alias, puerto, temp, hum, luz=None, agua=None, forzar=False):
        """
        Encola la lectura para guardado en Atlas si transcurrió el intervalo (5 min) para este nodo.
        Totalmente no bloqueante.
        """
        if not self.habilitado:
            return False

        # Si no hay datos válidos, ignorar
        if temp is None and hum is None:
            return False

        clave_disp = puerto or nodo_id or "default"
        ahora = time.time()

        with self._lock:
            ultimo = self._ultimos_guardados.get(clave_disp, 0)
            if not forzar and (ahora - ultimo < self.intervalo):
                return False  # Aún no pasaron los 5 minutos para este dispositivo
            self._ultimos_guardados[clave_disp] = ahora

        doc = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "fecha": time.strftime("%Y-%m-%d"),
            "hora": time.strftime("%H:%M:%S"),
            "nodo_id": nodo_id or "nodo_0",
            "alias": alias or "Arduino",
            "puerto": puerto or "--",
            "sensores": {
                "temp": round(float(temp), 2) if temp is not None else None,
                "hum": round(float(hum), 2) if hum is not None else None,
                "luz": round(float(luz), 2) if luz is not None else None,
                "agua": round(float(agua), 2) if agua is not None else None
            }
        }

        # Descarte seguro si la cola se satura (ej: Pi sin internet por varios días)
        try:
            self.cola.put_nowait(doc)
            return True
        except queue.Full:
            try:
                # Descartar el más antiguo y colocar el nuevo
                self.cola.get_nowait()
                self.cola.put_nowait(doc)
                return True
            except:
                return False

    def _worker_loop(self):
        """Bucle consumidor en hilo daemon: realiza los envíos a Atlas."""
        while True:
            try:
                doc = self.cola.get(timeout=2.0)
            except queue.Empty:
                continue

            # Si no hay cliente o falló conexión previa, intentar conectar
            if not self.conectado or self.collection is None:
                ok = self._conectar_cliente()
                if not ok:
                    # Esperar 10s antes del siguiente reintento para no quemar CPU ni red
                    time.sleep(10)
                    # Reencolar el documento si hay espacio
                    try:
                        self.cola.put_nowait(doc)
                    except:
                        pass
                    continue

            # Intentar inserción
            try:
                self.collection.insert_one(doc)
                self.total_guardados += 1
                self.ultimo_doc_guardado = doc
                self.conectado = True
                self.ultimo_error = None
            except Exception as e:
                self.conectado = False
                self.ultimo_error = str(e)
                print(f"[MongoManager] Error insertando en Atlas: {e}")
                # Si falló la red, esperar un poco antes de reintentar
                time.sleep(5)
                try:
                    self.cola.put_nowait(doc)
                except:
                    pass

    def obtener_historico(self, limit=20, page=1, nodo=None, orden="desc", sort_by="timestamp"):
        """Consulta los registros en MongoDB Atlas con paginación y ordenamiento."""
        if not self.habilitado:
            return {
                "ok": False,
                "error": self.motivo_desactivado or "MongoDB desactivado",
                "total": 0,
                "page": 1,
                "page_size": limit,
                "total_paginas": 1,
                "dispositivos": [],
                "datos": []
            }

        # Conexión on-demand si aún no se había establecido
        if not self.conectado or self.collection is None:
            ok = self._conectar_cliente()
            if not ok:
                return {
                    "ok": False,
                    "error": self.ultimo_error or "No se pudo conectar a MongoDB Atlas",
                    "total": 0,
                    "page": 1,
                    "page_size": limit,
                    "total_paginas": 1,
                    "dispositivos": [],
                    "datos": []
                }

        try:
            filtro = {}
            if nodo and nodo != "todos" and nodo != "all":
                filtro = {"$or": [{"nodo_id": nodo}, {"puerto": nodo}, {"alias": nodo}]}

            # Contar total de documentos que cumplen el filtro
            total_count = self.collection.count_documents(filtro)

            try:
                page_num = max(1, int(page))
            except:
                page_num = 1

            try:
                page_size = max(1, min(int(limit), 100))
            except:
                page_size = 20

            skip = (page_num - 1) * page_size
            total_paginas = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 1

            # Mapeo de ordenamiento
            sort_map = {
                "timestamp": "timestamp",
                "fecha": "timestamp",
                "hora": "timestamp",
                "temp": "sensores.temp",
                "hum": "sensores.hum",
                "luz": "sensores.luz",
                "agua": "sensores.agua"
            }
            sort_field = sort_map.get(sort_by, "timestamp")
            sort_dir = -1 if str(orden).lower() in ("desc", "-1") else 1

            cursor = self.collection.find(filtro, {"_id": 0}).sort([(sort_field, sort_dir)]).skip(skip).limit(page_size)
            registros = list(cursor)

            # Obtener lista de dispositivos únicos registrados
            try:
                dispositivos_lista = self.collection.distinct("alias")
                if not dispositivos_lista:
                    dispositivos_lista = self.collection.distinct("nodo_id")
            except:
                dispositivos_lista = []

            return {
                "ok": True,
                "total": total_count,
                "page": page_num,
                "page_size": page_size,
                "total_paginas": total_paginas,
                "dispositivos": sorted(dispositivos_lista),
                "datos": registros
            }
        except Exception as e:
            self.conectado = False
            self.ultimo_error = str(e)
            return {
                "ok": False,
                "error": str(e),
                "total": 0,
                "page": 1,
                "page_size": limit,
                "total_paginas": 1,
                "dispositivos": [],
                "datos": []
            }

    def obtener_estado(self):
        """Retorna el estado actual de sincronización con MongoDB."""
        ahora = time.time()
        with self._lock:
            dispositivos_info = {}
            for clave, ts in self._ultimos_guardados.items():
                dispositivos_info[clave] = {
                    "ultimo_guardado_ts": ts,
                    "hace_segundos": round(ahora - ts, 1),
                    "proximo_guardado_en": max(0, round(self.intervalo - (ahora - ts), 1))
                }

        return {
            "habilitado": self.habilitado,
            "conectado": self.conectado,
            "motivo_desactivado": self.motivo_desactivado,
            "db": self.db_name,
            "coleccion": self.coll_name,
            "intervalo_segundos": self.intervalo,
            "total_guardados": self.total_guardados,
            "cola_pendientes": self.cola.qsize(),
            "ultimo_doc_guardado": self.ultimo_doc_guardado,
            "ultimo_error": self.ultimo_error,
            "dispositivos": dispositivos_info
        }

# Instancia global compartida
mongo_db = MongoManager()

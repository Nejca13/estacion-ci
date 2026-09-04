import os, re, threading, time, json, subprocess, glob
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
try:
    import serial
except ImportError:
    serial = None

BAUD = 9600
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_URL = "https://nejca-iot.tail4284c3.ts.net"
MAX_HIST = 40

lock_estado = threading.Lock()
dispositivos = {}  # { puerto: { ...datos... } }
workers = {}       # { puerto: ArduinoWorker }

def detectar_todos_los_puertos():
    puertos = []
    for pat in ["/dev/ttyACM*", "/dev/ttyUSB*"]:
        for p in sorted(glob.glob(pat)):
            if p not in puertos:
                puertos.append(p)
    return puertos

class ArduinoWorker(threading.Thread):
    def __init__(self, puerto, indice):
        super().__init__(daemon=True)
        self.puerto = puerto
        self.indice = indice
        self.nodo_id = f"arduino_{indice}"
        self.alias = f"Nodo {indice + 1} ({os.path.basename(puerto)})"
        self.activo = True
        self.ser = None
        self.serial_lock = threading.Lock()
        
        # Inicializar estado del dispositivo en el diccionario global
        with lock_estado:
            if self.puerto not in dispositivos:
                dispositivos[self.puerto] = {
                    "id": self.nodo_id,
                    "alias": self.alias,
                    "puerto": self.puerto,
                    "conectado": False,
                    "temp": None,
                    "hum": None,
                    "luz": None,
                    "agua": None,
                    "ts": None,
                    "hora": None,
                    "fecha": None,
                    "actuadores": {"buzzer": False},
                    "log_act": [],
                    "historial": []
                }

    def enviar(self, cmd):
        if serial is None:
            return "simulado: " + cmd
        with self.serial_lock:
            if not self.ser or not self.ser.is_open:
                return "error: puerto serial no abierto"
            try:
                self.ser.reset_input_buffer()
                self.ser.write((cmd + "\n").encode())
                self.ser.flush()
                time.sleep(0.15)
                resp = ""
                while self.ser.in_waiting:
                    resp += self.ser.readline().decode(errors="ignore")
                
                with lock_estado:
                    d = dispositivos.get(self.puerto)
                    if d:
                        d["log_act"].append({"cmd": cmd, "resp": resp.strip(), "ts": time.strftime("%H:%M:%S")})
                        if len(d["log_act"]) > 20:
                            d["log_act"].pop(0)
                        # Buzzer: B = beep 200ms, pulso visual
                        if cmd == "B":
                            d["actuadores"]["buzzer"] = True
                            # auto-off visual tras 700ms
                            def _off(port=d["puerto"] if "puerto" in d else self.puerto):
                                try:
                                    import time as _t
                                    _t.sleep(0.7)
                                    with lock_estado:
                                        dd = dispositivos.get(port)
                                        if dd: dd["actuadores"]["buzzer"] = False
                                except: pass
                            import threading as _th
                            _th.Thread(target=_off, daemon=True).start()
                        elif cmd == "MUTE":
                            d["actuadores"]["buzzer"] = False
                return resp.strip() or "ok: " + cmd
            except Exception as e:
                return "error: " + str(e)

    def run(self):
        if serial is None:
            print(f"[ADVERTENCIA] pyserial no disponible para {self.puerto}")
            return
        
        csv4 = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*$")
        csv2 = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*$")
        t_re = re.compile(r"[Tt]emperatura:\s*([0-9.]+)")
        h_re = re.compile(r"[Hh]umedad:\s*([0-9.]+)")

        try:
            with self.serial_lock:
                self.ser = serial.Serial(self.puerto, BAUD, timeout=1)
            with lock_estado:
                if self.puerto in dispositivos:
                    dispositivos[self.puerto]["conectado"] = True
            print(f"✓ Conectado {self.alias} en {self.puerto}")
        except Exception as e:
            print(f"Error abriendo {self.puerto}: {e}")
            with lock_estado:
                if self.puerto in dispositivos:
                    dispositivos[self.puerto]["conectado"] = False
            self.activo = False
            return

        while self.activo:
            try:
                with self.serial_lock:
                    if not self.ser or not self.ser.is_open:
                        break
                    linea = self.ser.readline().decode("utf-8", "ignore").strip()
            except Exception as e:
                print(f"Desconexión detectada en {self.puerto}: {e}")
                break

            if not linea:
                continue
            if linea in ("ESTACION_METEO_CSV", "ERROR"):
                if linea == "ERROR":
                    with lock_estado:
                        if self.puerto in dispositivos:
                            dispositivos[self.puerto]["ts"] = time.strftime("%H:%M:%S")
                continue
            if linea.startswith("AHORA "):
                linea = linea[6:].strip()
            if linea.startswith("ECO:") or linea.startswith("COMANDO"):
                if linea.startswith("COMANDO OK:"):
                    with lock_estado:
                        if self.puerto in dispositivos:
                            dispositivos[self.puerto]["log_act"].append({"cmd": linea, "resp": "arduino", "ts": time.strftime("%H:%M:%S")})
                continue

            # Prefijo opcional de nodo en la trama (ej: "1,24.5,60" o "NODO_1:24.5,60")
            if ":" in linea and not ("emperatura" in linea or "umedad" in linea):
                pfx, rest = linea.split(":", 1)
                linea = rest.strip()

            cambio = False
            temp_val, hum_val, luz_val, agua_val = None, None, None, None

            m4 = csv4.match(linea)
            if m4:
                try:
                    temp_val = float(m4.group(1))
                    hum_val = float(m4.group(2))
                    luz_val = float(m4.group(3))
                    agua_val = float(m4.group(4))
                    cambio = True
                except: pass
            else:
                m2 = csv2.match(linea)
                if m2:
                    try:
                        temp_val = float(m2.group(1))
                        hum_val = float(m2.group(2))
                        cambio = True
                    except: pass
                else:
                    mt = t_re.search(linea)
                    mh = h_re.search(linea)
                    if mt:
                        try: temp_val = float(mt.group(1)); cambio = True
                        except: pass
                    if mh:
                        try: hum_val = float(mh.group(1)); cambio = True
                        except: pass

            if cambio:
                ts_str = time.strftime("%H:%M:%S")
                with lock_estado:
                    d = dispositivos.get(self.puerto)
                    if d:
                        d["conectado"] = True
                        d["ts"] = ts_str
                        d["hora"] = ts_str
                        d["fecha"] = time.strftime("%Y-%m-%d")
                        if temp_val is not None: d["temp"] = temp_val
                        if hum_val is not None: d["hum"] = hum_val
                        if luz_val is not None: d["luz"] = luz_val
                        if agua_val is not None: d["agua"] = agua_val

                        if d["temp"] is not None and d["hum"] is not None:
                            d["historial"].append({
                                "t": d["temp"],
                                "h": d["hum"],
                                "luz": d["luz"],
                                "agua": d["agua"],
                                "ts": ts_str
                            })
                            if len(d["historial"]) > MAX_HIST:
                                d["historial"].pop(0)

        # Limpieza al desconectar
        with self.serial_lock:
            if self.ser:
                try: self.ser.close()
                except: pass
                self.ser = None
        with lock_estado:
            if self.puerto in dispositivos:
                dispositivos[self.puerto]["conectado"] = False
                dispositivos[self.puerto]["temp"] = None
                dispositivos[self.puerto]["hum"] = None
                dispositivos[self.puerto]["luz"] = None
                dispositivos[self.puerto]["agua"] = None
        self.activo = False
        print(f"Hilo finalizado para {self.puerto}")

def gestor_puertos():
    """Hilo supervisor daemon: detecta puertos conectados y limpia desconectados periódicamente."""
    while True:
        try:
            puertos_actuales = detectar_todos_los_puertos()
            for idx, p in enumerate(puertos_actuales):
                if p not in workers or not workers[p].is_alive():
                    # Intento de conexión
                    w = ArduinoWorker(p, idx)
                    workers[p] = w
                    w.start()

            # Detectar puertos retirados físicamente
            with lock_estado:
                for p in list(dispositivos.keys()):
                    if p not in puertos_actuales:
                        dispositivos[p]["conectado"] = False
                        dispositivos[p]["temp"] = None
                        dispositivos[p]["hum"] = None
                        dispositivos[p]["luz"] = None
                        dispositivos[p]["agua"] = None
                        if p in workers:
                            workers[p].activo = False
                            del workers[p]
        except Exception as e:
            print(f"Error en gestor de puertos: {e}")
        time.sleep(2)

def obtener_dispositivo_seleccionado(params=None):
    """Devuelve (puerto_activo, dict_dispositivo) según query params o el primer conectado."""
    nodo_req = None
    if params:
        nodo_req = params.get("nodo", [None])[0] or params.get("puerto", [None])[0] or params.get("id", [None])[0]

    with lock_estado:
        # 1. Si se pidió un nodo explícito
        if nodo_req:
            for p, d in dispositivos.items():
                if p == nodo_req or d.get("id") == nodo_req or os.path.basename(p) == nodo_req:
                    return p, dict(d)
        
        # 2. Primer dispositivo actualmente conectado
        for p, d in dispositivos.items():
            if d.get("conectado"):
                return p, dict(d)
        
        # 3. Primer dispositivo aunque esté desconectado (o vacío)
        if dispositivos:
            p = sorted(dispositivos.keys())[0]
            return p, dict(dispositivos[p])
        
        # 4. Estado vacío por defecto si nunca se conectó ningún Arduino
        vacio = {
            "id": None,
            "alias": "Sin Arduino",
            "puerto": None,
            "conectado": False,
            "temp": None,
            "hum": None,
            "luz": None,
            "agua": None,
            "ts": None,
            "hora": None,
            "fecha": None,
            "actuadores": {"buzzer": False},
            "log_act": [],
            "historial": []
        }
        return None, vacio

def obtener_estado(params=None):
    """Genera el JSON consolidado multidispositivo con retrocompatibilidad 100% en la raíz."""
    puerto_activo, dev = obtener_dispositivo_seleccionado(params)
    with lock_estado:
        conectados = sum(1 for d in dispositivos.values() if d.get("conectado"))
        resumen_disp = {}
        for p, d in dispositivos.items():
            resumen_disp[p] = {
                "id": d.get("id"),
                "alias": d.get("alias"),
                "puerto": p,
                "conectado": d.get("conectado", False),
                "temp": d.get("temp"),
                "hum": d.get("hum"),
                "luz": d.get("luz"),
                "agua": d.get("agua"),
                "ts": d.get("ts"),
                "actuadores": d.get("actuadores", {})
            }

    # Estructura retrocompatible (campos raíz mapeados al nodo activo)
    resp = {
        "temp": dev.get("temp"),
        "hum": dev.get("hum"),
        "luz": dev.get("luz"),
        "agua": dev.get("agua"),
        "ts": dev.get("ts"),
        "hora": dev.get("hora"),
        "fecha": dev.get("fecha"),
        "arduino_conectado": dev.get("conectado", False),
        "puerto": puerto_activo,
        "historial": dev.get("historial", []),
        "actuadores": dev.get("actuadores", {"buzzer": False}),
        "log_act": dev.get("log_act", []),
        # Extensiones multidispositivo:
        "nodo_activo": dev.get("id"),
        "alias_activo": dev.get("alias"),
        "total_conectados": conectados,
        "dispositivos": resumen_disp
    }
    return resp

def listar_dispositivos():
    with lock_estado:
        conectados = sum(1 for d in dispositivos.values() if d.get("conectado"))
        return {
            "total_conectados": conectados,
            "dispositivos": [
                {
                    "id": d.get("id"),
                    "alias": d.get("alias"),
                    "puerto": p,
                    "conectado": d.get("conectado", False),
                    "temp": d.get("temp"),
                    "hum": d.get("hum"),
                    "luz": d.get("luz"),
                    "agua": d.get("agua"),
                    "ts": d.get("ts")
                }
                for p, d in sorted(dispositivos.items())
            ]
        }

def enviar_a_arduino(cmd, puerto=None):
    if not workers:
        return "no hay puertos Arduino detectados"
    target_worker = None
    if puerto and puerto in workers and workers[puerto].is_alive():
        target_worker = workers[puerto]
    else:
        # Enviar al primer worker conectado
        for w in workers.values():
            if w.is_alive() and getattr(w, "ser", None) and w.ser.is_open:
                target_worker = w
                break
    if not target_worker:
        return "no hay conexión activa con Arduino"
    return target_worker.enviar(cmd)

def correr(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout.strip()
    except Exception as e:
        return "error: " + str(e)

def estado_red():
    info = {}
    ssid = correr(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
    info["ssid_activo"] = ""
    for l in ssid.splitlines():
        if l.startswith("yes:"):
            info["ssid_activo"] = l.split(":", 1)[1]
    ip = correr(["hostname", "-I"])
    info["ip"] = ip.strip().split()[0] if ip.strip() else ""
    net = correr(["nmcli", "-t", "-f", "state", "general"])
    info["estado_networking"] = net
    info["internet"] = correr(["nmcli", "-t", "-f", "CONNECTIVITY", "general"])
    mem = correr(["free", "-m"])
    try:
        for l in mem.splitlines():
            if l.startswith("Mem:"):
                p = l.split()
                info["ram"] = {"total": p[1], "usada": p[2], "libre": p[3]}
                break
    except:
        info["ram"] = {}
    info["uptime"] = correr(["uptime", "-p"])
    info["temp_cpu"] = "--"
    for tp in ["/sys/class/thermal/thermal_zone0/temp"]:
        if os.path.exists(tp):
            try:
                with open(tp) as f: raw = f.read().strip()
                if raw.isdigit():
                    info["temp_cpu"] = round(int(raw) / 1000, 1)
                    break
            except: pass
    info["remote_url"] = REMOTE_URL
    info["cloudflare_url"] = REMOTE_URL
    return info

def escanear():
    try:
        correr(["sudo", "nmcli", "dev", "wifi", "rescan"])
        time.sleep(4)
    except: pass
    salida = correr(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    redes = []
    vistos = set()
    for l in salida.splitlines():
        p = l.split(":")
        if len(p) < 2: continue
        ssid = p[0]
        senal = p[1] if len(p) > 1 else ""
        seg = p[2] if len(p) > 2 else ""
        if ssid and ssid not in vistos:
            vistos.add(ssid)
            redes.append({"ssid": ssid, "senal": senal, "seguridad": seg})
    return redes

def redes_guardadas():
    salida = correr(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])
    lista = []
    for l in salida.splitlines():
        p = l.split(":")
        if len(p) >= 2 and p[1].startswith("802-11-wireless"):
            lista.append(p[0])
    return lista

def conectar(ssid, clave):
    guardadas = redes_guardadas()
    if ssid in guardadas:
        r = correr(["sudo", "nmcli", "con", "up", ssid])
    else:
        cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid]
        if clave:
            cmd += ["password", clave]
        r = correr(cmd)
    return r

def olvidar(nombre):
    return correr(["sudo", "nmcli", "con", "delete", nombre])

class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html(self, nombre):
        posibles = [os.path.join(BASE_DIR, nombre), os.path.join("/home/nico/dashboard", nombre)]
        html = None
        for ruta in posibles:
            if os.path.exists(ruta):
                try:
                    with open(ruta, "rb") as f:
                        html = f.read()
                        break
                except: pass
        if html is None:
            self._json({"error": "no encontrado " + nombre}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def do_GET(self):
        parsed = urlparse(self.path)
        ruta = parsed.path
        params = parse_qs(parsed.query)

        if ruta == "/":
            self._html("index_clases.html")
        elif ruta == "/clase3":
            self._html("dashboard.html")
        elif ruta in ("/clase4", "/dashboard_clase4.html"):
            self._html("dashboard_clase4.html")
        elif ruta == "/dashboard.html":
            self._html("dashboard.html")
        elif ruta == "/panel":
            self._html("panel.html")
        elif ruta == "/datos":
            self._json(obtener_estado(params))
        elif ruta == "/api/clase4/datos":
            self._json(obtener_estado(params))
        elif ruta == "/api/dispositivos":
            self._json(listar_dispositivos())
        elif ruta == "/api/actuador":
            puerto_activo, dev = obtener_dispositivo_seleccionado(params)
            self._json({"actuadores": dev.get("actuadores", {})})
        elif ruta == "/api/estado":
            self._json(estado_red())
        elif ruta == "/api/escanear":
            self._json(escanear())
        elif ruta == "/api/redes_guardadas":
            self._json(redes_guardadas())
        else:
            self._json({"error": "no existe " + ruta}, 404)

    def _auth_deploy(self):
        auth = self.headers.get("Authorization", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
        try:
            with open("/home/nico/.deploy_token") as f:
                expected = f.read().strip()
        except:
            expected = ""
        if expected and token == expected:
            return True
        return False

    def do_POST(self):
        parsed = urlparse(self.path)
        ruta = parsed.path
        ln = int(self.headers.get("Content-Length", 0))
        body = {}
        if ln:
            try:
                raw = self.rfile.read(ln)
                body = json.loads(raw.decode())
            except:
                body = {}

        if ruta in ("/api/clase4/actuador", "/api/actuador", "/api/clase4/actuadores"):
            cmd = body.get("cmd", "")
            puerto = body.get("puerto")
            if not cmd:
                self._json({"error": "falta cmd"}, 400)
                return
            res = enviar_a_arduino(cmd, puerto)
            _, dev = obtener_dispositivo_seleccionado({"puerto": [puerto]} if puerto else None)
            self._json({
                "result": res,
                "puerto": puerto or dev.get("puerto"),
                "estado": dev.get("actuadores", {}),
                "log": dev.get("log_act", [])[-5:]
            })
        elif ruta == "/api/deploy":
            token_ok = self._auth_deploy()
            if not token_ok and body.get("token"):
                try:
                    with open("/home/nico/.deploy_token") as f:
                        expected = f.read().strip()
                    token_ok = (body.get("token") == expected)
                except: pass
            if not token_ok:
                self._json({"error": "unauthorized - token invalido"}, 401)
                return
            log = []
            try:
                r = subprocess.run(["git", "-C", "/home/nico/estacion-ci", "fetch"], capture_output=True, text=True, timeout=20)
                log.append("git fetch: " + (r.stdout.strip() or r.stderr.strip() or "ok"))
                r = subprocess.run(["git", "-C", "/home/nico/estacion-ci", "reset", "--hard", "origin/main"], capture_output=True, text=True, timeout=20)
                log.append("git reset: " + (r.stdout.strip() or r.stderr.strip()))
                r2 = subprocess.run(["rsync", "-av", "/home/nico/estacion-ci/dashboard/", "/home/nico/dashboard/", "--exclude", ".git"], capture_output=True, text=True, timeout=20)
                log.append("rsync: " + r2.stdout.strip()[:500])
                # Auto-restart: proceso detached que mata el viejo y arranca el nuevo
                subprocess.Popen(
                    ["/bin/bash", "-c",
                     "sleep 2; pkill -f servidor_datos.py; sleep 1; "
                     "setsid python3 -u /home/nico/dashboard/servidor_datos.py "
                     "> /tmp/c8000.log 2>&1 < /dev/null &"],
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True
                )
                log.append("auto-restart programado en ~3s")
            except Exception as e:
                log.append("error: " + str(e))
            self._json({"result": "deploy iniciado", "log": log})
        elif ruta == "/api/conectar":
            ssid = body.get("ssid", "")
            clave = body.get("clave", "")
            res = conectar(ssid, clave)
            self._json({"resultado": res})
        elif ruta == "/api/olvidar":
            nombre = body.get("nombre", "")
            res = olvidar(nombre)
            self._json({"resultado": res})
        else:
            self._json({"error": "no existe POST " + ruta}, 404)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    t = threading.Thread(target=gestor_puertos, daemon=True)
    t.start()
    print("Servidor unificado multi-Arduino listo en puerto 8000 (PID %d)" % os.getpid())
    try:
        HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido")

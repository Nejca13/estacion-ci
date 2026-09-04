# Estación Meteorológica — CEAER IoT

Repo CI/CD para dashboards y servidor (Pi Zero). Trabajamos en local, desplegamos a la Pi sin editar directo en el host.

## Estructura

```
estacion-ci/
├── dashboard/           # Archivos que se despliegan a /home/nico/dashboard en la Pi
│   ├── index_clases.html      # Selector Clase 3 / Clase 4 (ruta /)
│   ├── dashboard.html         # Clase 3 — DHT11 + CSV 9600
│   ├── dashboard_clase4.html  # Clase 4 — Structs+Punteros, LDR/agua/hora + actuadores (sin emojis, iconos SVG)
│   ├── panel.html
│   ├── servidor_datos.py      # Servidor unificado :8000 (ver Rutas)
│   └── clase4_estacion.ino    # Sketch Arduino Clase 4 (struct Sensor + leer_todos)
├── clases/clase4/       # HTML de la materia (bloques, ejercicios) — edición local
├── scripts/deploy.sh    # Deploy manual por SSH
└── .github/workflows/deploy.yml  # CI/CD GitHub Actions → Pi
```

## Rutas del servicio unificado :8000 (un solo túnel)

| Ruta | Qué sirve |
|------|-----------|
| `/` | `index_clases.html` — selector Clase 3 / Clase 4 |
| `/clase3` | `dashboard.html` (Clase 3) |
| `/clase4` | `dashboard_clase4.html` (Clase 4) |
| `/panel` | `panel.html` |
| `/datos` | JSON temp/hum/luz/agua + historial (Clase 3 compat) |
| `/api/clase4/datos` | alias de `/datos` (mismo estado extendido) |
| `POST /api/clase4/actuador` `{"cmd":"LED_ON"}` | Escribe a `/dev/ttyACM*` 9600, responde `{"result":...}` |

Servidor parsea `CSV2` `temp,hum` (Clase 3) y `CSV4` `temp,hum,luz,agua` (Clase 4). Si solo llega CSV2, simula `luz/agua` para que Clase 4 no quede vacía.

## Pi Zero (192.168.0.43)

* Usuario `nico` / pass `011539` (SSH 22)
* Servicio: `python3 -u /home/nico/dashboard/servidor_datos.py` (autostart `@reboot` crontab)
* Túnel: `cloudflared tunnel --url http://localhost:8000` (autostart `@reboot`, un solo túnel)
* Último túnel: `https://reading-citysearch-explained-enable.trycloudflare.com` (cambia al reiniciar)
* LAN: `http://192.168.0.43:8000/` `/clase3` `/clase4`

## Flujo local

```bash
git clone <repo> estacion-ci
# editar dashboard/* o clases/*
./scripts/deploy.sh        # rsync + restart remoto
# o push a main → GitHub Actions despliega automático (ver .github/workflows)
```

## Hardware Clase 4

`clase4_estacion.ino`: DHT11 D2, LDR A1, Agua A2, LM35 A0, LEDs D8-10, Relay D7. Envia `temp,hum,luz,agua` cada 2000ms `millis()`, atiende `LED_ON/OFF`, `RELAY_ON/OFF`, `FAN_0..255/AUTO`.

## Convenciones

* HTML sin emojis — usar iconos SVG (heroicons). `dashboard_clase4.html` ya migrado (5 SVG).
* No editar directo en Pi; todo via git + deploy.

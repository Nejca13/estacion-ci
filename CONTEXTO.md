# Contexto hasta 2026-09-04

## Resumen ejecutivo

Materia: Programación en C/C++ — Tecnicatura IoT CEAER. Clases 1-3 ya dadas, lunes es Clase 4. Se pidió que Clase 4 cuadre con 1-3 y que tenga más práctica Arduino con estación meteorológica.

## Estado de clases

* **Clase 1** (`clase1_completa.html`): variables/tipos/`printf`/`sizeof`/operadores — base OK.
* **Clase 2** (`clase2_completa.html`): `if/switch/ternario/scope` con hardware simulado + preview punteros — anticipa clase 4.
* **Clase 3** (`clase3_completa.html`): `for/while/do-while/millis()/Serial 9600/CSV` + DHT11 HW-481 real + `dashboard.html` + Web Serial. Primer hardware real.
* **Clase 4** original condensaba `struct+punternos+array+menu LCD` en 4hs con `gcc/rand/usleep` (no Arduino) — ruptura de continuidad y sobrecarga vs plan oficial (`contexto_clases.txt`: C4=punteros, C5=arrays, C6=structs). Se ajustó:
  * `clase4_resumen.html`: puente explícito C1→C3, hardware `DHT D2 + LM35 A0 + LDR A1 (+agua A2)` con fallback `SIMULACION`.
  * `clase4_bloque1.html`: `struct Sensor` + `enum TipoSensor` + array centralizado, práctica Serial.
  * `clase4_bloque2.html`: `leer_sensor(Sensor *s)` versión Arduino real (`analogRead`/`dht.readTemperature`/`isnan`) con `#ifdef SIMULACION`, `calibrar`/`verificar_alertas` con `ptr->campo`.
  * `clase4_bloque3.html`: `leer_todos/calibrar_todos/alertar_todos/buscar_sensor` delegando en `leer_sensor(&s)` + menú no bloqueante `millis()/digitalRead D3/D4` + sistema completo `loop()` con CSV a dashboard.
  * `clase4_completa.html` regenerada.

## Pi Zero (nico@192.168.0.43:8000, cloudflared)

* Servidor original `servidor_datos.py` en `:8000` leía CSV `temp,hum` → `/datos` + `panel.html` + `dashboard.html` (Clase 3). **No tocar** archivos de Clase 3, solo agregar nuevo HTML para Clase 4.

### Evolución

1. **09-04 11:43** — Creado `dashboard_clase4.html` (16K) estilo idéntico a `dashboard.html` pero con: temp/hum + **LDR luz** (pill DIA/TARDE/NOCHE), **agua**, **hora/fecha**, gráfico 3 series, **actuadores** LED D8 / Relay D7 / Fan PWM. + `servidor_clase4.py` en `:8001` con segundo túnel (duplicado, descartado).

2. **Simulación luz/agua**: `servidor_datos.py` (unificado) y `dashboard_clase4.html` simulan valores si Arduino solo manda `temp,hum` (CSV2) — `luz` según hora (día 650+rand / noche 80+rand), `agua` aleatoria. Si llega CSV4 `temp,hum,luz,agua` usa reales.

3. **Unificación a un solo servicio** (pedido 11:52): se pidió ordenar por clases en mismo `:8000`, un solo túnel.
   * Creado `index_clases.html` selector Clase 3 / Clase 4.
   * `servidor_datos.py` reescrito unificado (backup `servidor_datos.py.bak_clase3`): rutas `/`→index, `/clase3`→dashboard, `/clase4`→dashboard_clase4, `/datos` y `/api/clase4/datos` mismo estado, `POST /api/clase4/actuador`→`enviar_a_arduino()` (abre `/dev/ttyACM*` 9600, escribe `LED_ON` etc.).
   * Eliminado `:8001` y segundo `cloudflared`; queda solo `:8000` + 1 túnel `https://reading-citysearch-explained-enable.trycloudflare.com`.
   * Autostart `@reboot` crontab: `python3 -u servidor_datos.py` + `cloudflared`.

4. **Caída y recuperación**: 12:00 Pi sin ping (100% loss), volvió a 12:02 tras reboot (`up 2 min`, reconectado `/dev/ttyUSB0`). Túnel relanzado con nueva URL `reading-citysearch...` (antes `chassis-colors...` y `row-measurement...`).

5. **Emojis → iconos**: 12:07 pedido “html sin emojis, usamos iconos”. Reemplazados en `dashboard_clase4.html`: 💡→svg lightbulb, 🚿→svg shower, 🌀→svg fan, ◐→svg circle-half, ✗→svg x (5 SVG, 0 emojis).

## Archivos clave

* Pi: `/home/nico/dashboard/` → `dashboard.html`, `dashboard_clase4.html`, `index_clases.html`, `panel.html`, `servidor_datos.py`, `clase4_estacion.ino`
* Local: `Programacion en C y C++/clase 4/` → bloques actualizados + `clase4_estacion.ino` + `dashboard_clase4.html`
* Este repo: `estacion-ci/dashboard/` espejo de los anteriores para CI/CD.

## Próximos pasos

* Cargar `clase4_estacion.ino` en Arduino y conectar a Pi (USB) para datos reales CSV4.
* Trabajar en local en `estacion-ci` y desplegar con `scripts/deploy.sh` o push → Actions (no editar en Pi).

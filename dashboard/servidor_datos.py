import os, re, threading, time, json, subprocess, glob
from http.server import BaseHTTPRequestHandler, HTTPServer
try:
    import serial
except ImportError:
    serial = None
BAUD = 9600
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
estado = {"temp": None, "hum": None, "ts": None, "arduino_conectado": False, "puerto": None, "historial": [], "luz": None, "agua": None, "hora": None, "fecha": None, "actuadores": {"led": False, "relay": False, "fan": 0}, "log_act": []}
def detectar_puerto():
    for pat in ["/dev/ttyACM*", "/dev/ttyUSB*"]:
        for p in sorted(glob.glob(pat)): return p
    return None
def buscar_puerto():
    if serial is None: return None
    p = detectar_puerto()
    if p:
        try: s = serial.Serial(p, BAUD, timeout=1); s.close(); return p
        except: pass
    return None
def enviar_a_arduino(cmd):
    if serial is None: return "simulado: "+cmd
    p = detectar_puerto()
    if not p: return "no hay puerto Arduino"
    try:
        s = serial.Serial(p, BAUD, timeout=1); s.reset_input_buffer(); s.write((cmd+"\n").encode()); s.flush(); time.sleep(0.25); resp=""
        while s.in_waiting: resp+=s.readline().decode(errors="ignore")
        s.close()
        estado["log_act"].append({"cmd":cmd,"resp":resp.strip(),"ts":time.strftime("%H:%M:%S")})
        if len(estado["log_act"])>20: estado["log_act"].pop(0)
        if cmd=="LED_ON": estado["actuadores"]["led"]=True
        elif cmd=="LED_OFF": estado["actuadores"]["led"]=False
        elif cmd=="RELAY_ON": estado["actuadores"]["relay"]=True
        elif cmd=="RELAY_OFF": estado["actuadores"]["relay"]=False
        elif cmd.startswith("FAN_"):
            try:
                if cmd=="FAN_AUTO": estado["actuadores"]["fan"]="AUTO"
                else: estado["actuadores"]["fan"]=int(cmd.split("_")[1])
            except: pass
        return resp.strip() or "ok: "+cmd
    except Exception as e: return "error: "+str(e)
def leer_serial():
    if serial is None: print("[ADVERTENCIA] serial no disponible"); return
    csv2 = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*$")
    csv4 = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*$")
    t_re = re.compile(r"[Tt]emperatura:\s*([0-9.]+)"); h_re = re.compile(r"[Hh]umedad:\s*([0-9.]+)")
    ser=None
    while True:
        if ser is None:
            estado["arduino_conectado"]=False; estado["puerto"]=None
            p=buscar_puerto()
            if p is None: time.sleep(2); continue
            try: ser=serial.Serial(p, BAUD, timeout=1); estado["arduino_conectado"]=True; estado["puerto"]=p; print("Conectado a",p)
            except: ser=None; time.sleep(2); continue
        try: linea=ser.readline().decode("utf-8","ignore").strip()
        except:
            try: ser.close()
            except: pass
            ser=None; estado["arduino_conectado"]=False; continue
        if not linea: continue
        if linea in ("ESTACION_METEO_CSV","ERROR"):
            if linea=="ERROR": estado["ts"]=time.strftime("%H:%M:%S")
            continue
        if linea.startswith("AHORA "): linea=linea[6:].strip()
        if linea.startswith("ECO:") or linea.startswith("COMANDO"):
            if linea.startswith("COMANDO OK:"): estado["log_act"].append({"cmd":linea,"resp":"arduino","ts":time.strftime("%H:%M:%S")})
            continue
        cambio=False
        m4=csv4.match(linea)
        if m4:
            try: estado["temp"]=float(m4.group(1)); estado["hum"]=float(m4.group(2)); estado["luz"]=float(m4.group(3)); estado["agua"]=float(m4.group(4)); cambio=True
            except: pass
        else:
            m2=csv2.match(linea)
            if m2:
                try: estado["temp"]=float(m2.group(1)); estado["hum"]=float(m2.group(2)); cambio=True
                except: pass
            else:
                mt=t_re.search(linea); mh=h_re.search(linea)
                if mt:
                    try: estado["temp"]=float(mt.group(1)); cambio=True
                    except: pass
                if mh:
                    try: estado["hum"]=float(mh.group(1)); cambio=True
                    except: pass
                if not cambio and not (mt or mh): continue
        if cambio:
            ts_str=time.strftime("%H:%M:%S"); estado["ts"]=ts_str; estado["hora"]=time.strftime("%H:%M:%S"); estado["fecha"]=time.strftime("%Y-%m-%d")
            if estado["luz"] is None:
                h=time.localtime().tm_hour; import random; base=650+random.randint(0,120) if 7 <= h <= 19 else 80+random.randint(0,80); estado["luz"]=base
            if estado["agua"] is None:
                import random; estado["agua"]=700+random.randint(0,200) if random.random()<0.15 else 120+random.randint(0,80)
            if estado["temp"] is not None and estado["hum"] is not None:
                estado["historial"].append({"t":estado["temp"],"h":estado["hum"],"luz":estado["luz"],"agua":estado["agua"],"ts":ts_str})
                if len(estado["historial"])>40: estado["historial"].pop(0)
def correr(cmd):
    try: r=subprocess.run(cmd,capture_output=True,text=True,timeout=20); return r.stdout.strip()
    except Exception as e: return "error: "+str(e)
REMOTE_URL = "https://nejca-iot.tail4284c3.ts.net"

def get_remote_url():
    return REMOTE_URL

def estado_red():
    info={}
    ssid=correr(["nmcli","-t","-f","active,ssid","dev","wifi"]); info["ssid_activo"]=""
    for l in ssid.splitlines():
        if l.startswith("yes:"): info["ssid_activo"]=l.split(":",1)[1]
    ip=correr(["hostname","-I"]); info["ip"]=ip.strip().split()[0] if ip.strip() else ""
    net=correr(["nmcli","-t","-f","state","general"]); info["estado_networking"]=net
    info["internet"]=correr(["nmcli","-t","-f","CONNECTIVITY","general"])
    mem=correr(["free","-m"])
    try:
        for l in mem.splitlines():
            if l.startswith("Mem:"):
                p=l.split(); info["ram"]={"total":p[1],"usada":p[2],"libre":p[3]}; break
    except: info["ram"]={}
    info["uptime"]=correr(["uptime","-p"]); info["temp_cpu"]="--"
    for tp in ["/sys/class/thermal/thermal_zone0/temp"]:
        if os.path.exists(tp):
            try:
                with open(tp) as f: raw=f.read().strip()
                if raw.isdigit(): info["temp_cpu"]=round(int(raw)/1000,1); break
            except: pass
    info["remote_url"]=REMOTE_URL
    info["cloudflare_url"]=REMOTE_URL
    return info
def escanear():
    try: correr(["sudo","nmcli","dev","wifi","rescan"]); time.sleep(4)
    except: pass
    salida=correr(["nmcli","-t","-f","SSID,SIGNAL,SECURITY","dev","wifi","list"])
    redes=[]; vistos=set()
    for l in salida.splitlines():
        p=l.split(":")
        if len(p)<2: continue
        ssid=p[0]; senal=p[1] if len(p)>1 else ""; seg=p[2] if len(p)>2 else ""
        if ssid and ssid not in vistos: vistos.add(ssid); redes.append({"ssid":ssid,"senal":senal,"seguridad":seg})
    return redes
def redes_guardadas():
    salida=correr(["nmcli","-t","-f","NAME,TYPE","con","show"])
    lista=[]
    for l in salida.splitlines():
        p=l.split(":")
        if len(p)>=2 and p[1].startswith("802-11-wireless"): lista.append(p[0])
    return lista
def conectar(ssid,clave):
    guardadas=redes_guardadas()
    if ssid in guardadas: r=correr(["sudo","nmcli","con","up",ssid])
    else:
        cmd=["sudo","nmcli","dev","wifi","connect",ssid]
        if clave: cmd+=["password",clave]
        r=correr(cmd)
    return r
def olvidar(nombre): return correr(["sudo","nmcli","con","delete",nombre])
class Handler(BaseHTTPRequestHandler):
    def _json(self,obj,code=200):
        b=json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def _html(self,nombre):
        posibles=[os.path.join(BASE_DIR,nombre), os.path.join("/home/nico/dashboard",nombre)]
        html=None
        for ruta in posibles:
            if os.path.exists(ruta):
                try:
                    with open(ruta,"rb") as f: html=f.read(); break
                except: pass
        if html is None: self._json({"error":"no encontrado "+nombre},404); return
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(html))); self.end_headers(); self.wfile.write(html)
    def do_GET(self):
        ruta=self.path.split("?")[0]
        if ruta=="/": self._html("index_clases.html")
        elif ruta=="/clase3": self._html("dashboard.html")
        elif ruta=="/clase4": self._html("dashboard_clase4.html")
        elif ruta=="/dashboard_clase4.html": self._html("dashboard_clase4.html")
        elif ruta=="/dashboard.html": self._html("dashboard.html")
        elif ruta=="/panel": self._html("panel.html")
        elif ruta=="/datos": self._json(estado)
        elif ruta=="/api/clase4/datos": self._json(estado)
        elif ruta=="/api/actuador": self._json({"actuadores":estado["actuadores"]})
        elif ruta=="/api/estado": self._json(estado_red())
        elif ruta=="/api/escanear": self._json(escanear())
        elif ruta=="/api/redes_guardadas": self._json(redes_guardadas())
        else: self._json({"error":"no existe "+ruta},404)
    def _auth_deploy(self):
        # Soporta Authorization: Bearer <token> o body.token
        auth=self.headers.get("Authorization","")
        token=""
        if auth.startswith("Bearer "): token=auth[7:].strip()
        # fallback: leer token de body si no vino en header (se lee afuera)
        # compara con /home/nico/.deploy_token
        try:
            with open("/home/nico/.deploy_token") as f: expected=f.read().strip()
        except: expected=""
        if expected and token==expected: return True
        # también acepta token en body (para curl simple)
        return False

    def do_POST(self):
        ruta=self.path.split("?")[0]
        ln=int(self.headers.get("Content-Length",0))
        body={}
        raw=b""
        if ln:
            try:
                raw=self.rfile.read(ln)
                body=json.loads(raw.decode())
            except: body={}
        if ruta in ("/api/clase4/actuador","/api/actuador","/api/clase4/actuadores"):
            cmd=body.get("cmd","")
            if not cmd: self._json({"error":"falta cmd"},400); return
            res=enviar_a_arduino(cmd); self._json({"result":res,"estado":estado["actuadores"],"log":estado["log_act"][-5:]})
        elif ruta=="/api/deploy":
            # Deploy por HTTP usando túnel Tailscale Funnel / LAN - verifica token
            token_ok=self._auth_deploy()
            # también acepta token en JSON body
            if not token_ok and body.get("token"):
                try:
                    with open("/home/nico/.deploy_token") as f: expected=f.read().strip()
                    token_ok=(body.get("token")==expected)
                except: pass
            if not token_ok:
                self._json({"error":"unauthorized - token invalido"},401); return
            # Ejecuta git pull en /home/nico/estacion-ci y copia dashboards (sin restart, lo hace el workflow vía SSH tailnet)
            log=[]
            try:
                r=subprocess.run(["git","-C","/home/nico/estacion-ci","pull"], capture_output=True, text=True, timeout=30)
                log.append("git pull: "+(r.stdout.strip() or r.stderr.strip()))
                r2=subprocess.run(["rsync","-av","/home/nico/estacion-ci/dashboard/","/home/nico/dashboard/","--exclude",".git"], capture_output=True, text=True, timeout=20)
                log.append("rsync: "+r2.stdout.strip()[:500])
                log.append("listo - reinicio via workflow SSH si es necesario")
            except Exception as e:
                log.append("error: "+str(e))
            self._json({"result":"deploy iniciado","log":log})
        elif ruta=="/api/conectar":
            ssid=body.get("ssid",""); clave=body.get("clave",""); res=conectar(ssid,clave); self._json({"resultado":res})
        elif ruta=="/api/olvidar":
            nombre=body.get("nombre",""); res=olvidar(nombre); self._json({"resultado":res})
        else: self._json({"error":"no existe POST "+ruta},404)
    def log_message(self,*a): pass
if __name__=="__main__":
    t=threading.Thread(target=leer_serial,daemon=True); t.start()
    print("Servidor unificado listo en puerto 8000 (PID %d)"%os.getpid())
    try: HTTPServer(("0.0.0.0",8000),Handler).serve_forever()
    except KeyboardInterrupt: print("\nDetenido")

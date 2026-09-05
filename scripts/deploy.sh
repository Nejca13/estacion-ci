#!/usr/bin/env bash
set -euo pipefail
# Deploy local dashboard/ → Pi /home/nico/dashboard + restart servicio

PI_HOST="${PI_HOST:-192.168.0.43}"
PI_USER="${PI_USER:-nico}"
PI_PASS="${PI_PASS:-011539}"
REMOTE_DIR="/home/nico/dashboard"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/dashboard"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Instalando sshpass..."
  sudo apt-get update -qq && sudo apt-get install -y -qq sshpass >/dev/null
fi

echo "→ Rsync $LOCAL_DIR → $PI_USER@$PI_HOST:$REMOTE_DIR (excluye __pycache__/*.pyc)"
sshpass -p "$PI_PASS" rsync -avz --progress \
  --exclude "__pycache__" --exclude "*.pyc" --exclude "*.pyo" --exclude ".git" \
  -e "ssh -o StrictHostKeyChecking=no" "$LOCAL_DIR/" "$PI_USER@$PI_HOST:$REMOTE_DIR/"

echo "→ Verificando servidor (Pi Zero: espera extra)"
sshpass -p "$PI_PASS" ssh -o StrictHostKeyChecking=no "$PI_USER@$PI_HOST" bash <<'EOS'
  set -e
  if ! python3 -c "import pymongo" >/dev/null 2>&1; then
    echo "Instalando dependencias en la Pi (pymongo[srv])..."
    pip3 install --break-system-packages "pymongo[srv]" 2>/dev/null || pip3 install "pymongo[srv]" 2>/dev/null || true
  fi
  echo "Reiniciando servidor_datos.py en :8000"
  pkill -f '[s]ervidor_datos.py' || true
  sleep 2
  pkill -9 -f '[s]ervidor_datos.py' || true
  sleep 1
  rm -rf /home/nico/dashboard/__pycache__ 2>/dev/null || true
  setsid /usr/bin/python3 -u /home/nico/dashboard/servidor_datos.py > /tmp/c8000.log 2>&1 < /dev/null &
  echo "Esperando Pi Zero (6s)..."
  sleep 6
  ss -tlnp | grep 8000 || echo "WARN: :8000 no escuchando"
  ps aux | grep "[s]ervidor_datos" || echo "WARN: no proceso"
  cat /tmp/c8000.log | head -n 30 || true
  echo "Dashboard (127.0.0.1:8000):"
  for p in "/" "/clase4" "/historico"; do
    echo -n "  $p: "
    curl -s -m 5 "http://127.0.0.1:8000$p" | grep -o '<title>.*</title>' | head -1 || echo "FAIL"
  done
EOS
# Verificación externa vía Funnel (público, no requiere LAN)
echo "→ Verificando Funnel https://nejca-iot.tail4284c3.ts.net"
for p in "/" "/clase4" "/historico"; do
  echo -n "  $p: "
  curl -s -m 10 "https://nejca-iot.tail4284c3.ts.net$p" | grep -o '<title>.*</title>' | head -1 || echo "FAIL (Funnel no responde, puede tardar 10s)"
done

echo "✓ Deploy OK. Local: http://$PI_HOST:8000/ (/clase4, /historico) | Remoto: https://nejca-iot.tail4284c3.ts.net"

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

echo "→ Rsync $LOCAL_DIR → $PI_USER@$PI_HOST:$REMOTE_DIR"
sshpass -p "$PI_PASS" rsync -avz --progress -e "ssh -o StrictHostKeyChecking=no" "$LOCAL_DIR/" "$PI_USER@$PI_HOST:$REMOTE_DIR/"

echo "→ Verificando servidor"
sshpass -p "$PI_PASS" ssh -o StrictHostKeyChecking=no "$PI_USER@$PI_HOST" bash <<'EOS'
  set -e
  if ! python3 -c "import pymongo" >/dev/null 2>&1; then
    echo "Instalando dependencias en la Pi (pymongo[srv])..."
    pip3 install --break-system-packages "pymongo[srv]" 2>/dev/null || pip3 install "pymongo[srv]" 2>/dev/null || true
  fi
  echo "Reiniciando servidor_datos.py en :8000"
  pkill -f servidor_datos.py || true
  sleep 1
  setsid python3 -u /home/nico/dashboard/servidor_datos.py > /tmp/c8000.log 2>&1 < /dev/null &
  sleep 2
  ss -tlnp | grep 8000 || echo "WARN: :8000 no escuchando"
  ps aux | grep "[s]ervidor_datos" || echo "WARN: no proceso"
  echo "Dashboard:"
  curl -s http://127.0.0.1:8000/ | grep -o '<title>.*</title>' | head -1
  curl -s http://127.0.0.1:8000/clase4 | grep -o '<title>.*</title>' | head -1
  curl -s http://127.0.0.1:8000/historico | grep -o '<title>.*</title>' | head -1
EOS

echo "✓ Deploy OK. Local: http://$PI_HOST:8000/ (/clase4, /historico) | Remoto: https://nejca-iot.tail4284c3.ts.net"

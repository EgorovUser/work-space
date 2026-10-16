#!/bin/sh
set -eu
cd /workspace
mkdir -p /workspace/data/logs

probe() {
  curl -sf -o /dev/null --max-time 2 "$1"
}

if probe "http://127.0.0.1:8080/" && probe "http://127.0.0.1:8000/healthz"; then
  exit 0
fi

if ! probe "http://127.0.0.1:8000/healthz"; then
  if [ -f /workspace/data/uvicorn.pid ] && kill -0 "$(cat /workspace/data/uvicorn.pid)" 2>/dev/null; then
    :
  else
    nohup /workspace/.venv/bin/uvicorn app.main:app --reload --reload-dir /workspace/app --host 0.0.0.0 --port 8000 >> /workspace/data/logs/uvicorn.log 2>&1 &
    echo $! > /workspace/data/uvicorn.pid
  fi
fi

if ! probe "http://127.0.0.1:8080/"; then
  if [ -f /workspace/data/vite.pid ] && kill -0 "$(cat /workspace/data/vite.pid)" 2>/dev/null; then
    :
  else
    cd /workspace/frontend
    nohup npm run dev >> /workspace/data/logs/vite.log 2>&1 &
    echo $! > /workspace/data/vite.pid
    cd /workspace
  fi
fi

i=0
while [ "$i" -lt 60 ]; do
  if probe "http://127.0.0.1:8080/" && probe "http://127.0.0.1:8000/healthz"; then
    exit 0
  fi
  i=$((i + 1))
  sleep 0.5
done

echo "startup failed" >&2
exit 1

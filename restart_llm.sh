#!/bin/bash
# Автоподъём llama-server (вызывается watchdog.py и вручную)
set -u

if pgrep -f "llama-server" > /dev/null 2>&1; then
    echo "llama-server уже запущен"
    exit 0
fi

MODEL="${CHAYOK_MODEL:-Bonsai-4B-Q1_0.gguf}"
cd /home/pi/llama.cpp || exit 1

if [ ! -f "models/$MODEL" ]; then
    echo "Нет модели models/$MODEL" >&2
    exit 1
fi

nohup ./build/bin/llama-server \
    -m "models/$MODEL" \
    --host 127.0.0.1 --port 8080 \
    -c 2048 -t 4 --no-webui \
    >> /tmp/bonsai.log 2>&1 &

echo "llama-server запущен с $MODEL"

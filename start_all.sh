#!/bin/bash
# ========================================
# ChayOK — ручной запуск (для терминала)
# Для автозапуска: sudo ./install_service.sh
# ========================================

set -u
cd /home/pi/ChayOK || exit 1

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/home/pi/.Xauthority}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export PULSE_SERVER="${PULSE_SERVER:-unix:/run/user/$(id -u)/pulse/native}"

# Строка на загрузочном экране. Если Plymouth уже завершился — пишем причину в лог.
boot_status() {
    err="$(plymouth update --status="$1" 2>&1 >/dev/null)" && return 0
    echo "[boot] не показать «$1»: ${err:-нет демона}" >&2
}

boot_status "Готовлю окружение"

if [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
else
    echo "venv не найден в /home/pi/ChayOK" >&2
    exit 1
fi

# Bonsai (llama.cpp) — поднимаем, если ещё не отвечает
BONSAI_URL="http://127.0.0.1:8080/v1/models"
boot_status "Проверяю модель"
if ! curl -sf -m 2 "$BONSAI_URL" > /dev/null; then
    if [ -x /home/pi/llama.cpp/build/bin/llama-server ]; then
        echo "Запускаю Bonsai (llama.cpp)..."
        boot_status "Запускаю модель"
        cd /home/pi/llama.cpp || exit 1
        nohup ./build/bin/llama-server \
            -m "models/${CHAYOK_MODEL:-Bonsai-4B-Q1_0.gguf}" \
            --host 127.0.0.1 --port 8080 \
            -c 2048 -t 4 --no-webui \
            > /tmp/bonsai.log 2>&1 &
        cd /home/pi/ChayOK || exit 1
        boot_status "Модель загружается"
        for _ in $(seq 1 30); do
            curl -sf -m 2 "$BONSAI_URL" > /dev/null && break
            sleep 1
        done
    else
        echo "llama-server не найден — останется резервный сервер на ПК" >&2
    fi
fi

echo "Запускаю ChayOK..."
boot_status "Запускаю ЧайОК"
exec python -u main.py

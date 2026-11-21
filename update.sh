#!/bin/bash
# Обновление ЧайОК из репозитория и перезапуск.
#
# Внимание: локальные правки отслеживаемых файлов будут перезаписаны версией
# из репозитория. Локальные настройки (notify.json, api.txt, alarm.json,
# volume.json) и модели лежат в .gitignore, их обновление не трогает.
set -u

APP_DIR="/home/pi/ChayOK"
REPO="${CHAYOK_REPO:-https://github.com/ilabolAfk/ChayOK.git}"
BRANCH="${CHAYOK_BRANCH:-main}"

cd "$APP_DIR" || exit 1

echo "== Обновление ЧайОК из $REPO ($BRANCH) =="

if [ ! -d .git ]; then
    echo "-- локального репозитория нет, инициализирую"
    git init -q || exit 1
    git remote add origin "$REPO" 2>/dev/null || git remote set-url origin "$REPO"
fi

git fetch --tags origin "$BRANCH" || { echo "Не удалось скачать обновление"; exit 1; }
git checkout -f -B "$BRANCH" "origin/$BRANCH" || { echo "Не удалось переключиться на $BRANCH"; exit 1; }

VERSION=$(git describe --tags --always 2>/dev/null || echo unknown)
echo "-- версия: $VERSION"

if [ -x venv/bin/pip ] && [ -f requirements.txt ]; then
    echo "-- зависимости"
    venv/bin/pip install -q -r requirements.txt || echo "pip: зависимости обновить не удалось"
fi

restart_app() {
    pkill -f 'python -u main.py' 2>/dev/null
    sleep 2
    nohup bash start_all.sh > /tmp/chayok_run.log 2>&1 &
    echo "-- запущено вручную, лог /tmp/chayok_run.log"
}

echo "-- перезапуск"
if systemctl is-active --quiet chayok 2>/dev/null; then
    if sudo -n systemctl restart chayok 2>/dev/null; then
        echo "-- служба chayok перезапущена"
    else
        echo "-- для systemctl нужен пароль sudo, перезапускаю вручную"
        restart_app
    fi
else
    restart_app
fi

sleep 3
if pgrep -f 'python -u main.py' > /dev/null; then
    echo "== Готово: $VERSION, приложение работает =="
else
    echo "== Обновлено до $VERSION, но приложение не поднялось — смотрите /tmp/chayok_run.log =="
    exit 1
fi

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

echo "-- перезапуск приложения"
# Приложение само подхватит изменения и сделает execv: без kill и без дублей
touch /tmp/chayok_reload
sleep 6

if pgrep -f 'main\.py' > /dev/null 2>&1; then
    echo "== Готово: $VERSION, приложение перезапускается по флагу =="
else
    echo "== Обновлено до $VERSION, но приложение не запущено =="
    echo "   Поднять: sudo systemctl start chayok  (или ./start_all.sh)"
    exit 1
fi

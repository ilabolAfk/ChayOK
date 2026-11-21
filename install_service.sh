#!/bin/bash
# ========================================
# Установка автозапуска ChayOK через systemd
# Запуск: sudo ./install_service.sh
# ========================================

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Запусти этот скрипт через sudo! (sudo ./install_service.sh)"
  exit 1
fi

SRC="/home/pi/ChayOK/chayok.service"
DST="/etc/systemd/system/chayok.service"

if [ ! -f "$SRC" ]; then
  echo "Не найден $SRC"
  exit 1
fi

echo "Копирую файл службы..."
install -m 644 "$SRC" "$DST"

echo "Перезагружаю конфигурацию systemd..."
systemctl daemon-reload

echo "Включаю автозапуск при загрузке..."
systemctl enable chayok.service

echo "Перезапускаю службу..."
systemctl restart chayok.service

echo "=========================================="
echo "Готово! Статус:  systemctl status chayok"
echo "Логи:           journalctl -u chayok -f"
echo "Остановить:     sudo systemctl stop chayok"
echo "=========================================="

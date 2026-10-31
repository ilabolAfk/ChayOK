#!/bin/bash
# ========================================
# ChayOK — полный запуск
# ========================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   ChayOK — запуск голосового помощника${NC}"
echo -e "${GREEN}========================================${NC}"

cd /home/pi/ChayOK || exit 1

# 1. Активация venv
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo -e "${RED}venv не найден!${NC}"
    exit 1
fi

# 2. Проверка Ollama на ПК (опционально)
echo -e "${YELLOW}[1/2] Проверяю связь с сервером Ollama...${NC}"
if curl -s --connect-timeout 3 http://192.168.1.108:11434/api/tags > /dev/null; then
    echo -e "${GREEN}  -> Сервер Ollama доступен.${NC}"
else
    echo -e "${YELLOW}  -> Сервер недоступен, будет использована локальная модель.${NC}"
fi

# 3. Запуск
echo -e "${YELLOW}[2/2] Запускаю ChayOK...${NC}"
echo -e "${GREEN}========================================${NC}"
python3 main.py
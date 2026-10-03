#!/bin/bash
# ========================================
# ChayOK — полный запуск
# Активирует venv, проверяет Ollama, запускает main.py
# ========================================

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   ChayOK — запуск голосового помощника${NC}"
echo -e "${GREEN}========================================${NC}"

# ========================================
# 1. Переходим в папку проекта
# ========================================
cd /home/pi/ChayOK || { echo -e "${RED}Папка /home/pi/ChayOK не найдена!${NC}"; exit 1; }

# ========================================
# 2. Активируем виртуальное окружение
# ========================================
if [ -f "venv/bin/activate" ]; then
    echo -e "${YELLOW}[1/4] Активирую venv...${NC}"
    source venv/bin/activate
else
    echo -e "${RED}venv не найден! Создай его командой:${NC}"
    echo -e "${YELLOW}python3 -m venv --system-site-packages venv${NC}"
    exit 1
fi

# ========================================
# 3. Проверяем зависимости
# ========================================
echo -e "${YELLOW}[2/4] Проверяю зависимости...${NC}"
python -c "import vosk, pyaudio, pygame, requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${RED}Не все зависимости установлены!${NC}"
    echo -e "${YELLOW}Устанавливаю...${NC}"
    pip install vosk pyaudio pygame requests
fi

# ========================================
# 4. Запускаем Ollama (если не запущен)
# ========================================
echo -e "${YELLOW}[3/4] Проверяю Ollama...${NC}"
if ! pgrep -x "ollama" > /dev/null; then
    echo -e "${YELLOW}Ollama не запущен. Запускаю в фоне...${NC}"
    ollama serve > /dev/null 2>&1 &
    sleep 3
else
    echo -e "${GREEN}Ollama уже запущен.${NC}"
fi

# Проверяем, есть ли модель
if ! ollama list | grep -q "qwen2.5"; then
    echo -e "${YELLOW}Модель qwen2.5 не найдена. Скачиваю...${NC}"
    ollama pull qwen2.5:0.5b-instruct
fi

# ========================================
# 5. Запускаем ЧайОК
# ========================================
echo -e "${YELLOW}[4/4] Запускаю ChayOK...${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Скажи 'ЧайОК' или нажми кнопку на экране${NC}"
echo -e "${GREEN}ESC — выход${NC}"
echo -e "${GREEN}========================================${NC}"

python main.py

# ========================================
# 6. После выхода
# ========================================
echo -e "${GREEN}ChayOK завершён.${NC}"
# ChayOK

<img width="839" height="485" alt="image" src="https://github.com/user-attachments/assets/325fdbcd-0b95-4ce1-9bd4-445d5fc41522" />

Автономный голосовой помощник на Raspberry Pi. Всё локально: STT (Vosk), LLM (Ollama + Qwen2.5), TTS (Piper), UI (Pygame).

Лицензия: **GPL v3**.

## Возможности

- Полностью офлайн (кроме погоды)
- Русский язык: STT, LLM, TTS, UI
- Сенсорный экран 5"
- Wake word: «ЧайОК»
- Погода (OpenWeatherMap)
- Редактор команд (Tkinter)
- Material-подобный интерфейс

## Железо

| Компонент | Характеристики |
|-----------|----------------|
| Pi | 4B, 4 GB |
| Экран | 5" IPS 800×480, MIPI-DSI, touch |
| Микрофон | USB |
| Колонка | USB / 3.5 мм |
| Питание | UPS HAT + 2×18650 |
| Охлаждение | радиаторы + вентилятор |

## Установка

```bash
git clone https://github.com/ilabolAfk/ChayOK.git
cd ChayOK
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

wget https://alphacephei.com/vosk/models/vosk-model-ru-0.22.zip
unzip vosk-model-ru-0.22.zip
mv vosk-model-ru-0.22 vosk-model

# Piper TTS + голос "Денис" — см. docs
Стек
Слой	Технология
STT	Vosk ru-0.22
LLM	Ollama + Qwen2.5 0.5B
TTS	Piper ru_RU-denis-medium
UI	Pygame 800×480
Mic	arecord plughw:4,0
Audio	pw-play
Структура
text
ChayOK/
├── main.py
├── alarm.py
├── start_all.sh
├── requirements.txt
├── vosk-model/
├── sounds/
└── README.md
License
GPL v3 · ilabolAfk

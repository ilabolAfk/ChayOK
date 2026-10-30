<img width="839" height="485" alt="image" src="https://github.com/user-attachments/assets/325fdbcd-0b95-4ce1-9bd4-445d5fc41522" />

# ChayOK

Автономный голосовой помощник с сенсорным экраном на Raspberry Pi 4B. 
Гибридная архитектура: локальная обработка звука на Pi + мощная LLM на ПК по сети.

## Стек

| Слой | Технология |
|------|------------|
| STT | Vosk (`vosk-model-small-ru-0.22`) |
| LLM | Ollama + Qwen2.5 (7B на ПК / 0.5B на Pi как fallback) |
| TTS | Piper (`ru_RU-ruslan-medium.onnx`) |
| UI | Pygame 800×480, NOFRAME |
| Mic | `arecord plughw:3,0` 44100 Hz mono |
| Audio | `pw-play` (PipeWire) |
| Battery | INA219 @ I2C 0x42 |

## Железо

- Raspberry Pi 4B (4 GB)
- 5" IPS 800×480 MIPI-DSI touch
- USB-микрофон (`USB PnP Sound Device`)
- USB-колонка (`UACDemoV1.0`)
- UPS HAT + 2×18650
- Радиаторы + вентилятор

## Установка (Raspberry Pi)

```bash
sudo raspi-config           # Interface Options → I2C → Yes
git clone <repo> && cd ChayOK
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install vosk pyaudio pygame requests smbus2

# Vosk
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
unzip vosk-model-small-ru-0.22.zip && mv vosk-model-small-ru-0.22 vosk-model

# Piper
cd /home/pi
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
tar -xf piper_linux_aarch64.tar.gz && mv piper_linux_aarch64 piper && cd piper
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx.json

# Shutdown без пароля
sudo visudo                 # pi ALL=(ALL) NOPASSWD: /sbin/shutdown
```
## Запуск
``` bash
./start_all.sh
Wake word: чайок / чаёк / чаек.

Конфиг (main.py)
python
WAKE_WORDS      = ["чайок", "чаек", "чаёк", "чай ок"]
COMMAND_SILENCE = 2.5      # сек тишины → отправка
MIC_CARD        = 3        # из arecord -l
MIC_DEVICE      = 0
SPK_CARD        = 4        # из aplay -l
SPK_DEVICE      = 0
WEATHER_API_KEY = "..."
CITY            = "Moscow"
```
## Особенности реализации
Потоковая генерация: ответ LLM появляется на экране по мере генерации.

Озвучка по предложениям: Piper запускается на каждое законченное предложение.

Блокировка звука (audio_lock): предотвращает наложение предложений друг на друга.

Стриминг дат: нейросеть инструктирована писать даты словами (27 октября).

Автоочистка промпта: слово «ЧайОК» вырезается из команды перед отправкой в LLM.

## Автозапуск
``` bash
crontab -e
#Добавить в конец файла:


@reboot sleep 30 && cd /home/pi/ChayOK && ./start_all.sh >> log.txt 2>&1
```
## Структура
ChayOK/
├── main.py
├── alarm.py
├── start_all.sh
├── logo.png
├── custom_commands.json
├── alarm.json
├── vosk-model/
├── sounds/{melody1..4}.mp3
└── README.md
## Troubleshooting

| Ошибка | Фикс |
|--------|------|
| LLM 404 | `ollama pull qwen2.5:7b-instruct` |
| Нет звука в LLM | Прописать IP ПК в `SERVER_OLLAMA_URL` |
| Mic not found | проверить `arecord -l`, обновить `MIC_CARD` |
| audio open error | использовать `pw-play`, проверить `audio_lock` |
| Battery `--%` | `i2cdetect -y 1` → 0x42 |
| Alarm пропускает минуту | `time.sleep(5)` в `alarm_checker` |

## License

GPL v3.

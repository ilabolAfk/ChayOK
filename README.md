# ChayOK

> Автономный голосовой помощник с сенсорным экраном на Raspberry Pi 4B.

Гибридная архитектура: **локальная обработка звука на Pi** + **мощная LLM на ПК по сети**. Устройство слышит слово пробуждения, понимает русскую речь и отвечает голосом на дисплее — без облачных сервисов.

![ChayOK](https://github.com/user-attachments/assets/325fdbcd-0b95-4ce1-9bd4-445d5fc41522)

## Как это работает

| Где | Роль |
| --- | ---- |
| Raspberry Pi | Звук, распознавание речи (STT), синтез голоса (TTS), сенсорный интерфейс |
| ПК (домашняя сеть) | Генерация ответа — Qwen2.5 7B через Ollama |
| Pi (fallback) | Qwen2.5 0.5B — если ПК недоступен |

## Возможности

- Wake word: **чайок / чаёк / чаек**
- Полностью на русском языке: STT, LLM, TTS, UI
- Сенсорный экран 5" с Material-подобным интерфейсом
- Мониторинг заряда батареи через датчик INA219
- Автоочистка промпта: слово «ЧайОК» вырезается из команды перед отправкой в LLM
- Даты словами: модель инструктирована писать «27 октября»
- Автозапуск при перезагрузке через crontab

## Железо

| Компонент | Характеристики |
| --------- | -------------- |
| Raspberry Pi 4B | 4 GB RAM |
| Дисплей | 5" IPS 800×480, MIPI-DSI, сенсорный |
| Микрофон | USB (`USB PnP Sound Device`) |
| Колонка | USB (`UACDemoV1.0`) |
| Питание | UPS HAT + 2×18650 |
| Управление батареей | INA219 по I2C (адрес 0x42) |
| Охлаждение | Радиаторы + вентилятор |

## Стек

| Слой | Технология |
| ---- | ---------- |
| STT | Vosk (`vosk-model-small-ru-0.22`) |
| LLM | Ollama + Qwen2.5 (7B на ПК / 0.5B на Pi) |
| TTS | Piper (`ru_RU-ruslan-medium.onnx`) |
| UI | Pygame 800×480, NOFRAME |
| Микрофон | `arecord plughw:3,0` 44100 Гц mono |
| Воспроизведение | `pw-play` (PipeWire) |
| Батарея | INA219 @ I2C 0x42 |

## Особенности реализации

- **Потоковая генерация** — ответ LLM появляется на экране по мере генерации.
- **Озвучка по предложениям** — Piper запускается на каждое законченное предложение.
- **audio_lock** — блокирует наложение предложений друг на друга.
- **Автоочистка промпта** — слово «ЧайОК» вырезается из команды перед отправкой в LLM.
- **Стриминг дат** — нейросеть инструктирована писать даты словами (например, «27 октября»).

## Конфигурация (`main.py`)

| Параметр | Значение по умолчанию | Что делает |
| -------- | --------------------- | ---------- |
| `WAKE_WORDS` | `["чайок", "чаек", "чаёк", "чай ок"]` | Слова пробуждения |
| `COMMAND_SILENCE` | `2.5` | Секунд тишины до отправки команды |
| `MIC_CARD` | `3` | Карта микрофона (из `arecord -l`) |
| `MIC_DEVICE` | `0` | Устройство микрофона |
| `SPK_CARD` | `4` | Карта колонки (из `aplay -l`) |
| `SPK_DEVICE` | `0` | Устройство колонки |
| `WEATHER_API_KEY` | `-` | Ключ OpenWeatherMap |
| `CITY` | `Moscow` | Город для прогноза погоды |

## Установка (Raspberry Pi)

```bash
# 1. Включить I2C
sudo raspi-config           # Interface Options → I2C → Yes

# 2. Клонировать и настроить окружение
git clone <repo> && cd ChayOK
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install vosk pyaudio pygame requests smbus2

# 3. Модель Vosk
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
unzip vosk-model-small-ru-0.22.zip && mv vosk-model-small-ru-0.22 vosk-model

# 4. Piper TTS
cd /home/pi
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
tar -xf piper_linux_aarch64.tar.gz && mv piper_linux_aarch64 piper && cd piper
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx.json

# 5. Выключение без пароля
sudo visudo                 # pi ALL=(ALL) NOPASSWD: /sbin/shutdown
```

## Запуск

```bash
./start_all.sh
```

Wake word: **чайок / чаёк / чаек**.

## Автозапуск

```bash
crontab -e
# Добавить в конец файла:
@reboot sleep 30 && cd /home/pi/ChayOK && ./start_all.sh >> log.txt 2>&1
```

## Структура проекта

```
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
```

## Troubleshooting

| Ошибка | Решение |
| ------ | ------- |
| LLM 404 | `ollama pull qwen2.5:7b-instruct` |
| Нет звука в LLM | Прописать IP ПК в `SERVER_OLLAMA_URL` |
| Mic not found | Проверить `arecord -l`, обновить `MIC_CARD` |
| audio open error | Использовать `pw-play`, проверить `audio_lock` |
| Battery `--%` | `i2cdetect -y 1` → 0x42 |
| Alarm пропускает минуту | `time.sleep(5)` в `alarm_checker` |

## License

GPL v3 · [ilabolAfk](https://github.com/ilabolAfk)

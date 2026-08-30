# Readme.md  
<img width="839" height="485" alt="image" src="https://github.com/user-attachments/assets/325fdbcd-0b95-4ce1-9bd4-445d5fc41522" />

#ChayOK — открытый голосовой помощник с экраном  
  
**ChayOK** — это полностью автономный голосовой помощник с сенсорным экраном, работающий на Raspberry Pi.    
Всё локально: распознавание речи (Vosk), генерация ответов (Ollama + Qwen2.5), синтез голоса (Piper TTS, голос "Денис"), интерфейс на Pygame.  
  
Проект создан в рамках open-source проекта и распространяется под лицензией GPL v3.  
  
---  
  
## 🎯 Особенности  
  
- ✅ Полностью локальный — не требует интернета для работы  
- ✅ Русский язык — распознавание, ответы, голос, интерфейс  
- ✅ Сенсорный экран  
- ✅ Голосовое пробуждение по ключевому слову ("ЧайОК")  
- ✅ Поддержка погоды через OpenWeatherMap API  
- ✅ Редактор пользовательских команд (Tkinter)  
- ✅material-design интерфейс  
- ✅open-source  
  
---  
  
## 🖼️ Скриншоты  
  
*Здесь будут фото устройства*  
  
---  
  
## 📦 Требования (железо)  
  
| Компонент | Модель / Характеристики |  
|-----------|--------------------------|  
| Raspberry Pi | 4B (4 ГБ ОЗУ) |  
| Экран | 5" IPS, 800×480, MIPI-DSI |  
| Микрофон | USB (любой поддерживаемый) |  
| Колонка | USB или 3.5 мм |  
| Питание | UPS HAT + 2×18650 (опционально) |  
| Охлаждение | Радиаторы + вентилятор |  
  
---  
  
## 🛠️ Установка на Raspberry Pi  
  
```bash  
git clone https://github.com/ilabolAfk/ChayOK.git  
cd ChayOK  
  
python3 -m venv venv  
source venv/bin/activate  
  
pip install -r requirements.txt  
  
wget https://alphacephei.com/vosk/models/vosk-model-ru-0.22.zip  
unzip vosk-model-ru-0.22.zip  
mv vosk-model-ru-0.22 vosk-model  
  
# Устанавливаем Piper TTS и скачиваем голос "Денис"  
# (подробности в документации проекта)  

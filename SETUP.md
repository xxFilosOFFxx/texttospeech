# Text to Speech Converter

Конвертер текстовых файлов в MP3 аудио с использованием Edge TTS или Silero.

## Поддерживаемые форматы

Входные файлы: TXT, PDF, EPUB, FB2
Выходной формат: MP3 (с разделением на главы по N минут)

## Установка

### 1. Создание виртуального окружения

```bash
python3 -m venv venv
```

### 2. Активация окружения

```bash
# Linux/Mac
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Установка дополнительных зависимостей (для Silero)

Если используется система с внешним управлением Python (PEP 668):

```bash
pip install --break-system-packages silero torch torchaudio
```

Или через conda:

```bash
conda install pytorch torchaudio pydub -c pytorch
```

## Использование

### CLI режим

```bash
# Конвертация файла в MP3 (один файл)
python tts_converter.py -i "book.txt" -o "output/" --voice "ru-RU-SvetlanaNeural"

# Конвертация с разделением на главы по 30 минут
python tts_converter.py -i "book.txt" -o "output/" --split 30 --voice "ru-RU-SvetlanaNeural"

# Использование Silero TTS
python tts_converter.py -i "book.txt" -o "output/" --tts silero --voice "xenia"

# Запуск Telegram бота
python tts_converter.py --bot "YOUR_BOT_TOKEN"
```

#### Аргументы CLI

| Аргумент | Описание | По умолчанию |
|---------|----------|--------------|
| `-i`, `--input` | Входной файл | (обязательно) |
| `-o`, `--output` | Папка для сохранения | ~/Desktop |
| `-v`, `--voice` | Голос TTS | ru-RU-SvetlanaNeural |
| `-s`, `--split` | Разделение на куски (минуты) | 0 (не делить) |
| `-t`, `--tts` | Тип движка: edge/silero | edge |
| `-g`, `--gui` | Запустить GUI | - |
| `-b`, `--bot` | Токен Telegram бота | - |

### GUI режим (PyQt6)

```bash
python tts_converter.py --gui
```

### Доступные голоса

#### Edge TTS

Русские:
- ru-RU-SvetlanaNeural (женский)
- ru-RU-DmitryNeural (мужской)
- ru-RU-ElizabethNeural (женский)

Английские:
- en-US-JennyNeural
- en-US-GuyNeural

Украинские:
- UK-RomanNeural
- UK-LydiaNeural

#### Silero TTS

Модель v5_ru (русский):
- xenia (женский)
- aidar (мужской)
- aleksandr (мужской)
- alyona (женский)
- anna (женский)
- danil (мужской)
- dasha (женский)
- emma (женский)
- iren (женский)
- max (мужской)
- oksana (женский)
- pavel (мужской)
- ruslan_k (мужской)
- tatiana (женский)

## Оптимальная настройка split_duration

Для аудиокниг рекомендуется:

- **30 минут** - оптимально для большинства плееров
- **15-20 минут** - если нужны короткие главы
- **0** - объединить в один файл

## Примеры использования

### Конвертация книги с разделением на 30-минутные главы

```bash
python tts_converter.py -i "Война и мир.txt" -o "audio/" --split 30
```

Создаст файлы:
```
audio/
  Война и мир_part0.mp3  (30 мин)
  Война и мир_part1.mp3  (30 мин)
  Война и мир_part2.mp3  (20 мин)
```

### Использование Silero для офлайн работы

```bash
python tts_converter.py -i "book.txt" -o "audio/" --tts silero --voice "xenia"
```

## Устранение проблем

### "command not found: python"

```bash
# Linux
which python3

# Использовать python3 вместо python
python3 tts_converter.py --gui
```

### " Externally-managed-environment"

```bash
# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Silero ошибки

```bash
# Установить torch и torchaudio
pip install torch torchaudio

# Или через pip с --break-system-packages
pip install --break-system-packages torch torchaudio
```

### Telegram бот

Для создания бота:
1. Открой @BotFather в Telegram
2. Используй /newbot
3. Скопируй токен
4. Запусти: `python tts_converter.py --bot "TOKEN"`
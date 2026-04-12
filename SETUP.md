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
source venv/bin/activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
pip install scipy soundfile
```

При проблемах с PEP 668:
```bash
pip install --break-system-packages scipy soundfile
```

## Использование

### GUI режим

```bash
python tts_converter.py --gui
```

### CLI режим

```bash
# Один файл
python tts_converter.py -i "book.txt" -o "output/" --voice "ru-RU-SvetlanaNeural"

# С разделением на главы
python tts_converter.py -i "book.txt" -o "output/" --split 30

# Silero TTS
python tts_converter.py -i "book.txt" -o "output/" --tts silero --voice "xenia"
```

### Telegram бот

```bash
python bot.py "YOUR_BOT_TOKEN"
```

**Алгоритм:**
1. Отправьте файл
2. Выберите разбиение (минуты, 0 = один файл)
3. Выберите движок (Edge/Silero)
4. Выберите голос

## systemd сервис

```bash
sudo cp tts.service /etc/systemd/system/
sudo nano /etc/systemd/system/tts.service  # измените токен
sudo systemctl enable tts
sudo systemctl start tts
```

## Аргументы CLI

| Аргумент | Описание | По умолчанию |
|---------|----------|--------------|
| `-i`, `--input` | Входной файл | (обязательно) |
| `-o`, `--output` | Папка для сохранения | ~/Desktop |
| `-v`, `--voice` | Голос TTS | ru-RU-SvetlanaNeural |
| `-s`, `--split` | Разделение (минуты) | 0 |
| `-t`, `--tts` | edge/silero | edge |
| `-g`, `--gui` | Запустить GUI | - |

## Голоса

**Edge TTS:** ru-RU-SvetlanaNeural, ru-RU-DmitryNeural, en-US-JennyNeural, UK-RomanNeural

**Silero:** xenia, aidar, aleksandr, alyona, anna, danil, dasha, max, pavel

## Устранение проблем

### Python не найден
```bash
python3 tts_converter.py --gui
```

### Silero ошибки
```bash
pip install torch torchaudio
```

### Создание Telegram бота
1. Откройте @BotFather
2. /newbot
3. Скопируйте токен
4. Запустите: `python bot.py "TOKEN"`

## Лицензия

MIT
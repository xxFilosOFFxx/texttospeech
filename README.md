# Text to Speech Converter

Конвертер текстовых файлов (TXT, PDF, EPUB, FB2) в MP3 аудио с использованием Edge TTS или Silero.

## Возможности

- Поддержка форматов: TXT, PDF, EPUB, FB2
- Два движка TTS: Edge TTS (онлайн) и Silero (офлайн)
- Разделение на главы по N минут
- GUI (PyQt6/tkinter)
- Telegram бот

## Установка

### Быстрый старт

```bash
# Клонирование репозитория
git clone https://github.com/xxFilosOFFxx/texttospeech.git
cd texttospeech

# Запуск скрипта установки
chmod +x install.sh
./install.sh

# Или вручную:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install scipy soundfile
```

### Требования

- Python 3.10+
- ffmpeg (для аудио)
- pydub, soundfile, scipy

## Использование

### GUI режим

```bash
source venv/bin/activate
python tts_converter.py --gui
```

### CLI режим

```bash
source venv/bin/activate
python tts_converter.py -i "book.txt" -o "output/" --voice "ru-RU-SvetlanaNeural"
python tts_converter.py -i "book.txt" -o "output/" --split 30 --voice "ru-RU-SvetlanaNeural"
python tts_converter.py -i "book.txt" -o "output/" --tts silero --voice "xenia"
```

### Аргументы CLI

| Аргумент | Описание | По умолчанию |
|---------|----------|-------------|
| `-i`, `--input` | Входной файл | (обязательно) |
| `-o`, `--output` | Папка для сохранения | ~/Desktop |
| `-v`, `--voice` | Голос TTS | ru-RU-SvetlanaNeural |
| `-s`, `--split` | Разделение (минуты) | 0 |
| `-t`, `--tts` | edge/silero | edge |
| `-g`, `--gui` | Запустить GUI | - |
| `-b`, `--bot` | Токен Telegram бота | - |

### Доступные голоса

**Edge TTS:**
- Русские: ru-RU-SvetlanaNeural, ru-RU-DmitryNeural, ru-RU-ElizabethNeural
- Английские: en-US-JennyNeural, en-US-GuyNeural
- Украинские: UK-RomanNeural, UK-LydiaNeural

**Silero:**
- xenia, aidar, aleksandr, alyona, anna, danil, dasha, emma, iren, max, oksana, pavel

## Устранение проблем

### "command not found: python"

```bash
# Использовать python3
python3 tts_converter.py --gui
```

### Silero ошибки

```bash
# Установить дополнительные пакеты
pip install scipy soundfile torch torchaudio
```

### Права доступа

```bash
chmod +x install.sh
./install.sh --with-system-deps
```

## Лицензия

MIT
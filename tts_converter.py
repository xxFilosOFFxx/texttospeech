#!/usr/bin/env python3
"""
Text to Speech Converter
Конвертирует текстовые файлы (txt, pdf, epub, fb2) в MP3 аудио с использованием Edge TTS.
Поддерживает GUI (PyQt6/tkinter), CLI и Telegram бот.
"""

import os
import sys

# Автоматическая активация виртуального окружения (до импортов)
venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv')
if os.path.exists(venv_path):
    for subdir in ['lib', 'lib64']:
        site_packages = os.path.join(venv_path, subdir, 'python3.14', 'site-packages')
        if os.path.exists(site_packages) and site_packages not in sys.path:
            sys.path.insert(0, site_packages)
            break

import argparse
import tempfile
import shutil
from pathlib import Path
import asyncio
import multiprocessing
import logging

# Количество параллельных процессов (на 1 меньше, чем CPU ядер)
CPU_COUNT = max(1, multiprocessing.cpu_count() - 1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('tts_converter.log', encoding='utf-8')  # Запись в файл
    ]
)
logger = logging.getLogger(__name__)

try:
    import edge_tts  # Microsoft Edge TTS для синтеза речи
except ImportError:
    print("Установите edge-tts: pip install edge-tts")
    sys.exit(1)

try:
    import tkinter as tk  # Встроенный GUI (альтернатива)
    from tkinter import filedialog, messagebox, ttk
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

try:
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                   QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                                   QComboBox, QTextEdit, QProgressBar, QFileDialog,
                                   QGroupBox, QMessageBox, QSpinBox, QSlider)
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    PYQT_AVAILABLE = True  # Основной GUI
except ImportError:
    PYQT_AVAILABLE = False

try:
    from telegram import Update  # Telegram Bot API
    from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

try:
    import PyPDF2  # Чтение PDF файлов
except ImportError:
    PyPDF2 = None

try:
    from ebooklib import epub  # Чтение EPUB файлов
    EPUB_AVAILABLE = True
except ImportError:
    EPUB_AVAILABLE = False

PYDUB_AVAILABLE = False

try:
    from pydub import AudioSegment  # Объединение и обработка аудио
    PYDUB_AVAILABLE = True
except Exception as e:
    PYDUB_AVAILABLE = False

# Silero TTS - локальная языковая модель
SILERO_AVAILABLE = False

try:
    from silero import silero_tts
    SILERO_AVAILABLE = True
except ImportError:
    silero_tts = None

# Глобальная модель Silero (загружается один раз)
_silero_model = None
_silero_example_text = None
_silero_speakers = []


def init_silero_model():
    """
    Инициализирует модель Silero TTS (загружает один раз при первом использовании).
    """
    global _silero_model, _silero_example_text, _silero_speakers
    if _silero_model is not None:
        return _silero_model, _silero_example_text
    
    if not SILERO_AVAILABLE:
        logger.warning("Silero не установлен. Установите: pip install silero")
        return None, None
    
    try:
        logger.info("Загрузка модели Silero TTS...")
        # Загружаем русскую модель v5
        _silero_model, _silero_example_text = silero_tts(language='ru', speaker='v5_ru')
        # Список доступных спикеров для v5_ru
        _silero_speakers = ['aidar', 'aleksandr', 'alyona', 'anna', 'danil', 'dasha', 'deep_s1', 
                         'emma', 'iren', 'max', 'natural_s0', 'natural_s1', 'natural_s2', 
                         'natural_s3', 'oksana', 'pavel', 'seriy', 'tatiana', 'tersky', 
                         'xenia', 'izhulav', 'nataly', 'ruslan_k']
        logger.info(f"Модель Silero загружена. Пример: {_silero_example_text[:50]}...")
        logger.info(f"Доступные спикеры: {_silero_speakers}")
        return _silero_model, _silero_example_text
    except Exception as e:
        logger.error(f"Ошибка загрузки Silero: {e}")
        return None, None


def get_silero_voices():
    """Возвращает список доступных голосов Silero."""
    _, _ = init_silero_model()
    return _silero_speakers if _silero_speakers else []


def convert_text_to_audio_silero(text, output_path, voice="xenia", sample_rate=48000):
    """
    Конвертирует текст в аудио с использованием локальной модели Silero TTS.
    """
    model, example_text = init_silero_model()
    if model is None:
        raise RuntimeError("Silero TTS не доступен. Установите: pip install silero")
    
    # Выбираем голос (по умолчанию xenia)
    if not voice:
        voice = "xenia"
    
    try:
        import torch
        import numpy as np
        import soundfile as sf
        logger.info(f"Синтез речи: voice={voice}, text_len={len(text)}")
        audio = model.apply_tts(text=text, speaker=voice, sample_rate=sample_rate)
        # Конвертируем torch tensor в numpy и сохраняем через soundfile
        audio_np = audio.cpu().numpy().squeeze()
        sf.write(output_path, audio_np, sample_rate)
        logger.info(f"Сохранено в {output_path}")
        return True
    except Exception as e:
        logger.error(f"Ошибка Silero TTS: {e}")
        raise


def convert_all_chunks_silero(chunks, temp_files, voice, progress_callback=None):
    """
    Конвертирует все куски текста последовательно с использованием Silero.
    Silero работает синхронно, поэтому используется последовательная обработка.
    """
    num_chunks = len(chunks)
    logger.info(f"Начало конвертации {num_chunks} частей через Silero...")
    
    for i, (chunk, output_path) in enumerate(zip(chunks, temp_files)):
        logger.info(f"Конвертация части {i + 1}/{num_chunks}")
        try:
            convert_text_to_audio_silero(chunk, output_path, voice)
            logger.info(f"Часть {i + 1}/{num_chunks} успешно конвертирована")
            
            if progress_callback:
                progress = 10 + int(60 * (i + 1) / num_chunks)
                progress_callback(progress)
        except Exception as e:
            logger.error(f"Ошибка конвертации части {i + 1}: {e}")
    
    logger.info("Конвертация Silero завершена")


def extract_text_from_file(filepath):
    """
    Извлекает текст из различных форматов файлов.
    Поддерживает: TXT, PDF, EPUB, FB2.
    """
    ext = Path(filepath).suffix.lower()
    text = ""
    
    if ext == ".txt":
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
            
    elif ext == ".pdf":
        if PyPDF2:
            try:
                with open(filepath, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
            except Exception as e:
                print(f"Ошибка PDF: {e}")
        else:
            print("PyPDF2 не установлен")
            
    elif ext == ".epub":
        if EPUB_AVAILABLE:
            try:
                book = epub.read_epub(filepath)
                for item in book.get_items():
                    if item.get_type() == 9:
                        text += item.get_content().decode("utf-8")
            except Exception as e:
                print(f"Ошибка EPUB: {e}")
        else:
            print("ebooklib не установлен")
            
    elif ext == ".fb2":
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(filepath)
            root = tree.getroot()
            for elem in root.iter():
                if elem.text:
                    text += elem.text + " "
        except Exception as e:
            print(f"Ошибка FB2: {e}")
            
    return text


async def convert_text_to_audio(text, output_path, voice="ru-RU-SvetlanaNeural", rate="+0%"):
    """
    Конвертирует текст в аудио файл (однократная конвертация).
    Использует Microsoft Edge TTS.
    """


def split_audio(input_path, output_dir, prefix, duration_minutes):
    """
    Разделяет аудио файл на части заданной длительности.
    """
    if duration_minutes <= 0:
        return [input_path]
    
    logger.info(f"Разделение файла {input_path} на куски по {duration_minutes} минут...")
    
    is_mp3 = input_path.lower().endswith('.mp3')
    
    try:
        # Пробуем через pydub если работает
        if PYDUB_AVAILABLE and is_mp3:
            try:
                audio = AudioSegment.from_file(input_path)
                duration_sec = len(audio) / 1000
                logger.info(f"Длительность: {duration_sec:.1f} сек ({duration_sec/60:.1f} мин)")
                
                if duration_sec < duration_minutes * 60:
                    logger.info("Файл короче указанной длительности")
                    return [input_path]
                
                chunk_duration_ms = duration_minutes * 60 * 1000
                files = []
                chunk_num = 1
                
                while len(audio) > chunk_duration_ms:
                    chunk = audio[:chunk_duration_ms]
                    output_file = os.path.join(output_dir, f"{prefix}_part{chunk_num}.mp3")
                    logger.info(f"Создание части {chunk_num}: {output_file}")
                    chunk.export(output_file, format="mp3")
                    files.append(output_file)
                    audio = audio[chunk_duration_ms:]
                    chunk_num += 1
                
                if len(audio) > 0:
                    output_file = os.path.join(output_dir, f"{prefix}_part{chunk_num}.mp3")
                    logger.info(f"Создание части {chunk_num}: {output_file}")
                    audio.export(output_file, format="mp3")
                    files.append(output_file)
                
                if files and input_path not in files:
                    try:
                        os.remove(input_path)
                    except:
                        pass
                
                logger.info(f"Разделение завершено, создано {len(files)} файлов")
                return files
            except Exception as e:
                logger.warning(f"pydub не работает: {e}")
        
        # Используем ffmpeg для разделения
        if is_mp3 or input_path.lower().endswith('.wav'):
            import subprocess
            
            # Конвертируем в WAV если нужно
            if is_mp3:
                temp_wav = os.path.join(output_dir, f"{prefix}_temp.wav")
                try:
                    subprocess.run(['ffmpeg', '-y', '-i', input_path, '-acodec', 'pcm_s16le', '-ar', '48000', temp_wav], 
                                  capture_output=True, check=True)
                    input_wav = temp_wav
                except Exception as e:
                    logger.error(f"Конвертация в WAV не удалась: {e}")
                    return [input_path]
            else:
                input_wav = input_path
            
            # Читаем WAV и получаем длительность
            import wave
            with wave.open(input_wav, 'rb') as wav:
                rate = wav.getframerate()
                frames = wav.getnframes()
                duration_sec = frames / rate
            
            logger.info(f"Длительность: {duration_sec:.1f} сек ({duration_sec/60:.1f} мин)")
            
            if duration_sec < duration_minutes * 60:
                logger.info("Файл короче указанной длительности")
                if is_mp3 and 'temp_wav' in dir():
                    try:
                        os.remove(temp_wav)
                    except:
                        pass
                return [input_path]
            
            # Разделяем через ffmpeg
            files = []
            chunk_num = 1
            start_sec = 0
            
            while start_sec < duration_sec:
                end_sec = min(start_sec + duration_minutes * 60, duration_sec)
                output_file = os.path.join(output_dir, f"{prefix}_part{chunk_num}.wav")
                logger.info(f"Создание части {chunk_num}: {output_file}")
                
                try:
                    subprocess.run([
                        'ffmpeg', '-y', '-i', input_wav,
                        '-ss', str(start_sec), '-to', str(end_sec),
                        '-acodec', 'pcm_s16le', '-ar', '48000', output_file
                    ], capture_output=True, check=True)
                    files.append(output_file)
                except Exception as e:
                    logger.error(f"Ошибка создания части {chunk_num}: {e}")
                
                start_sec = end_sec
                chunk_num += 1
            
            # Удаляем временный WAV
            if is_mp3 and 'temp_wav' in dir():
                try:
                    os.remove(temp_wav)
                except:
                    pass
            
            if files and input_path not in files:
                try:
                    os.remove(input_path)
                except:
                    pass
            
            logger.info(f"Разделение завершено, создано {len(files)} файлов")
            return files
        
        # Для других форматов используем soundfile
        import soundfile as sf
        data, sr = sf.read(input_path)
        duration_sec = len(data) / sr
        
        logger.info(f"Длительность: {duration_sec:.1f} сек ({duration_sec/60:.1f} мин)")
        
        if duration_sec < duration_minutes * 60:
            return [input_path]
        
        chunk_samples = int(sr * duration_minutes * 60)
        files = []
        chunk_num = 1
        
        for i in range(0, len(data), chunk_samples):
            chunk = data[i:i + chunk_samples]
            output_file = os.path.join(output_dir, f"{prefix}_part{chunk_num}.wav")
            logger.info(f"Создание части {chunk_num}: {output_file}")
            sf.write(output_file, chunk, sr)
            files.append(output_file)
            chunk_num += 1
        
        if files and input_path not in files:
            try:
                os.remove(input_path)
            except:
                pass
        
        logger.info(f"Разделение завершено, создано {len(files)} файлов")
        return files
    except Exception as e:
        logger.error(f"Ошибка разделения: {e}")
        return [input_path]


def split_text_into_chunks(text, chunk_size=2000, tts_type="edge"):
    """
    Разделяет текст на части для постепенной конвертации.
    Разбиение происходит по предложениям с ограничением размера куска.
    
    Silero ограничен ~500 символами, Edge TTS - ~3000
    """
    # Silero имеет меньший лимит
    if tts_type == "silero":
        chunk_size = min(chunk_size, 500)
    
    chunks = []
    sentences = text.replace("\n", " ").split(". ")
    
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += ". " + sentence if current_chunk else sentence
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [text]


async def convert_chunk_to_audio_async(text, output_path, voice, rate="+0%", retry=5, delay=3):
    """
    Конвертирует один кусок текста в аудио с повторными попытками при ошибках.
    """
    logger.debug(f"Создание edge_tts.Communicate для voice={voice}, rate={rate}")
    
    last_error = None
    for attempt in range(retry):
        try:
            communicate = edge_tts.Communicate(
                text, voice, rate=rate,
                connect_timeout=30,
                receive_timeout=120
            )
            logger.debug(f"Попытка {attempt + 1}/{retry}: сохранение в {output_path}")
            await communicate.save(output_path)
            logger.debug(f"Успешно сохранено в {output_path}")
            return True
        except Exception as e:
            last_error = e
            logger.warning(f"Попытка {attempt + 1}/{retry} неудачна: {e}")
            if attempt < retry - 1:
                wait = delay * (attempt + 1)
                logger.info(f"Ожидание {wait} сек перед повторной попыткой...")
                await asyncio.sleep(wait)
    
    logger.error(f"Не удалось сконвертировать часть после {retry} попыток: {last_error}")
    return False


async def convert_all_chunks_async(chunks, temp_files, voice, progress_callback=None, rate="+0%"):
    """
    Конвертирует все куски текста параллельно с использованием семафора.
    Ограничивает количество параллельных запросов к Edge TTS.
    """
    num_chunks = len(chunks)
    logger.info(f"Начало конвертации {num_chunks} частей с лимитом {CPU_COUNT} параллельных запросов, скорость: {rate}")
    
    async def convert_with_progress(chunk_idx, text, output_path):
        logger.info(f"Начало конвертации части {chunk_idx + 1}/{num_chunks}")
        success = await convert_chunk_to_audio_async(text, output_path, voice, rate)
        if success:
            logger.info(f"Часть {chunk_idx + 1}/{num_chunks} успешно конвертирована -> {output_path}")
            if progress_callback:
                progress = 10 + int(60 * (chunk_idx + 1) / num_chunks)
                progress_callback(progress)
                logger.debug(f"Прогресс: {progress}%")
            return True
        else:
            logger.warning(f"Часть {chunk_idx + 1}/{num_chunks} не сконвертирована, пропускаем")
            return False
    
    semaphore = asyncio.Semaphore(3)
    logger.info(f"Создан семафор с лимитом 3 параллельных запросов")
    
    async def bounded_convert(idx, text, path):
        async with semaphore:
            logger.debug(f"Семафор захвачен для части {idx + 1}")
            result = await convert_with_progress(idx, text, path)
            logger.debug(f"Семафор освобожден после части {idx + 1}")
            return result
    
    tasks = [bounded_convert(i, chunks[i], temp_files[i]) for i in range(num_chunks)]
    logger.info(f"Запущено {len(tasks)} задач, ожидание завершения...")
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success_count = 0
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
        elif r is True:
            success_count += 1
        elif r is False:
            error_count += 1
    
    logger.info(f"Конвертация завершена: успешно {success_count}, ошибок {error_count}")


def process_file(input_path, output_dir, voice, split_duration, silent=False, progress_callback=None, rate="+0%", tts_type="edge"):
    """
    Основная функция обработки файла.
    Извлекает текст, конвертирует в MP3 и при необходимости разделяет на части.
    
    Параметры:
        tts_type: тип TTS движка ("edge" - Edge TTS, "silero" - локальная модель Silero)
    """
    # Создаем выходную директорию если не существует
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"=== НАЧАЛО ОБРАБОТКИ ФАЙЛА ===")
    logger.info(f"Входной файл: {input_path}")
    logger.info(f"Выходная папка: {output_dir}")
    logger.info(f"Голос: {voice}")
    logger.info(f"Скорость: {rate}")
    logger.info(f"Разделение: {split_duration} минут")
    
    logger.info("Извлечение текста из файла...")
    text = extract_text_from_file(input_path)
    logger.info(f"Извлечено символов: {len(text)}")
    
    if not text.strip():
        text = "Не удалось извлечь текста из файла."
        logger.warning("Текст пустой!")
    
    filename = Path(input_path).stem
    logger.info(f"Имя файла (без расширения): {filename}")
    
    if progress_callback:
        progress_callback(5)
        logger.debug("Прогресс: 5% (текст извлечен)")
    
    logger.info("Разделение текста на куски...")
    chunks = split_text_into_chunks(text, tts_type=tts_type)
    num_chunks = len(chunks)
    logger.info(f"Текст разделен на {num_chunks} кусков")
    
    logger.info(f"Создание временных файлов в {tempfile.gettempdir()}...")
    # Используем .wav для Silero (лучше совместимость)
    ext = ".wav" if tts_type == "silero" else ".mp3"
    temp_files = [os.path.join(tempfile.gettempdir(), f"{filename}_part{i}{ext}") for i in range(num_chunks)]
    logger.info(f"Создано {len(temp_files)} временных файлов")
    
    if tts_type == "silero":
        logger.info("=== НАЧАЛО КОНВЕРТАЦИИ SILERO ===")
        convert_all_chunks_silero(chunks, temp_files, voice, progress_callback)
    else:
        logger.info("=== НАЧАЛО АСИНХРОННОЙ КОНВЕРТАЦИИ ===")
        asyncio.run(convert_all_chunks_async(chunks, temp_files, voice, progress_callback, rate))
    
    logger.info("=== КОНВЕРТАЦИЯ ЗАВЕРШЕНА ===")
    logger.info("Проверка существования временных файлов...")
    for i, f in enumerate(temp_files):
        exists = os.path.exists(f)
        size = os.path.getsize(f) if exists else 0
        logger.debug(f"Файл {i}: {f} - существует: {exists}, размер: {size}")
    
    existing_files = [f for f in temp_files if os.path.exists(f)]
    logger.info(f"Существует файлов: {len(existing_files)}/{len(temp_files)}")
    
    if not existing_files:
        logger.error("НИ ОДНОГО ВРЕМЕННОГО ФАЙЛА НЕ СОЗДАНО!")
        raise Exception("Конвертация не создала ни одного файла")
    
    logger.info(f"Подготовка к финальной обработке ({len(existing_files)} файлов)...")
    logger.info(f"split_duration={split_duration} минут")
    
    # Всегда объединяем куски в один файл
    logger.info("=== ОБЪЕДИНЕНИЕ В ОДИН ФАЙЛ ===")
    
    if len(existing_files) > 1:
        if PYDUB_AVAILABLE:
            try:
                logger.info("Объединение через pydub...")
                combined = AudioSegment.from_file(existing_files[0])
                logger.info(f"Первый файл: {len(combined)/1000:.1f} сек")
                for i, f in enumerate(existing_files[1:], 1):
                    logger.info(f"Добавляю файл {i + 1}/{len(existing_files)}...")
                    combined += AudioSegment.from_file(f)
                logger.info(f"Общая длительность: {len(combined)/1000:.1f} сек")
                combined_file = os.path.join(tempfile.gettempdir(), f"{filename}_combined.mp3")
                combined.export(combined_file, format="mp3")
                combined_path = combined_file
            except Exception as e:
                logger.error(f"Ошибка pydub: {e}, пробую soundfile...")
                import soundfile as sf
                import numpy as np
                audios = []
                for f in existing_files:
                    audio_data, sr = sf.read(f)
                    audios.append(audio_data)
                combined_audio = np.concatenate(audios)
                combined_file = os.path.join(tempfile.gettempdir(), f"{filename}_combined.wav")
                sf.write(combined_file, combined_audio, 48000)
                combined_path = combined_file
        else:
            # Бинарное объединение - только для MP3
            is_mp3 = existing_files[0].lower().endswith('.mp3')
            if is_mp3:
                logger.info("Бинарное объединение MP3...")
                combined_file = os.path.join(tempfile.gettempdir(), f"{filename}_combined.mp3")
                with open(combined_file, "wb") as out:
                    for f in existing_files:
                        with open(f, "rb") as inp:
                            out.write(inp.read())
                combined_path = combined_file
            else:
                # Для WAV используем soundfile
                import soundfile as sf
                import numpy as np
                logger.info("Объединение WAV через soundfile...")
                audios = []
                for f in existing_files:
                    audio_data, sr = sf.read(f)
                    audios.append(audio_data)
                combined_audio = np.concatenate(audios)
                combined_file = os.path.join(tempfile.gettempdir(), f"{filename}_combined.wav")
                sf.write(combined_file, combined_audio, 48000)
                combined_path = combined_file
    elif len(existing_files) == 1:
        combined_path = existing_files[0]
    else:
        logger.error("Нет файлов для объединения!")
        raise Exception("Нет файлов для объединения")
    
    # Теперь разбиваем на куски если нужно
    if split_duration > 0:
        logger.info("=== РАЗДЕЛЕНИЕ НА КУСКИ ===")
        
        try:
            # Проверяем длительность через pydub (поддерживает MP3)
            if PYDUB_AVAILABLE:
                audio = AudioSegment.from_file(combined_path)
                duration_sec = len(audio) / 1000
            else:
                import soundfile as sf
                data, sr = sf.read(combined_path)
                duration_sec = len(data) / sr
            
            logger.info(f"Длительность: {duration_sec:.1f} сек ({duration_sec/60:.1f} мин)")
            
            max_duration_sec = split_duration * 60
            if duration_sec > max_duration_sec:
                logger.info(f"Разбиваем на куски по {split_duration} минут...")
                result_files = split_audio(combined_path, output_dir, filename, split_duration)
            else:
                # Файл короче - конвертируем в MP3 если WAV
                final_name = os.path.join(output_dir, f"{filename}.mp3")
                if combined_path.lower().endswith('.wav'):
                    if PYDUB_AVAILABLE:
                        audio = AudioSegment.from_wav(combined_path)
                        audio.export(final_name, format="mp3")
                        os.remove(combined_path)
                    else:
                        import soundfile as sf
                        data, sr = sf.read(combined_path)
                        sf.write(final_name.replace('.mp3', '.wav'), data, sr)
                        if PYDUB_AVAILABLE:
                            audio = AudioSegment.from_wav(final_name.replace('.mp3', '.wav'))
                            audio.export(final_name, format="mp3")
                        else:
                            shutil.move(combined_path, final_name)
                else:
                    shutil.move(combined_path, final_name)
                result_files = [final_name]
        except Exception as e:
            logger.error(f"Ошибка разбиения: {e}, перемещаем как есть")
            final_name = os.path.join(output_dir, f"{filename}.mp3")
            try:
                shutil.move(combined_path, final_name)
            except:
                pass
            result_files = [final_name] if os.path.exists(final_name) else []
    else:
        # split_duration == 0 - просто перемещаем
        final_name = os.path.join(output_dir, f"{filename}.mp3")
        if combined_path.lower().endswith('.mp3'):
            shutil.move(combined_path, final_name)
            result_files = [final_name]
        else:
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(combined_path)
                audio.export(final_name, format="mp3")
                os.remove(combined_path)
                result_files = [final_name]
            except:
                shutil.move(combined_path, final_name)
                result_files = [final_name]
    
    # Удаляем временные файлы после завершения
    for f in existing_files:
        if f != combined_path:
            try:
                os.remove(f)
            except:
                pass
    
    if not silent:
        for f in result_files:
            print(f"Сохранено: {f}")
    
    if progress_callback:
        progress_callback(100)
        logger.info("Прогресс: 100% завершено")
    
    return result_files


def run_telegram_bot(token, output_dir, default_voice="ru-RU-SvetlanaNeural", default_split=0):
    """
    Запускает Telegram бота для обработки файлов.
    Интерактивный режим: проверка расширения -> выбор разбиения -> выбор голоса -> конвертация.
    """
    if not TELEGRAM_AVAILABLE:
        print("python-telegram-bot не установлен")
        return
    
    SUPPORTED_EXTENSIONS = ['txt', 'pdf', 'epub', 'fb2']
    EDGE_VOICES = [
        "ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural", "ru-RU-ElizabethNeural",
        "en-US-JennyNeural", "en-US-GuyNeural", "UK-RomanNeural", "UK-LydiaNeural"
    ]
    SILERO_VOICES = ["xenia", "aidar", "aleksandr", "alyona", "anna", "danil", "dasha", "max", "pavel"]
    
    user_sessions = {}
    
    class UserSession:
        """Сессия пользователя для пошагового ввода параметров."""
        def __init__(self, user_id):
            self.user_id = user_id
            self.file_path = None
            self.file_name = None
            self.split_duration = 0
            self.tts_type = "edge"
            self.voice = "ru-RU-SvetlanaNeural"
            self.waiting_for = None
    
    def get_session(user_id):
        if user_id not in user_sessions:
            user_sessions[user_id] = UserSession(user_id)
        return user_sessions[user_id]
    
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎙 <b>Text to Speech Converter</b>\n\n"
            "Отправьте мне текстовый файл (TXT, PDF, EPUB, FB2) - я конвертирую его в MP3 аудио.\n\n"
            "После отправки файла я задам несколько вопросов о параметрах конвертации.",
            parse_mode="HTML"
        )
    
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await start_command(update, context)
    
    async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка загруженного документа."""
        user_id = update.effective_user.id
        session = get_session(user_id)
        
        try:
            file = await update.message.document.get_file()
            ext = update.message.document.file_name.split('.')[-1].lower()
            file_name = update.message.document.file_name
            
            # Проверка расширения
            if ext not in SUPPORTED_EXTENSIONS:
                await update.message.reply_text(
                    f"❌ <b>Неверный формат файла!</b>\n\n"
                    f"Поддерживаемые форматы: <code>{', '.join(SUPPORTED_EXTENSIONS)}</code>\n\n"
                    f"Вы отправили: <code>.{ext}</code>",
                    parse_mode="HTML"
                )
                return
            
            # Скачиваем файл во временную директорию
            session.file_name = file_name
            temp_dir = tempfile.mkdtemp()
            session.file_path = os.path.join(temp_dir, file_name)
            await file.download_to_drive(session.file_path)
            
            # Подтверждение получения
            await update.message.reply_text(
                f"✅ <b>Файл получен!</b>\n\n"
                f"📄 <code>{file_name}</code>\n\n"
                f"Теперь выберите параметры конвертации.\n\n"
                f"<b>Шаг 1 из 3</b>\n"
                f"На сколько минут разбить аудио файл?\n"
                f"Отправьте число (например: <code>30</code>)\n"
                f"Если <code>0</code> - весь текст в одном файле.",
                parse_mode="HTML"
            )
            session.waiting_for = "split"
            
        except Exception as e:
            logger.error(f"Ошибка при обработке документа: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            # Очищаем сессию
            if session.file_path and os.path.exists(os.path.dirname(session.file_path)):
                try:
                    shutil.rmtree(os.path.dirname(session.file_path))
                except:
                    pass
            session.file_path = None
    
    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений (выбор параметров)."""
        user_id = update.effective_user.id
        session = get_session(user_id)
        text = update.message.text.strip()
        
        # Если не в процессе настройки - игнорируем
        if not session.waiting_for or not session.file_path:
            await update.message.reply_text(
                "Отправьте файл для конвертации или /start для начала."
            )
            return
        
        try:
            # Шаг 1: Разбиение на части
            if session.waiting_for == "split":
                try:
                    split_val = int(text)
                    if split_val < 0:
                        await update.message.reply_text("❌ Число должно быть положительным. Попробуйте again:")
                        return
                    session.split_duration = split_val
                except ValueError:
                    await update.message.reply_text("❌ Введите число. Например: 30")
                    return
                
                # Шаг 2: Выбор движка
                split_text = "одним файлом" if split_val == 0 else f"по {split_val} минут"
                await update.message.reply_text(
                    f"✅ Разбиение: <b>{split_text}</b>\n\n"
                    f"<b>Шаг 2 из 3</b>\n"
                    f"Выберите движок TTS:\n"
                    f"<code>1</code> - Edge TTS (онлайн, много голосов)\n"
                    f"<code>2</code> - Silero (офлайн, российские голоса)\n\n"
                    f"Отправьте <code>1</code> или <code>2</code>",
                    parse_mode="HTML"
                )
                session.waiting_for = "engine"
            
            # Шаг 2: Выбор движка
            elif session.waiting_for == "engine":
                if text == "1":
                    session.tts_type = "edge"
                    voices = EDGE_VOICES
                elif text == "2":
                    if not SILERO_AVAILABLE:
                        await update.message.reply_text(
                            "❌ Silero не установлен. Использую Edge TTS.\n"
                        )
                        session.tts_type = "edge"
                        voices = EDGE_VOICES
                    else:
                        session.tts_type = "silero"
                        voices = SILERO_VOICES
                else:
                    await update.message.reply_text("Введите 1 или 2")
                    return
                
                # Шаг 3: Выбор голоса
                voice_list = "\n".join([f"<code>{v}</code>" for v in voices])
                engine_name = "Edge TTS" if session.tts_type == "edge" else "Silero"
                await update.message.reply_text(
                    f"✅ Движок: <b>{engine_name}</b>\n\n"
                    f"<b>Шаг 3 из 3</b>\n"
                    f"Выберите голос (отправьте название):\n\n"
                    f"{voice_list}",
                    parse_mode="HTML"
                )
                session.waiting_for = "voice"
            
            # Шаг 3: Выбор голоса и запуск конвертации
            elif session.waiting_for == "voice":
                session.voice = text
                
                # Начинаем конвертацию
                await update.message.reply_text(
                    f"✅ Голос: <b>{text}</b>\n\n"
                    f"🚀 <b>Начинаю конвертацию...</b>",
                    parse_mode="HTML"
                )
                
                # Конвертация
                session.waiting_for = None
                await process_and_send(update, session)
                
        except Exception as e:
            logger.error(f"Ошибка в handle_text: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            session.waiting_for = None
    
    async def process_and_send(update: Update, session):
        """Конвертация и отправка файлов пользователю."""
        user_id = update.effective_user.id
        
        try:
            # Извлечение текста
            await update.message.reply_text("📖 Извлекаю текст из файла...")
            text = extract_text_from_file(session.file_path)
            if not text.strip():
                await update.message.reply_text("❌ Не удалось извлечь текст из файла.")
                return
            
            text_len = len(text)
            logger.info(f"Извлечено {text_len} символов")
            
            # Разбиение текста на куски
            await update.message.reply_text("✂️ Разбиваю текст на части...")
            chunks = split_text_into_chunks(text, tts_type=session.tts_type)
            num_chunks = len(chunks)
            logger.info(f"Текст разделен на {num_chunks} кусков")
            
            # Создание временных файлов
            temp_dir = os.path.dirname(session.file_path)
            ext = ".wav" if session.tts_type == "silero" else ".mp3"
            temp_files = [os.path.join(temp_dir, f"part{i}{ext}") for i in range(num_chunks)]
            
            # Конвертация
            rate = "+0%"
            progress_msg = await update.message.reply_text(
                f"🎙 Конвертирую текст в аудио...\n"
                f"0/{num_chunks} частей",
                parse_mode="HTML"
            )
            
            if session.tts_type == "silero":
                convert_all_chunks_silero(chunks, temp_files, session.voice)
            else:
                # Edge TTS - асинхронная конвертация с callback для обновления
                last_update = 0
                async def progress_callback(p):
                    nonlocal last_update
                    current = int(p * num_chunks / 100)
                    if current > last_update and current % 10 == 0:
                        last_update = current
                        try:
                            await progress_msg.edit_text(
                                f"🎙 Конвертирую текст в аудио...\n"
                                f"{current}/{num_chunks} частей",
                                parse_mode="HTML"
                            )
                        except:
                            pass
                
                await convert_all_chunks_async(chunks, temp_files, session.voice, progress_callback, rate)
            
            await progress_msg.edit_text(
                f"✅ Конвертация завершена!\n"
                f"Обработано {num_chunks} частей",
                parse_mode="HTML"
            )
            
            # Объединение файлов
            await update.message.reply_text("🔗 Объединяю аудио файлы...")
            existing_files = [f for f in temp_files if os.path.exists(f)]
            
            if not existing_files:
                await update.message.reply_text("❌ Ошибка: не создано ни одного аудио файла.")
                return
            
            # Объединение через soundfile
            import soundfile as sf
            import numpy as np
            audios = []
            for f in existing_files:
                audio_data, sr = sf.read(f)
                audios.append(audio_data)
            combined_audio = np.concatenate(audios)
            
            # Определяем длительность
            duration_sec = len(combined_audio) / 48000
            await update.message.reply_text(
                f"📊 Общая длительность: {duration_sec/60:.1f} минут",
                parse_mode="HTML"
            )
            
            # Разбиение на куски если нужно
            max_duration_sec = session.split_duration * 60
            final_files = []
            
            if session.split_duration > 0 and duration_sec > max_duration_sec:
                await update.message.reply_text(f"✂️ Разбиваю на куски по {session.split_duration} минут...")
                
                # Сохраняем объединенный файл
                combined_path = os.path.join(temp_dir, "combined.wav")
                sf.write(combined_path, combined_audio, 48000)
                
                # Разбиваем через pydub
                if PYDUB_AVAILABLE:
                    audio = AudioSegment.from_wav(combined_path)
                    duration_ms = session.split_duration * 60 * 1000
                    
                    for i in range(0, len(audio), duration_ms):
                        chunk = audio[i:i+duration_ms]
                        part_file = os.path.join(temp_dir, f"output_part{len(final_files)+1}.mp3")
                        chunk.export(part_file, format="mp3")
                        final_files.append(part_file)
                else:
                    # Без pydub - просто отправляем как есть
                    final_path = os.path.join(temp_dir, "output.mp3")
                    sf.write(final_path.replace('.mp3', '.wav'), combined_audio, 48000)
                    final_files.append(final_path)
            else:
                # Один файл
                final_path = os.path.join(temp_dir, "output.mp3")
                sf.write(final_path.replace('.mp3', '.wav'), combined_audio, 48000)
                if PYDUB_AVAILABLE:
                    audio = AudioSegment.from_wav(final_path.replace('.mp3', '.wav'))
                    audio.export(final_path, format="mp3")
                final_files.append(final_path)
            
            # Отправка файлов
            await update.message.reply_text(
                f"📤 Отправляю аудио файлы ({len(final_files)} шт)...",
                parse_mode="HTML"
            )
            
            for i, f in enumerate(final_files):
                try:
                    with open(f, "rb") as file:
                        await update.message.reply_audio(file)
                    logger.info(f"Отправлен файл {i+1}/{len(final_files)}")
                except Exception as e:
                    logger.error(f"Ошибка отправки файла {f}: {e}")
            
            await update.message.reply_text(
                "✅ <b>Конвертация завершена!</b>\n\n"
                "Можете отправить новый файл для конвертации.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка конвертации: {e}")
            await update.message.reply_text(f"❌ Ошибка конвертации: {str(e)}")
        
        finally:
            # Очистка временных файлов
            if session.file_path and os.path.exists(os.path.dirname(session.file_path)):
                try:
                    shutil.rmtree(os.path.dirname(session.file_path))
                    logger.info(f"Временные файлы удалены")
                except Exception as e:
                    logger.error(f"Ошибка удаления временных файлов: {e}")
            # Очищаем сессию
            user_sessions[user_id] = UserSession(user_id)
    
    # Для работы в не-main потоке используем run_until_complete
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Telegram бот запущен. Нажмите Ctrl+C для остановки.")
    
    try:
        loop.run_until_complete(application.run_polling())
    except KeyboardInterrupt:
        print("Бот остановлен")
    finally:
        loop.close()


def cli_mode(args):
    """
    Режим командной строки.
    Обрабатывает аргументы CLI и запускает конвертацию или бота.
    """
    if not args.input:
        print("Используйте: python tts_converter.py --input file.txt --output dir")
        print("Или: python tts_converter.py --bot TOKEN")
        sys.exit(1)
    
    tts_type = getattr(args, 'tts', 'edge')
    
    if args.bot:
        run_telegram_bot(args.bot, args.output or ".", args.voice, args.split)
    else:
        output_dir = args.output or os.path.expanduser("~/Desktop")
        result = process_file(args.input, output_dir, args.voice, args.split, tts_type=tts_type)
        print(f"Создано файлов: {len(result)}")


def gui_mode():
    """
    Запускает GUI в зависимости от доступных библиотек.
    Приоритет: PyQt6 -> tkinter
    """
    if PYQT_AVAILABLE:
        pyqt_gui_mode()
    elif GUI_AVAILABLE:
        tkinter_gui_mode()
    else:
        print("GUI недоступен. Установите PyQt6 или python3-tk")
        sys.exit(1)


def pyqt_gui_mode():
    """
    GUI на PyQt6.
    Предоставляет графический интерфейс с выбором файла, голоса, скорости и разделения.
    """
    class ConversionThread(QThread):
        """
        Поток для выполнения конвертации без блокировки GUI.
        """
        progress = pyqtSignal(int)  # Сигнал прогресса
        log_message = pyqtSignal(str)  # Сигнал лога
        finished = pyqtSignal(list)  # Сигнал завершения
        error = pyqtSignal(str)  # Сигнал ошибки
        
        def __init__(self, input_file, output_dir, voice, split_duration, speed, tts_type="edge"):
            super().__init__()
            self.input_file = input_file
            self.output_dir = output_dir
            self.voice = voice
            self.split_duration = split_duration
            self.speed = speed  # Скорость речи (50-200%)
            self.tts_type = tts_type  # Тип TTS: "edge" или "silero"
        
        def run(self):
            """Запуск конвертации в отдельном потоке."""
            try:
                def progress_callback(p):
                    self.progress.emit(p)
                
                # Конвертация скорости в формат Edge TTS
                rate = f"+{self.speed - 100}%" if self.speed >= 100 else f"{self.speed - 100}%"
                
                result = process_file(
                    self.input_file,
                    self.output_dir,
                    self.voice,
                    self.split_duration,
                    silent=False,
                    progress_callback=progress_callback,
                    rate=rate,
                    tts_type=self.tts_type
                )
                self.finished.emit(result)
            except Exception as e:
                self.error.emit(str(e))

    class TextToSpeechApp(QMainWindow):
        """
        Главное окно приложения с PyQt6.
        """
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Text to Speech Converter")
            self.setGeometry(100, 100, 700, 600)
            self.is_converting = False  # Флаг конвертации
            self.conversion_thread = None  # Поток конвертации
            self.bot_running = False  # Флаг работы бота
            self.bot_process = None  # Процесс бота (QProcess)
            
            # Доступные голоса Edge TTS
            voices = [
                "ru-RU-SvetlanaNeural",
                "ru-RU-DmitryNeural", 
                "ru-RU-ElizabethNeural",
                "en-US-JennyNeural",
                "en-US-GuyNeural",
                "UK-RomanNeural",
                "UK-LydiaNeural"
            ]
            
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            layout = QVBoxLayout(central_widget)
            
            title = QLabel("Text to Speech Converter")
            title.setStyleSheet("font-size: 18px; font-weight: bold;")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)
            
            file_group = QGroupBox("Файл")
            file_layout = QHBoxLayout(file_group)
            self.input_file = QLineEdit()
            self.input_file.setPlaceholderText("Выберите файл...")
            file_layout.addWidget(self.input_file)
            btn_open = QPushButton("Открыть")
            btn_open.clicked.connect(self.open_file)
            file_layout.addWidget(btn_open)
            layout.addWidget(file_group)
            
            output_group = QGroupBox("Папка для сохранения")
            output_layout = QHBoxLayout(output_group)
            self.output_dir = QLineEdit(os.path.expanduser("~/Desktop"))
            output_layout.addWidget(self.output_dir)
            btn_output = QPushButton("Выбрать")
            btn_output.clicked.connect(self.select_output_dir)
            output_layout.addWidget(btn_output)
            layout.addWidget(output_group)
            
            voice_group = QGroupBox("Голос")
            voice_layout = QHBoxLayout(voice_group)
            
            # Выбор типа TTS
            tts_layout = QHBoxLayout()
            tts_layout.addWidget(QLabel("Движок:"))
            self.tts_type_combo = QComboBox()
            self.tts_type_combo.addItems(["Edge TTS", "Silero TTS"])
            self.tts_type_combo.currentTextChanged.connect(self.on_tts_type_changed)
            tts_layout.addWidget(self.tts_type_combo)
            voice_layout.addLayout(tts_layout)
            
            self.voice_combo = QComboBox()
            self.voice_combo.addItems(voices)
            voice_layout.addWidget(self.voice_combo)
            
            self.btn_load_silero = QPushButton("Загрузить Silero")
            self.btn_load_silero.setToolTip("Загрузить голоса Silero")
            self.btn_load_silero.clicked.connect(self.load_silero_voices)
            self.btn_load_silero.setVisible(False)
            voice_layout.addWidget(self.btn_load_silero)
            
            self.speed_label = QLabel("Скорость: 1.0x")
            voice_layout.addWidget(self.speed_label)
            
            self.speed_slider = QSlider(Qt.Orientation.Horizontal)
            self.speed_slider.setRange(50, 200)
            self.speed_slider.setValue(100)
            self.speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            self.speed_slider.setTickInterval(25)
            self.speed_slider.valueChanged.connect(self.on_speed_changed)
            voice_layout.addWidget(self.speed_slider)
            
            self.btn_preview = QPushButton("🔊")
            self.btn_preview.setToolTip("Предпрослушивание")
            self.btn_preview.setFixedWidth(40)
            self.btn_preview.clicked.connect(self.preview_voice)
            voice_layout.addWidget(self.btn_preview)
            
            layout.addWidget(voice_group)
            
            split_group = QGroupBox("Разделение файла (минуты)")
            split_layout = QHBoxLayout(split_group)
            self.split_duration = QSpinBox()
            self.split_duration.setRange(0, 180)
            self.split_duration.setValue(0)
            split_layout.addWidget(self.split_duration)
            label = QLabel("0 = не делить")
            split_layout.addWidget(label)
            split_layout.addStretch()
            layout.addWidget(split_group)
            
            self.btn_convert = QPushButton("Конвертировать в MP3")
            self.btn_convert.clicked.connect(self.start_conversion)
            layout.addWidget(self.btn_convert)
            
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            layout.addWidget(self.progress_bar)
            
            log_group = QGroupBox("Лог")
            log_layout = QVBoxLayout(log_group)
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            log_layout.addWidget(self.log_text)
            layout.addWidget(log_group)
            
            if TELEGRAM_AVAILABLE:
                bot_group = QGroupBox("Telegram бот")
                bot_layout = QHBoxLayout(bot_group)
                label = QLabel("Токен бота:")
                bot_layout.addWidget(label)
                self.telegram_token = QLineEdit()
                self.telegram_token.setPlaceholderText("Введите токен...")
                bot_layout.addWidget(self.telegram_token)
                self.btn_bot = QPushButton("Запустить")
                self.btn_bot.clicked.connect(self.start_telegram_bot)
                bot_layout.addWidget(self.btn_bot)
                layout.addWidget(bot_group)
            
            layout.addStretch()
        
        def log(self, message):
            self.log_text.append(message)
        
        def open_file(self):
            filename, _ = QFileDialog.getOpenFileName(
                self, "Выбрать файл", "",
                "Все поддерживаемые (*.txt *.pdf *.epub *.fb2);;"
                "Текстовые (*.txt);;PDF (*.pdf);;EPUB (*.epub);;FB2 (*.fb2)"
            )
            if filename:
                self.input_file.setText(filename)
                self.log(f"Выбран файл: {filename}")
        
        def on_speed_changed(self, value):
            speed = value / 100.0
            self.speed_label.setText(f"Скорость: {speed:.1f}x")
        
        def on_tts_type_changed(self, text):
            """Переключение между Edge TTS и Silero."""
            is_silero = "Silero" in text
            
            # Показываем/скрываем кнопку загрузки Silero
            self.btn_load_silero.setVisible(is_silero and SILERO_AVAILABLE)
            
            if is_silero and not SILERO_AVAILABLE:
                self.log("ВНИМАНИЕ: Silero не установлен! pip install silero")
            
            # Обновляем список голосов
            if is_silero and SILERO_AVAILABLE:
                try:
                    voices = get_silero_voices()
                    self.voice_combo.clear()
                    self.voice_combo.addItems(voices if voices else ["xenia", "aidar", "aleksandr"])
                except Exception as e:
                    self.log(f"Ошибка загрузки голосов Silero: {e}")
            else:
                edge_voices = [
                    "ru-RU-SvetlanaNeural",
                    "ru-RU-DmitryNeural", 
                    "ru-RU-ElizabethNeural",
                    "en-US-JennyNeural",
                    "en-US-GuyNeural",
                    "UK-RomanNeural",
                    "UK-LydiaNeural"
                ]
                self.voice_combo.clear()
                self.voice_combo.addItems(edge_voices)
        
        def load_silero_voices(self):
            """Загружает голоса Silero."""
            self.log("Загрузка модели Silero...")
            try:
                voices = get_silero_voices()
                self.voice_combo.clear()
                self.voice_combo.addItems(voices if voices else ["xenia", "aidar", "aleksandr"])
                self.log(f"Загружено голосов: {len(voices)}")
            except Exception as e:
                self.log(f"Ошибка: {e}")
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить Silero: {e}")
        
        def get_current_tts_type(self):
            """Возвращает тип TTS: 'edge' или 'silero'."""
            return "silero" if "Silero" in self.tts_type_combo.currentText() else "edge"
        
        def preview_voice(self):
            input_path = self.input_file.text()
            if not input_path:
                QMessageBox.warning(self, "Ошибка", "Выберите файл для предпрослушивания!")
                return
            
            self.log("Создание превью...")
            speed = self.speed_slider.value()
            rate = f"+{speed - 100}%" if speed >= 100 else f"{speed - 100}%"
            
            try:
                text = extract_text_from_file(input_path)
                preview_text = text[:200] if len(text) > 200 else text
                if not preview_text:
                    preview_text = "Привет"
                
                preview_file = os.path.join(tempfile.gettempdir(), "preview.mp3")
                
                if self.get_current_tts_type() == "silero":
                    convert_text_to_audio_silero(preview_text, preview_file, self.voice_combo.currentText())
                else:
                    async def do_preview():
                        await convert_chunk_to_audio_async(preview_text, preview_file, self.voice_combo.currentText(), rate)
                    
                    asyncio.run(do_preview())
                
                if os.path.exists(preview_file):
                    import subprocess
                    if sys.platform == "linux":
                        subprocess.run(["xdg-open", preview_file])
                    elif sys.platform == "darwin":
                        subprocess.run(["open", preview_file])
                    else:
                        subprocess.run(["start", "", preview_file], shell=True)
                    self.log(f"Превью воспроизводится (скорость {speed/100:.1f}x)")
                else:
                    self.log("Ошибка создания превью")
            except Exception as e:
                self.log(f"Ошибка превью: {e}")
                QMessageBox.critical(self, "Ошибка", str(e))
        
        def select_output_dir(self):
            dirname = QFileDialog.getExistingDirectory(self, "Выбрать папку", self.output_dir.text())
            if dirname:
                self.output_dir.setText(dirname)
                self.log(f"Папка сохранения: {dirname}")
        
        def start_conversion(self):
            input_path = self.input_file.text()
            if not input_path:
                QMessageBox.warning(self, "Ошибка", "Выберите файл!")
                return
            
            if self.is_converting:
                return
            
            self.is_converting = True
            self.btn_convert.setEnabled(False)
            self.progress_bar.setValue(0)
            
            tts_type = self.get_current_tts_type()
            
            self.conversion_thread = ConversionThread(
                input_path,
                self.output_dir.text(),
                self.voice_combo.currentText(),
                self.split_duration.value(),
                self.speed_slider.value(),
                tts_type
            )
            self.conversion_thread.progress.connect(self.on_progress)
            self.conversion_thread.log_message.connect(self.log)
            self.conversion_thread.finished.connect(self.on_finished)
            self.conversion_thread.error.connect(self.on_error)
            self.conversion_thread.start()
            self.log(f"Начало конвертации... (движок: {tts_type})")
        
        def on_progress(self, value):
            self.progress_bar.setValue(value)
        
        def on_finished(self, result):
            self.is_converting = False
            self.btn_convert.setEnabled(True)
            self.progress_bar.setValue(100)
            self.log(f"Готово! Создано файлов: {len(result)}")
            QMessageBox.information(self, "Успех", f"Конвертация завершена!\nСоздано файлов: {len(result)}")
        
        def on_error(self, error_msg):
            self.is_converting = False
            self.btn_convert.setEnabled(True)
            self.log(f"Ошибка: {error_msg}")
            QMessageBox.critical(self, "Ошибка", error_msg)
        
        def start_telegram_bot(self):
            token = self.telegram_token.text()
            if not token:
                QMessageBox.warning(self, "Ошибка", "Введите токен бота")
                return
            
            if self.bot_running:
                self.log("Остановка Telegram бота...")
                self.bot_process.kill()
                self.bot_process = None
                self.bot_running = False
                self.btn_bot.setText("Запустить")
                self.log("Бот остановлен")
                return
            
            self.log("Запуск Telegram бота...")
            
            venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'bin', 'python')
            bot_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py')
            
            from PyQt6.QtCore import QProcess
            self.bot_process = QProcess()
            self.bot_process.setProgram(venv_python)
            self.bot_process.setArguments([bot_script, token])
            self.bot_process.setWorkingDirectory(os.path.dirname(os.path.abspath(__file__)))
            
            self.bot_process.readyReadStandardOutput.connect(self._read_bot_output)
            self.bot_process.readyReadStandardError.connect(self._read_bot_error)
            self.bot_process.finished.connect(self._bot_finished)
            self.bot_process.started.connect(self._bot_started)
            self.bot_process.errorOccurred.connect(self._bot_error)
            
            self.bot_process.start()
        
        def _bot_started(self):
            self.bot_running = True
            self.btn_bot.setText("Остановить")
            self.log("Бот запущен!")
        
        def _bot_error(self, error):
            self.log(f"Ошибка процесса: {error}")
            self.bot_running = False
            self.btn_bot.setText("Запустить")
        
        def _read_bot_output(self):
            try:
                output = self.bot_process.readAllStandardOutput().data().decode('utf-8', errors='replace')
                for line in output.splitlines():
                    self.log(line)
            except:
                pass
        
        def _read_bot_error(self):
            try:
                output = self.bot_process.readAllStandardError().data().decode('utf-8', errors='replace')
                for line in output.splitlines():
                    self.log(f"[ERR] {line}")
            except:
                pass
        
        def _bot_finished(self, exit_code, exit_status):
            self.bot_running = False
            self.btn_bot.setText("Запустить")
            self.log(f"Бот остановлен (код {exit_code})")

    app = QApplication(sys.argv)
    window = TextToSpeechApp()
    window.show()
    app.exec()


def tkinter_gui_mode():
    """
    GUI на tkinter (альтернативный интерфейс).
    Используется, если PyQt6 недоступен.
    """
    class TextToSpeechApp:
        """
        Главное окно приложения с tkinter.
        """
        def __init__(self, root):
            self.root = root
            self.root.title("Text to Speech Converter")
            self.root.geometry("700x600")
            
            self.input_file = tk.StringVar()
            self.output_dir = tk.StringVar(value=os.path.expanduser("~/Desktop"))
            self.voice = tk.StringVar(value="ru-RU-SvetlanaNeural")
            self.split_duration = tk.IntVar(value=0)
            self.progress = tk.StringVar(value="")
            self.is_converting = False
            
            self.setup_ui()
            
        def setup_ui(self):
            main_frame = ttk.Frame(self.root, padding="20")
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(main_frame, text="Text to Speech Converter", font=("Arial", 16, "bold")).pack(pady=10)
            
            file_frame = ttk.LabelFrame(main_frame, text="Файл", padding="10")
            file_frame.pack(fill=tk.X, pady=5)
            
            ttk.Entry(file_frame, textvariable=self.input_file, width=50).pack(side=tk.LEFT, padx=5)
            ttk.Button(file_frame, text="Открыть", command=self.open_file).pack(side=tk.LEFT)
            
            supported_formats = "txt, pdf, epub, fb2"
            ttk.Label(main_frame, text=f"Поддерживаемые форматы: {supported_formats}", 
                      font=("Arial", 8), foreground="gray").pack()
            
            output_frame = ttk.LabelFrame(main_frame, text="Папка для сохранения", padding="10")
            output_frame.pack(fill=tk.X, pady=5)
            
            ttk.Entry(output_frame, textvariable=self.output_dir, width=50).pack(side=tk.LEFT, padx=5)
            ttk.Button(output_frame, text="Выбрать", command=self.select_output_dir).pack(side=tk.LEFT)
            
            voice_frame = ttk.LabelFrame(main_frame, text="Голос", padding="10")
            voice_frame.pack(fill=tk.X, pady=5)
            
            voices = [
                "ru-RU-SvetlanaNeural",
                "ru-RU-DmitryNeural", 
                "ru-RU-ElizabethNeural",
                "en-US-JennyNeural",
                "en-US-GuyNeural",
                "UK-RomanNeural",
                "UK-LydiaNeural"
            ]
            ttk.Combobox(voice_frame, textvariable=self.voice, values=voices, width=30).pack()
            
            split_frame = ttk.LabelFrame(main_frame, text="Разделение файла (минуты)", padding="10")
            split_frame.pack(fill=tk.X, pady=5)
            
            ttk.Entry(split_frame, textvariable=self.split_duration, width=15).pack()
            ttk.Label(split_frame, text="0 = не делить").pack()
            
            self.btn_convert = ttk.Button(main_frame, text="Конвертировать в MP3", 
                                           command=self.start_conversion)
            self.btn_convert.pack(pady=20)
            
            ttk.Label(main_frame, textvariable=self.progress).pack(pady=10)
            
            progress_bar = ttk.Progressbar(main_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=5)
            self.progress_bar = progress_bar
            
            status_frame = ttk.LabelFrame(main_frame, text="Лог", padding="10")
            status_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            
            self.log_text = tk.Text(status_frame, height=10, width=70)
            self.log_text.pack(fill=tk.BOTH, expand=True)
            
            if TELEGRAM_AVAILABLE:
                ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
                btn_frame = ttk.Frame(main_frame).pack()
                ttk.Label(btn_frame, text="Токен бота:").pack(side=tk.LEFT)
                self.telegram_token = tk.StringVar()
                ttk.Entry(btn_frame, textvariable=self.telegram_token, width=25).pack(side=tk.LEFT, padx=5)
                ttk.Button(btn_frame, text="Запустить Telegram бот", 
                          command=self.start_telegram_bot).pack(side=tk.LEFT)
        
        def log(self, message):
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
        
        def open_file(self):
            filetypes = [
                ("Все поддерживаемые", "*.txt *.pdf *.epub *.fb2"),
                ("Текстовые", "*.txt"),
                ("PDF", "*.pdf"),
                ("EPUB", "*.epub"),
                ("FB2", "*.fb2")
            ]
            filename = filedialog.askopenfilename(filetypes=filetypes)
            if filename:
                self.input_file.set(filename)
                self.log(f"Выбран файл: {filename}")
        
        def select_output_dir(self):
            dirname = filedialog.askdirectory(initialdir=self.output_dir.get())
            if dirname:
                self.output_dir.set(dirname)
                self.log(f"Папка сохранения: {dirname}")
        
        def start_conversion(self):
            if not self.input_file.get():
                messagebox.showerror("Ошибка", "Выберите файл!")
                return
            
            if self.is_converting:
                return
                
            self.is_converting = True
            self.btn_convert.config(state=tk.DISABLED)
            self.progress_bar.start()
            
            from threading import Thread
            thread = Thread(target=self.convert_thread)
            thread.start()
        
        def convert_thread(self):
            try:
                result = process_file(
                    self.input_file.get(),
                    self.output_dir.get(),
                    self.voice.get(),
                    self.split_duration.get()
                )
                self.progress.set("Готово!")
                messagebox.showinfo("Успех", f"Конвертация завершена!\nСоздано файлов: {len(result)}")
                
            except Exception as e:
                self.log(f"Ошибка: {e}")
                messagebox.showerror("Ошибка", str(e))
            finally:
                self.is_converting = False
                self.btn_convert.config(state=tk.NORMAL)
                self.progress_bar.stop()
        
        def start_telegram_bot(self):
            token = self.telegram_token.get()
            if not token:
                messagebox.showerror("Ошибка", "Введите токен бота")
                return
            
            self.log("Запуск Telegram бота...")
            from threading import Thread
            thread = Thread(target=run_telegram_bot, args=(token, self.output_dir.get(), self.voice.get(), self.split_duration.get()))
            thread.daemon = True
            thread.start()
            self.log("Бот запущен!")

    root = tk.Tk()
    app = TextToSpeechApp(root)
    root.mainloop()


def main():
    """
    Точка входа в приложение.
    Парсит аргументы и запускает соответствующий режим (GUI/CLI/бот).
    """
    parser = argparse.ArgumentParser(description="Text to Speech Converter")
    parser.add_argument("--input", "-i", help="Входной файл")
    parser.add_argument("--output", "-o", help="Папка для сохранения")
    parser.add_argument("--voice", "-v", default="ru-RU-SvetlanaNeural", help="Голос")
    parser.add_argument("--split", "-s", type=int, default=0, help="Разделить на куски (минуты)")
    parser.add_argument("--bot", "-b", help="Запустить Telegram бот (используйте bot.py)")
    parser.add_argument("--gui", "-g", action="store_true", help="Запустить GUI")
    parser.add_argument("--tts", "-t", default="edge", choices=["edge", "silero"], help="Тип TTS движка: edge (по умолчанию) или silero")
    
    args = parser.parse_args()
    
    # Telegram бот - используйте bot.py для запуска
    if args.bot:
        print("Для запуска бота используйте: python bot.py TOKEN")
        sys.exit(1)
    # GUI
    elif args.gui or (not args.input and (GUI_AVAILABLE or PYQT_AVAILABLE)):
        if PYQT_AVAILABLE or GUI_AVAILABLE:
            gui_mode()
        else:
            print("GUI недоступен. Используйте консольный режим.")
            cli_mode(args)
    # CLI
    else:
        cli_mode(args)


if __name__ == "__main__":
    main()
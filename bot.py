#!/usr/bin/env python3
"""
Telegram Bot запускатель.
Запускает бота в отдельном процессе.
"""

import sys
import os
import subprocess

# Автоматическая активация виртуального окружения (до импортов)
venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv')
if os.path.exists(venv_path):
    for subdir in ['lib', 'lib64']:
        site_packages = os.path.join(venv_path, subdir, 'python3.14', 'site-packages')
        if os.path.exists(site_packages) and site_packages not in sys.path:
            sys.path.insert(0, site_packages)
            break

# Добавляем путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import argparse
import tempfile
import shutil

from tts_converter import (
    extract_text_from_file, split_text_into_chunks, 
    convert_all_chunks_async, convert_all_chunks_silero,
    PYDUB_AVAILABLE, SILERO_AVAILABLE
)
import logging
import soundfile as sf
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout  # Лог в stdout чтобы не путать с ошибками
)
logger = logging.getLogger(__name__)

# Константы
SUPPORTED_EXTENSIONS = ['txt', 'pdf', 'epub', 'fb2']
EDGE_VOICES = [
    "ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural", "ru-RU-ElizabethNeural",
    "en-US-JennyNeural", "en-US-GuyNeural", "UK-RomanNeural", "UK-LydiaNeural"
]
SILERO_VOICES = ["xenia", "aidar", "aleksandr", "alyona", "anna", "danil", "dasha", "max", "pavel"]

# Хранилище сессий
user_sessions = {}

class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.file_path = None
        self.file_name = None
        self.split_duration = 0
        self.tts_type = "edge"
        self.voice = "ru-RU-SvetlanaNeural"
        self.waiting_for = None
        self.available_voices = []

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]

async def retry_api_call(coro_fn, max_retries=3, delay=2):
    """
    Выполняет API вызов с повторными попытками при таймаутах.
    coro_fn — вызываемая функция возвращающая корутину (lambda: ...)
    """
    import asyncio
    from telegram.error import TimedOut, NetworkError
    
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except (TimedOut, NetworkError) as e:
            if attempt < max_retries - 1:
                wait = delay * (attempt + 1)
                logger.warning(f"Таймаут API (попытка {attempt + 1}/{max_retries}): {e}, ожидание {wait}с")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Все {max_retries} попыток API неудачны: {e}")
                raise

async def safe_reply_text(message, text, **kwargs):
    """
    Безопасная отправка текстового сообщения с повторными попытками.
    """
    await retry_api_call(lambda: message.reply_text(text, **kwargs))

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply_text(update.message,
        "🎙 <b>Text to Speech Converter</b>\n\n"
        "Отправьте мне текстовый файл (TXT, PDF, EPUB, FB2) - я конвертирую его в MP3 аудио.\n\n"
        "После отправки файла я задам несколько вопросов о параметрах конвертации.",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply_text(update.message,
        "📖 <b>Помощь</b>\n\n"
        "Отправьте текстовый файл для конвертации.\n"
        "Команды: /start - начать, /help - помощь",
        parse_mode="HTML"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    
    try:
        file = await retry_api_call(update.message.document.get_file)
        ext = update.message.document.file_name.split('.')[-1].lower()
        file_name = update.message.document.file_name
        
        if ext not in SUPPORTED_EXTENSIONS:
            await safe_reply_text(update.message,
                f"❌ <b>Неверный формат файла!</b>\n\n"
                f"Поддерживаемые форматы: <code>{', '.join(SUPPORTED_EXTENSIONS)}</code>\n\n"
                f"Вы отправили: <code>.{ext}</code>",
                parse_mode="HTML"
            )
            return
        
        session.file_name = file_name
        temp_dir = tempfile.mkdtemp()
        session.file_path = os.path.join(temp_dir, file_name)
        await file.download_to_drive(session.file_path)
        
        await safe_reply_text(update.message,
            f"✅ <b>Файл получен!</b>\n\n"
            f"📄 <code>{file_name}</code>\n\n"
            f"<b>Шаг 1 из 3</b>\n"
            f"На сколько минут разбить аудио файл?\n"
            f"Отправьте число (например: <code>30</code>)\n"
            f"Если <code>0</code> - весь текст в одном файле.",
            parse_mode="HTML"
        )
        session.waiting_for = "split"
        
    except Exception as e:
        logger.error(f"Ошибка при обработке документа: {e}")
        await safe_reply_text(update.message, f"❌ Ошибка: {str(e)}")
        if session.file_path and os.path.exists(os.path.dirname(session.file_path)):
            try:
                shutil.rmtree(os.path.dirname(session.file_path))
            except:
                pass
        session.file_path = None

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text.strip()
    
    if not session.waiting_for or not session.file_path:
        await safe_reply_text(update.message, "Отправьте файл для конвертации или /start для начала.")
        return
    
    try:
        if session.waiting_for == "split":
            try:
                split_val = int(text)
                if split_val < 0:
                    await safe_reply_text(update.message, "❌ Число должно быть положительным.")
                    return
                session.split_duration = split_val
            except ValueError:
                await safe_reply_text(update.message, "❌ Введите число. Например: 30")
                return
            
            split_text = "одним файлом" if split_val == 0 else f"по {split_val} минут"
            await safe_reply_text(update.message,
                f"✅ Разбиение: <b>{split_text}</b>\n\n"
                f"<b>Шаг 2 из 3</b>\n"
                f"Выберите движок TTS:\n"
                f"<code>1</code> - Edge TTS (онлайн)\n"
                f"<code>2</code> - Silero (офлайн)\n\n"
                f"Отправьте <code>1</code> или <code>2</code>",
                parse_mode="HTML"
            )
            session.waiting_for = "engine"
        
        elif session.waiting_for == "engine":
            if text == "1":
                session.tts_type = "edge"
                session.available_voices = EDGE_VOICES
            elif text == "2":
                if not SILERO_AVAILABLE:
                    await safe_reply_text(update.message, "❌ Silero не установлен. Использую Edge TTS.")
                    session.tts_type = "edge"
                    session.available_voices = EDGE_VOICES
                else:
                    session.tts_type = "silero"
                    session.available_voices = SILERO_VOICES
            else:
                await safe_reply_text(update.message, "Введите 1 или 2")
                return
            
            voice_list = "\n".join([f"<code>{i + 1}</code> - {v}" for i, v in enumerate(session.available_voices)])
            engine_name = "Edge TTS" if session.tts_type == "edge" else "Silero"
            await safe_reply_text(update.message,
                f"✅ Движок: <b>{engine_name}</b>\n\n"
                f"<b>Шаг 3 из 3</b>\n"
                f"Выберите голос (отправьте номер):\n\n{voice_list}",
                parse_mode="HTML"
            )
            session.waiting_for = "voice"
        
        elif session.waiting_for == "voice":
            try:
                voice_idx = int(text) - 1
                if voice_idx < 0 or voice_idx >= len(session.available_voices):
                    await safe_reply_text(update.message, f"❌ Номер должен быть от 1 до {len(session.available_voices)}")
                    return
                session.voice = session.available_voices[voice_idx]
            except ValueError:
                await safe_reply_text(update.message, "❌ Введите номер голоса")
                return
            
            await safe_reply_text(update.message,
                f"✅ Голос: <b>{session.voice}</b>\n\n"
                f"🚀 <b>Начинаю конвертацию...</b>",
                parse_mode="HTML"
            )
            
            session.waiting_for = None
            await process_and_send(update, session)
            
    except Exception as e:
        logger.error(f"Ошибка в handle_text: {e}")
        await safe_reply_text(update.message, f"❌ Ошибка: {str(e)}")
        session.waiting_for = None

async def process_and_send(update: Update, session):
    user_id = update.effective_user.id
    
    try:
        await safe_reply_text(update.message, "📖 Извлекаю текст из файла...")
        text = extract_text_from_file(session.file_path)
        if not text.strip():
            await safe_reply_text(update.message, "❌ Не удалось извлечь текст из файла.")
            return
        
        await safe_reply_text(update.message, "✂️ Разбиваю текст на части...")
        chunks = split_text_into_chunks(text, tts_type=session.tts_type)
        num_chunks = len(chunks)
        
        temp_dir = os.path.dirname(session.file_path)
        ext = ".wav" if session.tts_type == "silero" else ".mp3"
        temp_files = [os.path.join(temp_dir, f"part{i}{ext}") for i in range(num_chunks)]
        
        progress_msg = await retry_api_call(lambda: update.message.reply_text(
            f"🎙 Конвертирую...\n0/{num_chunks} частей",
            parse_mode="HTML"
        ))
        
        if session.tts_type == "silero":
            convert_all_chunks_silero(chunks, temp_files, session.voice)
        else:
            last_update = 0
            async def progress_callback(p):
                nonlocal last_update
                current = int(p * num_chunks / 100)
                if current > last_update and current % 10 == 0:
                    last_update = current
                    try:
                        await retry_api_call(lambda: progress_msg.edit_text(
                            f"🎙 Конвертирую...\n{current}/{num_chunks} частей",
                            parse_mode="HTML"
                        ))
                    except:
                        pass
            
            await convert_all_chunks_async(chunks, temp_files, session.voice, progress_callback, "+0%")
        
        await retry_api_call(lambda: progress_msg.edit_text(f"✅ Конвертировано {num_chunks} частей", parse_mode="HTML"))
        
        # Объединение и отправка
        existing_files = [f for f in temp_files if os.path.exists(f)]
        
        if not existing_files:
            await safe_reply_text(update.message, "❌ Ошибка: не создано ни одного файла.")
            return
        
        # Читаем все WAV/MP3 и объединяем
        audios = []
        sr = 48000
        for f in existing_files:
            if f.endswith('.mp3'):
                # Конвертируем MP3 в WAV через ffmpeg для объединения
                tmp_wav = f.replace('.mp3', '_tmp.wav')
                subprocess.run(['ffmpeg', '-y', '-i', f, '-acodec', 'pcm_s16le', '-ar', '48000', tmp_wav],
                              capture_output=True, check=True)
                audio_data, sr = sf.read(tmp_wav)
                audios.append(audio_data)
                os.remove(tmp_wav)
            else:
                audio_data, sr = sf.read(f)
                audios.append(audio_data)
        
        combined_audio = np.concatenate(audios)
        duration_sec = len(combined_audio) / sr
        await safe_reply_text(update.message, f"📊 Длительность: {duration_sec/60:.1f} мин", parse_mode="HTML")
        
        # Определяем как делить
        max_duration_sec = session.split_duration * 60 if session.split_duration > 0 else float('inf')
        final_files = []
        
        if duration_sec > max_duration_sec:
            await safe_reply_text(update.message, f"✂️ Разбиваю на куски по {session.split_duration} минут...", parse_mode="HTML")
            samples_per_chunk = int(sr * session.split_duration * 60)
            chunk_num = 1
            
            for i in range(0, len(combined_audio), samples_per_chunk):
                chunk = combined_audio[i:i + samples_per_chunk]
                wav_path = os.path.join(temp_dir, f"chunk_{chunk_num}.wav")
                sf.write(wav_path, chunk, sr)
                
                # Конвертируем WAV в MP3 через ffmpeg
                mp3_path = os.path.join(temp_dir, f"{session.file_name.rsplit('.', 1)[0]}_part{chunk_num}.mp3")
                subprocess.run(['ffmpeg', '-y', '-i', wav_path, '-codec:a', 'libmp3lame', '-qscale:a', '2', mp3_path],
                              capture_output=True, check=True)
                os.remove(wav_path)
                
                if os.path.getsize(mp3_path) < 48 * 1024 * 1024:  # Telegram limit ~48MB
                    final_files.append(mp3_path)
                else:
                    await safe_reply_text(update.message, f"⚠️ Часть {chunk_num} слишком большая, пропускаю")
                    os.remove(mp3_path)
                
                chunk_num += 1
        else:
            # Один файл
            wav_path = os.path.join(temp_dir, "combined.wav")
            sf.write(wav_path, combined_audio, sr)
            mp3_path = os.path.join(temp_dir, f"{session.file_name.rsplit('.', 1)[0]}.mp3")
            subprocess.run(['ffmpeg', '-y', '-i', wav_path, '-codec:a', 'libmp3lame', '-qscale:a', '2', mp3_path],
                          capture_output=True, check=True)
            os.remove(wav_path)
            final_files.append(mp3_path)
        
        # Отправка файлов
        await safe_reply_text(update.message, f"📤 Отправляю {len(final_files)} файлов...", parse_mode="HTML")
        
        for f in final_files:
            try:
                with open(f, "rb") as file:
                    doc_data = file.read()
                    await retry_api_call(lambda: update.message.reply_document(
                        document=doc_data,
                        filename=os.path.basename(f),
                        caption=f"🎵 {os.path.basename(f)}"
                    ))
            except Exception as e:
                logger.error(f"Ошибка отправки {f}: {e}")
                await safe_reply_text(update.message, f"⚠️ Не удалось отправить {os.path.basename(f)}: {str(e)}")
        
        await safe_reply_text(update.message, "✅ <b>Готово!</b>", parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await safe_reply_text(update.message, f"❌ Ошибка: {str(e)}")
    
    finally:
        if session.file_path and os.path.exists(os.path.dirname(session.file_path)):
            try:
                shutil.rmtree(os.path.dirname(session.file_path))
            except:
                pass
        user_sessions[user_id] = UserSession(user_id)

def main():
    parser = argparse.ArgumentParser(description="Telegram Bot")
    parser.add_argument("token", help="Telegram Bot Token")
    args = parser.parse_args()
    
    from telegram.request import HTTPXRequest
    
    # HTTP запрос с повторными попытками при таймаутах
    request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )
    
    application = Application.builder().token(args.token).request(request).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Telegram бот запущен...")
    
    # run_polling синхронный и сам управляет event loop
    application.run_polling()

if __name__ == "__main__":
    main()
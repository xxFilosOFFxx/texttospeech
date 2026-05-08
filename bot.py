#!/usr/bin/env python3
"""
Telegram Bot — полностью изолированная архитектура.
Конвертация запускается как отдельный процесс, бот только общается с пользователями.
"""

import sys
import os
import subprocess
import asyncio
import tempfile
import shutil
import time
import threading

# Автоматическая активация виртуального окружения
venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv')
if os.path.exists(venv_path):
    for subdir in ['lib', 'lib64']:
        site_packages = os.path.join(venv_path, subdir, 'python3.14', 'site-packages')
        if os.path.exists(site_packages) and site_packages not in sys.path:
            sys.path.insert(0, site_packages)
            break

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

EDGE_VOICES = [
    "ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural", "ru-RU-ElizabethNeural",
    "en-US-JennyNeural", "en-US-GuyNeural", "UK-RomanNeural", "UK-LydiaNeural"
]
SILERO_VOICES = ["xenia", "aidar", "aleksandr", "alyona", "anna", "danil", "dasha", "max", "pavel"]

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

active_conversions = {}

async def retry_send(message, text, max_retries=2, delay=1, **kwargs):
    """Быстрая отправка сообщения с минимальными повторами."""
    from telegram.error import TimedOut, NetworkError
    for attempt in range(max_retries):
        try:
            return await message.reply_text(text, **kwargs)
        except (TimedOut, NetworkError) as e:
            if attempt < max_retries - 1:
                logger.warning(f"Таймаут отправки (попытка {attempt + 1}): {e}")
                await asyncio.sleep(delay)
            else:
                raise

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await retry_send(update.message,
        "🎙 <b>Text to Speech Converter</b>\n\n"
        "Отправьте мне текстовый файл (TXT, PDF, EPUB, FB2) - я конвертирую его в MP3 аудио.\n\n"
        "После отправки файла я задам несколько вопросов о параметрах конвертации.",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await retry_send(update.message,
        "📖 <b>Помощь</b>\n\n"
        "Отправьте текстовый файл для конвертации.\n"
        "Команды: /start - начать, /help - помощь",
        parse_mode="HTML"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    
    if user_id in active_conversions:
        await retry_send(update.message, "⏳ У вас уже идёт конвертация. Дождитесь завершения.")
        return
    
    try:
        file = await update.message.document.get_file()
        ext = update.message.document.file_name.split('.')[-1].lower()
        file_name = update.message.document.file_name
        
        if ext not in ['txt', 'pdf', 'epub', 'fb2']:
            await retry_send(update.message,
                f"❌ <b>Неверный формат!</b>\n\nПоддерживаемые: <code>txt, pdf, epub, fb2</code>\nВы отправили: <code>.{ext}</code>",
                parse_mode="HTML"
            )
            return
        
        session.file_name = file_name
        temp_dir = tempfile.mkdtemp()
        session.file_path = os.path.join(temp_dir, file_name)
        await file.download_to_drive(session.file_path)
        
        await retry_send(update.message,
            f"✅ <b>Файл получен!</b>\n\n📄 <code>{file_name}</code>\n\n"
            f"<b>Шаг 1 из 3</b>\nНа сколько минут разбить аудио?\n"
            f"Отправьте число (например: <code>30</code>). Если <code>0</code> - одним файлом.",
            parse_mode="HTML"
        )
        session.waiting_for = "split"
        
    except Exception as e:
        logger.error(f"Ошибка при обработке документа: {e}")
        await retry_send(update.message, f"❌ Ошибка: {str(e)}")
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
        await retry_send(update.message, "Отправьте файл для конвертации или /start для начала.")
        return
    
    try:
        if session.waiting_for == "split":
            try:
                split_val = int(text)
                if split_val < 0:
                    await retry_send(update.message, "❌ Число должно быть положительным.")
                    return
                session.split_duration = split_val
            except ValueError:
                await retry_send(update.message, "❌ Введите число. Например: 30")
                return
            
            split_text = "одним файлом" if split_val == 0 else f"по {split_val} минут"
            await retry_send(update.message,
                f"✅ Разбиение: <b>{split_text}</b>\n\n"
                f"<b>Шаг 2 из 3</b>\nВыберите движок TTS:\n"
                f"<code>1</code> - Edge TTS (онлайн)\n<code>2</code> - Silero (офлайн)\n\n"
                f"Отправьте <code>1</code> или <code>2</code>",
                parse_mode="HTML"
            )
            session.waiting_for = "engine"
        
        elif session.waiting_for == "engine":
            if text == "1":
                session.tts_type = "edge"
                session.available_voices = EDGE_VOICES
            elif text == "2":
                session.tts_type = "edge"
                session.available_voices = EDGE_VOICES
                await retry_send(update.message, "❌ Silero не установлен. Использую Edge TTS.")
            else:
                await retry_send(update.message, "Введите 1 или 2")
                return
            
            voice_list = "\n".join([f"<code>{i + 1}</code> - {v}" for i, v in enumerate(session.available_voices)])
            engine_name = "Edge TTS" if session.tts_type == "edge" else "Silero"
            await retry_send(update.message,
                f"✅ Движок: <b>{engine_name}</b>\n\n"
                f"<b>Шаг 3 из 3</b>\nВыберите голос (отправьте номер):\n\n{voice_list}",
                parse_mode="HTML"
            )
            session.waiting_for = "voice"
        
        elif session.waiting_for == "voice":
            try:
                voice_idx = int(text) - 1
                if voice_idx < 0 or voice_idx >= len(session.available_voices):
                    await retry_send(update.message, f"❌ Номер от 1 до {len(session.available_voices)}")
                    return
                session.voice = session.available_voices[voice_idx]
            except ValueError:
                await retry_send(update.message, "❌ Введите номер голоса")
                return
            
            await retry_send(update.message,
                f"✅ Голос: <b>{session.voice}</b>\n\n🚀 <b>Начинаю конвертацию...</b>",
                parse_mode="HTML"
            )
            
            session.waiting_for = None
            launch_conversion(update, session)
            user_sessions[user_id] = UserSession(user_id)
            
    except Exception as e:
        logger.error(f"Ошибка в handle_text: {e}")
        await retry_send(update.message, f"❌ Ошибка: {str(e)}")
        session.waiting_for = None

def launch_conversion(update, session):
    """Запускает конвертацию как отдельный процесс."""
    user_id = update.effective_user.id
    temp_dir = os.path.dirname(session.file_path)
    
    active_conversions[user_id] = {
        'update': update,
        'session': {
            'file_path': session.file_path,
            'file_name': session.file_name,
            'split_duration': session.split_duration,
            'tts_type': session.tts_type,
            'voice': session.voice,
            'temp_dir': temp_dir,
        },
        'process': None,
    }
    
    # Запускаем конвертацию через subprocess
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'bin', 'python')
    converter = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tts_converter.py')
    
    split_arg = str(session.split_duration)
    voice_arg = session.voice
    
    process = subprocess.Popen(
        [venv_python, converter, '-i', session.file_path, '-o', temp_dir,
         '-v', voice_arg, '-s', split_arg],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    active_conversions[user_id]['process'] = process
    
    def monitor_process():
        """Ждёт завершения процесса и создаёт файл-флаг."""
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.error(f"Конвертация для user {user_id} завершилась с ошибкой: {stderr.decode()}")
        
        # Создаём флаг что процесс завершён
        flag_file = os.path.join(temp_dir, '.conversion_done')
        with open(flag_file, 'w') as f:
            f.write(f"returncode={process.returncode}\n")
    
    threading.Thread(target=monitor_process, daemon=True).start()

async def conversion_watcher(application):
    """Фоновая задача — отслеживает завершение конвертаций и отправляет файлы."""
    while True:
        await asyncio.sleep(2)
        
        for user_id in list(active_conversions.keys()):
            conv = active_conversions[user_id]
            session_data = conv['session']
            temp_dir = session_data['temp_dir']
            
            flag_file = os.path.join(temp_dir, '.conversion_done')
            if not os.path.exists(flag_file):
                continue
            
            # Конвертация завершена
            del active_conversions[user_id]
            
            update = conv['update']
            message = update.message
            
            # Проверяем успешность
            with open(flag_file) as f:
                content = f.read()
            
            if 'returncode=0' not in content:
                await message.reply_text(f"❌ Ошибка конвертации:\n{content}")
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
                continue
            
            # Находим MP3 файлы (результаты конвертации)
            mp3_files = [f for f in os.listdir(temp_dir) 
                        if f.endswith('.mp3') and f != 'preview.mp3']
            
            if not mp3_files:
                await message.reply_text("❌ Не удалось создать аудио файл.")
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
                continue
            
            # Отправляем файлы
            for mp3_file in sorted(mp3_files):
                file_path = os.path.join(temp_dir, mp3_file)
                try:
                    with open(file_path, "rb") as f:
                        await message.reply_document(
                            document=f,
                            filename=mp3_file,
                            caption=f"🎵 {mp3_file}"
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки {mp3_file}: {e}")
                    await message.reply_text(f"⚠️ Не удалось отправить {mp3_file}")
            
            await message.reply_text("✅ <b>Готово!</b>", parse_mode="HTML")
            
            # Очистка
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

async def post_init(application):
    """Запускает фоновый наблюдатель после инициализации бота."""
    application.create_task(conversion_watcher(application))

def main():
    parser = argparse.ArgumentParser(description="Telegram Bot")
    parser.add_argument("token", help="Telegram Bot Token")
    args = parser.parse_args()
    
    from telegram.request import HTTPXRequest
    
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )
    
    application = Application.builder().token(args.token).request(request).build()
    application.post_init = post_init
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Telegram бот запущен...")
    application.run_polling(bootstrap_retries=10)

import argparse

if __name__ == "__main__":
    import time
    while True:
        try:
            main()
        except Exception as e:
            logger.error(f"Бот упал: {e}, перезапуск через 30с...")
            time.sleep(30)

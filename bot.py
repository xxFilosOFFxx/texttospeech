#!/usr/bin/env python3
"""
Telegram Bot — минимальный, быстрый, с полной изоляцией конвертации.
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
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)

EDGE_VOICES = [
    "ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural", "ru-RU-ElizabethNeural",
    "en-US-JennyNeural", "en-US-GuyNeural", "UK-RomanNeural", "UK-LydiaNeural"
]

user_sessions = {}
active_conversions = {}

class UserSession:
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
        "Отправьте текстовый файл (TXT, PDF, EPUB, FB2).\n"
        "После отправки задам вопросы о параметрах.",
        parse_mode="HTML"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    
    if user_id in active_conversions:
        await update.message.reply_text("⏳ У вас уже идёт конвертация. Дождитесь завершения.")
        return
    
    try:
        file = await update.message.document.get_file()
        ext = update.message.document.file_name.split('.')[-1].lower()
        file_name = update.message.document.file_name
        
        if ext not in ['txt', 'pdf', 'epub', 'fb2']:
            await update.message.reply_text(f"❌ Формат .{ext} не поддерживается. Только txt, pdf, epub, fb2")
            return
        
        session.file_name = file_name
        temp_dir = tempfile.mkdtemp()
        session.file_path = os.path.join(temp_dir, file_name)
        await file.download_to_drive(session.file_path)
        
        await update.message.reply_text(
            f"📄 <b>{file_name}</b> получен!\n\n"
            f"<b>Шаг 1/3:</b> На сколько минут разбить аудио?\n"
            f"<code>0</code> = одним файлом",
            parse_mode="HTML"
        )
        session.waiting_for = "split"
        
    except Exception as e:
        logger.error(f"Ошибка документа: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text.strip()
    
    if not session.waiting_for or not session.file_path:
        await update.message.reply_text("Отправьте файл или /start")
        return
    
    if session.waiting_for == "split":
        try:
            val = int(text)
            if val < 0:
                await update.message.reply_text("Число должно быть >= 0")
                return
            session.split_duration = val
        except ValueError:
            await update.message.reply_text("Введите число")
            return
        
        await update.message.reply_text(
            f"<b>Шаг 2/3:</b> Выберите голос:\n\n" +
            "\n".join([f"<code>{i+1}</code> - {v}" for i, v in enumerate(EDGE_VOICES)]),
            parse_mode="HTML"
        )
        session.waiting_for = "voice"
    
    elif session.waiting_for == "voice":
        try:
            idx = int(text) - 1
            if idx < 0 or idx >= len(EDGE_VOICES):
                await update.message.reply_text(f"Номер от 1 до {len(EDGE_VOICES)}")
                return
            session.voice = EDGE_VOICES[idx]
        except ValueError:
            await update.message.reply_text("Введите номер голоса")
            return
        
        await update.message.reply_text("🚀 Начинаю конвертацию...")
        
        # Сохраняем данные и запускаем фоновый процесс
        temp_dir = os.path.dirname(session.file_path)
        active_conversions[user_id] = {
            'chat_id': update.message.chat_id,
            'bot': context.bot,
            'temp_dir': temp_dir,
            'start_time': time.time(),
        }
        
        # Сбрасываем сессию чтобы пользователь мог работать дальше
        user_sessions[user_id] = UserSession(user_id)
        
        # Запускаем конвертацию в отдельном процессе
        venv_python = os.path.join(venv_path, 'bin', 'python')
        converter = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tts_converter.py')
        
        subprocess.Popen(
            [venv_python, converter, '-i', session.file_path, '-o', temp_dir,
             '-v', session.voice, '-s', str(session.split_duration)],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

async def conversion_poller(application):
    """Периодически проверяет завершённые конвертации и отправляет файлы."""
    bot = application.bot
    while True:
        await asyncio.sleep(3)
        
        for user_id in list(active_conversions.keys()):
            conv = active_conversions[user_id]
            temp_dir = conv['temp_dir']
            
            # Проверяем завершение через наличие MP3 файлов
            mp3_files = [f for f in os.listdir(temp_dir) 
                        if f.endswith('.mp3') and f != 'preview.mp3']
            
            if not mp3_files:
                # Проверяем не слишком ли долго ждём (таймаут 30 мин)
                if time.time() - conv['start_time'] > 1800:
                    try:
                        await bot.send_message(chat_id=conv['chat_id'], text="⏰ Таймаут конвертации (30 мин)")
                    except:
                        pass
                    del active_conversions[user_id]
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass
                continue
            
            # Конвертация завершена — отправляем файлы
            del active_conversions[user_id]
            
            for mp3_file in sorted(mp3_files):
                fp = os.path.join(temp_dir, mp3_file)
                try:
                    with open(fp, "rb") as f:
                        await bot.send_document(
                            chat_id=conv['chat_id'],
                            document=f,
                            filename=mp3_file,
                            caption=f"🎵 {mp3_file}"
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки: {e}")
            
            try:
                await bot.send_message(chat_id=conv['chat_id'], text="✅ Готово!", parse_mode="HTML")
            except:
                pass
            
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

import argparse

def main():
    parser = argparse.ArgumentParser(description="Telegram Bot")
    parser.add_argument("token", help="Telegram Bot Token")
    args = parser.parse_args()
    
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
    )
    
    application = Application.builder().token(args.token).request(request).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    async def post_init(app):
        asyncio.create_task(conversion_poller(app))
    
    application.post_init = post_init
    
    print("Telegram бот запущен...")
    application.run_polling(bootstrap_retries=5)

if __name__ == "__main__":
    main()

import os
import logging
import tempfile
import threading
import asyncio
import time
from flask import Flask, request, jsonify
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import yt_dlp
import json
import traceback
import requests
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаем экземпляр Flask приложения
app = Flask(__name__)

# Ваш токен Telegram бота
TELEGRAM_BOT_TOKEN = "7798669926:AAHyGpiKprJgcRt1OBY0WsznO6c0yjnsp94"

# URL вашего Railway проекта
PROJECT_URL = os.environ.get("RAILWAY_STATIC_URL", "https://web-production-c09e9.up.railway.app")

# Локализация сообщений для русского (ru), украинского (uk) и английского (en).
messages = {
    'start': {
        'en': (
            "Hello!\n"
            "Send me a link to a video from TikTok, Instagram Reels, LinkedIn or Facebook, "
            "and I'll download it for you."
        ),
        'ru': (
            "Привет!\n"
            "Отправь мне ссылку на видео из TikTok, Instagram Reels, LinkedIn или Facebook, "
            "и я скачаю его для тебя."
        ),
        'uk': (
            "Привіт!\n"
            "Надішли мені посилання на відео з TikTok, Instagram Reels, LinkedIn чи Facebook, "
            "і я завантажу його для тебе."
        )
    },
    'not_supported': {
        'en': "The link is not recognized as a supported video source.",
        'ru': "Ссылка не распознана как поддерживаемый источник видео.",
        'uk': "Посилання не розпізнано як підтримуване джерело відео."
    },
    'processing': {
        'en': "Processing your link, please wait...",
        'ru': "Обрабатываю вашу ссылку, пожалуйста, подождите...",
        'uk': "Обробляю ваше посилання, будь ласка, зачекайте..."
    },
    'error': {
        'en': "An error occurred while downloading the video. Please try again later.",
        'ru': "Произошла ошибка при загрузке видео. Попробуйте повторить запрос позже.",
        'uk': "Сталася помилка під час завантаження відео. Спробуйте повторити запит пізніше."
    },
    'menu': {
        'en': "Choose an action from the menu:",
        'ru': "Выберите действие из меню:",
        'uk': "Оберіть дію з меню:"
    }
}

# Текст для кнопок меню
inline_buttons_text = {
    'report_issue': {
        'en': "Report an issue",
        'ru': "Сообщить о проблеме",
        'uk': "Повідомити про проблему"
    },
    'donate_author': {
        'en': "Support the author",
        'ru': "Поблагодарить автора",
        'uk': "Підтримати автора"
    }
}

# Глобальные переменные
application = None
event_loop = None
updates_queue = asyncio.Queue()

def get_user_language(update: Update) -> str:
    """Определяем язык пользователя по его настройкам в Telegram."""
    user_lang = update.effective_user.language_code
    if user_lang is None:
        return "en"
    user_lang = user_lang.lower()
    if user_lang.startswith("ru"):
        return "ru"
    elif user_lang.startswith("uk"):
        return "uk"
    else:
        return "en"

def t(key: str, lang: str) -> str:
    """Возвращает локализованное сообщение по ключу для заданного языка."""
    return messages.get(key, {}).get(lang, messages[key]['en'])

def download_tiktok_alternative(url: str) -> str:
    """Скачивает видео из TikTok через альтернативный сервис без водяного знака."""
    logger.info(f"Попытка скачать TikTok видео без водяного знака: {url}")
    
    try:
        # Метод 1: ИспользованиеMusicalDown API
        api_url = "https://musicaldown.com/api/post"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://musicaldown.com/',
            'Origin': 'https://musicaldown.com'
        }
        data = {'link': url, 'submit': ''}
        
        response = requests.post(api_url, headers=headers, data=data, allow_redirects=True)
        
        if response.status_code == 200:
            # Ищем ссылку на видео без водяного знака
            no_watermark_url = re.search(r'href=[\'"]?([^\'" >]+).*?Download Server 1', response.text)
            
            if no_watermark_url:
                download_url = no_watermark_url.group(1)
                
                # Скачиваем видео
                video_response = requests.get(download_url, stream=True)
                if video_response.status_code == 200:
                    # Сохраняем видео во временный файл
                    temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                    with open(temp_path, 'wb') as f:
                        for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    logger.info(f"Видео без водяного знака успешно скачано (метод 1): {temp_path}")
                    return temp_path
        
        # Метод 2: Использование SnapTik API
        api_url = "https://api.snaptik.app/video-info"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://snaptik.app/'
        }
        params = {'url': url}
        
        response = requests.get(api_url, headers=headers, params=params)
        
        if response.status_code == 200:
            json_data = response.json()
            
            if json_data.get('code') == 0 and 'data' in json_data:
                # Найдем ссылку без водяного знака
                no_watermark_url = None
                for video in json_data['data'].get('videos', []):
                    if video.get('watermark') is False:
                        no_watermark_url = video.get('url')
                        break
                
                if not no_watermark_url:
                    # Если не нашли ссылку без водяного знака, берем любую
                    for video in json_data['data'].get('videos', []):
                        if video.get('url'):
                            no_watermark_url = video.get('url')
                            break
                
                if no_watermark_url:
                    # Скачиваем видео
                    video_response = requests.get(no_watermark_url, stream=True)
                    if video_response.status_code == 200:
                        # Сохраняем видео во временный файл
                        temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                        with open(temp_path, 'wb') as f:
                            for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f.write(chunk)
                        logger.info(f"Видео без водяного знака успешно скачано (метод 2): {temp_path}")
                        return temp_path
        
        # Метод 3: Использование SSSTik API
        api_url = "https://ssstik.io/api/v1/download"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://ssstik.io/',
            'Origin': 'https://ssstik.io',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {'url': url, 'hd': '1', 'watermark': '0', 'tt': '0'}
        
        response = requests.post(api_url, headers=headers, data=data)
        
        if response.status_code == 200:
            # Ищем ссылку на видео без водяного знака в HTML-ответе
            download_url = re.search(r'href=[\'"]?([^\'" >]+mp4[^\'" >]*)', response.text)
            
            if download_url:
                download_url = download_url.group(1)
                
                # Скачиваем видео
                video_response = requests.get(download_url, stream=True)
                if video_response.status_code == 200:
                    # Сохраняем видео во временный файл
                    temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                    with open(temp_path, 'wb') as f:
                        for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    logger.info(f"Видео без водяного знака успешно скачано (метод 3): {temp_path}")
                    return temp_path
        
        # Метод 4: Использование TikMate API
        tikmate_url = "https://tikmate.app/api/lookup"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://tikmate.app/',
            'Origin': 'https://tikmate.app',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {'url': url}
        
        response = requests.post(tikmate_url, headers=headers, data=data)
        
        if response.status_code == 200:
            json_data = response.json()
            
            if 'success' in json_data and json_data['success'] and 'id' in json_data:
                video_id = json_data['id']
                download_url = f"https://tikmate.app/download/{video_id}/mp4/nowm/1"
                
                # Скачиваем видео
                video_response = requests.get(download_url, stream=True)
                if video_response.status_code == 200:
                    # Сохраняем видео во временный файл
                    temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                    with open(temp_path, 'wb') as f:
                        for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    logger.info(f"Видео без водяного знака успешно скачано (метод 4): {temp_path}")
                    return temp_path
        
        # Если все методы не сработали, возвращаем ошибку
        raise Exception("Не удалось скачать видео без водяного знака")
    
    except Exception as e:
        logger.error(f"Ошибка при скачивании видео без водяного знака: {e}")
        raise

def download_video(url: str, is_tiktok: bool = False) -> str:
    """Скачивает видео по заданной ссылке с помощью yt-dlp."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        ydl_opts = {
            'outtmpl': os.path.join(tmpdirname, '%(id)s.%(ext)s'),
            'noplaylist': True,
        }
        if is_tiktok:
            logger.info("Обработка TikTok видео (формат mp4)")
            ydl_opts['format'] = 'mp4'
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Начало скачивания видео: {url}")
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.isfile(filename):
                    filename = os.path.join(tmpdirname, f"{info['id']}.{info.get('ext', 'mp4')}")
                # Сохраняем видео во временный файл в рабочей директории
                temp_video_path = os.path.join("/tmp", f"{info['id']}.{info.get('ext', 'mp4')}")
                with open(filename, 'rb') as f_in, open(temp_video_path, 'wb') as f_out:
                    f_out.write(f_in.read())
                logger.info(f"Видео успешно скачано: {temp_video_path}")
                return temp_video_path
        except Exception as e:
            logger.error(f"Ошибка при скачивании видео: {e}")
            raise e

def remove_tiktok_watermark(video_path: str) -> str:
    """Заглушка для удаления водяного знака с TikTok."""
    logger.info("Удаление водяного знака для TikTok не реализовано. Возвращаем оригинальный файл.")
    return video_path

# Создаём постоянную клавиатуру с кнопкой "Menu"
menu_keyboard = [[KeyboardButton("Menu")]]
menu_reply_markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    logger.info(f"Получена команда /start от пользователя {update.effective_user.id}")
    lang = get_user_language(update)
    await update.message.reply_text(t('start', lang), reply_markup=menu_reply_markup)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /menu"""
    logger.info(f"Получена команда /menu от пользователя {update.effective_user.id}")
    lang = get_user_language(update)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                inline_buttons_text['report_issue'][lang],
                url="https://t.me/d_shain"
            )
        ],
        [
            InlineKeyboardButton(
                inline_buttons_text['donate_author'][lang],
                url="https://buymeacoffee.com/shain_di"
            )
        ]
    ])
    await update.message.reply_text(t('menu', lang), reply_markup=keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    logger.info(f"Получено сообщение от пользователя {update.effective_user.id}: {update.message.text[:30]}...")
    lang = get_user_language(update)
    user_text = update.message.text.strip()

    # Если пользователь нажал кнопку "Menu"
    if user_text == "Menu":
        return await menu_command(update, context)

    # Проверяем ссылку
    supported_domains = [
        "tiktok.com", "linkedin.com", "facebook.com"
    ]
    # Добавляем особую проверку для Instagram Reels
    if "instagram.com" in user_text:
        # Убедимся, что в ссылке присутствует "reel"
        if "reel" not in user_text:
            await update.message.reply_text(t('not_supported', lang))
            return
        # Если есть "reel", считаем домен поддерживаемым
        supported_domains.append("instagram.com")

    # Если ссылка не содержит нужных доменов, отклоняем
    if not any(domain in user_text for domain in supported_domains):
        await update.message.reply_text(t('not_supported', lang))
        return
    
    is_tiktok = "tiktok.com" in user_text
    await update.message.reply_text(t('processing', lang))
    
    try:
        if is_tiktok:
            # Для TikTok используем альтернативный метод, который удаляет водяной знак
            try:
                video_path = download_tiktok_alternative(user_text)
                logger.info("Видео TikTok успешно скачано без водяного знака")
            except Exception as e:
                logger.error(f"Ошибка при скачивании TikTok без водяного знака: {e}")
                # Если альтернативный метод не сработал, пробуем стандартный
                video_path = download_video(user_text, is_tiktok=True)
                logger.info("Запуск процедуры удаления водяного знака для TikTok")
                video_path = remove_tiktok_watermark(video_path)
        else:
            # Для других платформ используем стандартный метод
            video_path = download_video(user_text, is_tiktok=False)
        
        # Создаём инлайн-кнопку "Поблагодарить автора" (локализованную)
        donate_text = inline_buttons_text['donate_author'][lang]
        video_reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(donate_text, url="https://buymeacoffee.com/shain_di")]
        ])

        with open(video_path, 'rb') as video_file:
            await update.message.reply_video(video=video_file, reply_markup=video_reply_markup)
        logger.info(f"Видео успешно отправлено пользователю {update.effective_user.id}")
        
        # Удаляем временный файл
        try:
            os.remove(video_path)
            logger.info(f"Временный файл удален: {video_path}")
        except Exception as e:
            logger.error(f"Не удалось удалить временный файл: {e}")
    except Exception as e:
        logger.error(f"Ошибка при обработке ссылки: {e}", exc_info=True)
        await update.message.reply_text(t('error', lang))

# Асинхронный обработчик обновлений
async def process_updates():
    """Обрабатывает обновления из очереди"""
    global application, updates_queue
    
    logger.info("Запущен обработчик обновлений")
    
    while True:
        try:
            # Получаем обновление из очереди
            update_data = await updates_queue.get()
            
            # Обрабатываем обновление
            update = Update.de_json(update_data, application.bot)
            await application.process_update(update)
            
            # Помечаем задачу как выполненную
            updates_queue.task_done()
        except Exception as e:
            logger.error(f"Ошибка при обработке обновления: {e}", exc_info=True)
        
        # Небольшая пауза, чтобы не загружать CPU
        await asyncio.sleep(0.1)

# Инициализация бота и запуск обработчика обновлений
async def setup_bot():
    """Инициализирует бота и запускает обработчик обновлений"""
    global application, event_loop
    
    logger.info("Инициализация приложения бота...")
    
    # Инициализируем приложение
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Инициализируем приложение
    await application.initialize()
    
    logger.info("Приложение бота инициализировано")
    
    # Запускаем обработчик обновлений
    asyncio.create_task(process_updates())
    
    logger.info("Обработчик обновлений запущен")

# Маршрут для домашней страницы
@app.route('/')
def home():
    return "Бот активен и работает!"

# Маршрут для проверки доступности
@app.route('/ping')
def ping():
    return "pong"

# Маршрут для обработки вебхуков от Telegram
@app.route(f'/webhook/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    """Обработчик вебхуков от Telegram"""
    global updates_queue, event_loop
    
    try:
        logger.info("Получен вебхук запрос")
        
        if request.headers.get('content-type') == 'application/json':
            update_data = request.json
            logger.info(f"Получены данные обновления: {update_data.get('update_id', 'unknown')}")
            
            # Добавляем обновление в очередь
            asyncio.run_coroutine_threadsafe(updates_queue.put(update_data), event_loop)
            
            return jsonify({"status": "success", "message": "Update queued for processing"})
        else:
            logger.warning(f"Получен запрос с неверным content-type: {request.headers.get('content-type')}")
            return jsonify({"status": "error", "message": "Invalid content type"})
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"Ошибка при обработке вебхука: {e}\n{error_traceback}")
        return jsonify({"status": "error", "message": str(e)})

# Маршрут для установки вебхука
@app.route('/set_webhook')
def set_webhook():
    """Устанавливает вебхук для бота"""
    # URL для вебхука с полным URL, включая https
    webhook_url = f"https://web-production-c09e9.up.railway.app/webhook/{TELEGRAM_BOT_TOKEN}"
    
    # Удаляем предыдущий вебхук
    delete_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
    requests.get(delete_url)
    
    # Устанавливаем новый вебхук
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    response = requests.post(api_url, json={'url': webhook_url})
    
    # Получаем информацию о вебхуке
    webhook_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo").json()
    
    return f"Вебхук установлен: {response.json()}<br>Информация о вебхуке: {webhook_info}"

# Маршрут для проверки статуса вебхука
@app.route('/webhook_status')
def webhook_status():
    """Проверяет статус вебхука"""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
    response = requests.get(api_url)
    
    return f"Статус вебхука: {response.json()}"

# Функция для запуска event loop
def run_event_loop():
    """Запускает и поддерживает event loop"""
    global event_loop
    
    # Создаем новый event loop
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    
    # Запускаем инициализацию бота
    event_loop.run_until_complete(setup_bot())
    
    # Запускаем event loop вечно
    try:
        event_loop.run_forever()
    except Exception as e:
        logger.error(f"Ошибка в event loop: {e}", exc_info=True)
    finally:
        event_loop.close()

# Получаем порт из переменных окружения
port = int(os.environ.get("PORT", 8080))

# Запускаем event loop в отдельном потоке
loop_thread = threading.Thread(target=run_event_loop, daemon=True)
loop_thread.start()

if __name__ == "__main__":
    # Запускаем Flask приложение
    app.run(host='0.0.0.0', port=port)

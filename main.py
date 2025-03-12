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

def download_tiktok_direct(url: str) -> str:
    """Скачивает видео из TikTok прямым методом через библиотеку requests."""
    import time
    import re
    import json
    import uuid
    
    logger.info(f"Попытка скачать TikTok видео прямым методом: {url}")
    
    try:
        # Шаг 1: Получение ID видео из URL
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.tiktok.com/',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
        
        # Обработка 'vm.tiktok.com' ссылок
        if 'vm.tiktok.com' in url:
            response = requests.get(url, headers=headers, allow_redirects=True)
            url = response.url
        
        # Получаем ID видео из URL
        video_id = None
        id_match = re.search(r'/video/(\d+)', url)
        if id_match:
            video_id = id_match.group(1)
        
        if not video_id:
            raise Exception("Не удалось извлечь ID видео из URL")
        
        logger.info(f"Извлечен ID видео: {video_id}")
        
        # Шаг 2: Попытка скачать через TikSave
        try:
            # Используем сервис TikSave
            tiksave_url = "https://tikwm.com/api/"
            data = {
                'url': url,
                'hd': 1
            }
            
            response = requests.post(tiksave_url, data=data, headers=headers)
            if response.status_code == 200:
                json_response = response.json()
                if json_response.get('code') == 0 and 'data' in json_response:
                    data = json_response['data']
                    if 'play' in data:
                        video_url = data['play']
                        logger.info(f"Получена ссылка на видео TikTok: {video_url}")
                        
                        # Скачиваем видео
                        video_response = requests.get(video_url, headers=headers, stream=True)
                        if video_response.status_code == 200:
                            temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                            with open(temp_path, 'wb') as f:
                                for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                                    if chunk:
                                        f.write(chunk)
                            logger.info(f"Видео TikTok успешно скачано: {temp_path}")
                            return temp_path
        except Exception as e:
            logger.warning(f"Не удалось скачать через TikSave: {e}")
        
        # Шаг 3: Попытка скачать через TikTok API
        try:
            # Формируем URL для скачивания
            tiktok_api_url = f"https://api22-normal-c-alisg.tiktokv.com/aweme/v1/feed/?aweme_id={video_id}"
            params = {
                "aweme_id": video_id,
                "version_name": "26.1.3",
                "version_code": "2613",
                "build_number": "26.1.3",
                "manifest_version_code": "2613",
                "update_version_code": "2613",
                "openudid": str(uuid.uuid4()),
                "uuid": str(uuid.uuid4()),
                "_rticket": str(int(time.time() * 1000)),
                "ts": str(int(time.time())),
                "device_brand": "Google",
                "device_type": "Pixel 4",
                "device_platform": "android",
                "resolution": "1080*1920",
                "dpi": "420",
                "os_version": "10",
                "os_api": "29",
                "carrier_region": "US",
                "sys_region": "US",
                "region": "US",
                "app_name": "trill",
                "app_language": "en",
                "language": "en",
                "timezone_name": "America/New_York",
                "timezone_offset": "-14400",
                "channel": "googleplay",
                "ac": "wifi",
                "mcc_mnc": "310260",
                "is_my_cn": "0",
                "aid": "1180",
                "ssmix": "a",
                "as": "a1qwert123",
                "cp": "cbfhckdckkde1"
            }
            
            response = requests.get(tiktok_api_url, params=params, headers=headers)
            
            if response.status_code == 200:
                json_data = response.json()
                
                if 'aweme_list' in json_data and len(json_data['aweme_list']) > 0:
                    video_data = json_data['aweme_list'][0]
                    
                    if 'video' in video_data and 'play_addr' in video_data['video']:
                        play_addr = video_data['video']['play_addr']
                        if 'url_list' in play_addr and len(play_addr['url_list']) > 0:
                            video_url = play_addr['url_list'][0]
                            
                            # Скачиваем видео
                            video_response = requests.get(video_url, headers=headers, stream=True)
                            if video_response.status_code == 200:
                                temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                                with open(temp_path, 'wb') as f:
                                    for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                                        if chunk:
                                            f.write(chunk)
                                logger.info(f"Видео TikTok успешно скачано через API: {temp_path}")
                                return temp_path
        except Exception as e:
            logger.warning(f"Не удалось скачать через TikTok API: {e}")
        
        # Шаг 4: Попытка скачать через LocoSave
        try:
            locosave_url = "https://www.locosave.com/api/ajaxSearch"
            data = {
                'url': url,
                'lang': 'en'
            }
            
            response = requests.post(locosave_url, data=data, headers=headers)
            if response.status_code == 200:
                json_data = response.json()
                
                if json_data.get('status') == 'ok' and 'data' in json_data:
                    if 'nwm_video_url' in json_data['data']:
                        video_url = json_data['data']['nwm_video_url']
                    elif 'video_url' in json_data['data']:
                        video_url = json_data['data']['video_url']
                    
                    if video_url:
                        # Скачиваем видео
                        video_response = requests.get(video_url, headers=headers, stream=True)
                        if video_response.status_code == 200:
                            temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                            with open(temp_path, 'wb') as f:
                                for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                                    if chunk:
                                        f.write(chunk)
                            logger.info(f"Видео TikTok успешно скачано через LocoSave: {temp_path}")
                            return temp_path
        except Exception as e:
            logger.warning(f"Не удалось скачать через LocoSave: {e}")
            
        # Шаг 5: Использование SaveFromWeb
        try:
            # Новый метод через SaveFrom.net
            savefrom_url = "https://worker.sf-tools.com/savefrom.php"
            payload = {
                'sf_url': url,
                'sf_submit': '',
                'new': 1,
                'lang': 'ru',
                'app': '',
                'country': 'ru',
                'os': 'Windows',
                'browser': 'Chrome',
                'channel': 'main',
                'sf-nomad': 1
            }
            
            headers['Origin'] = 'https://savefrom.net'
            headers['Referer'] = 'https://savefrom.net/'
            
            response = requests.post(savefrom_url, data=payload, headers=headers)
            if response.status_code == 200:
                json_data = json.loads(response.text)
                
                if isinstance(json_data, list) and len(json_data) > 0:
                    for item in json_data:
                        if 'url' in item and item.get('type') == 'mp4':
                            video_url = item['url']
                            quality = item.get('quality', '')
                            logger.info(f"Найдена ссылка на видео качества {quality}: {video_url}")
                            
                            # Скачиваем видео
                            video_response = requests.get(video_url, headers=headers, stream=True)
                            if video_response.status_code == 200:
                                temp_path = os.path.join("/tmp", f"tiktok_{int(time.time())}.mp4")
                                with open(temp_path, 'wb') as f:
                                    for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                                        if chunk:
                                            f.write(chunk)
                                logger.info(f"Видео TikTok успешно скачано через SaveFrom: {temp_path}")
                                return temp_path
                            break
        except Exception as e:
            logger.warning(f"Не удалось скачать через SaveFrom: {e}")
        
        raise Exception("Не удалось скачать видео TikTok ни одним из методов")
        
    except Exception as e:
        logger.error(f"Ошибка при прямом скачивании видео TikTok: {e}")
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
            # Для TikTok используем несколько методов в порядке приоритета
            try:
                # Сначала попробуем прямой метод
                video_path = download_tiktok_direct(user_text)
                logger.info("Видео TikTok успешно скачано прямым методом")
            except Exception as e:
                logger.error(f"Ошибка при прямом скачивании TikTok: {e}")
                try:
                    # Если не сработал прямой метод, пробуем альтернативный
                    video_path = download_tiktok_alternative(user_text)
                    logger.info("Видео TikTok успешно скачано альтернативным методом")
                except Exception as e2:
                    logger.error(f"Ошибка при альтернативном скачивании TikTok: {e2}")
                    # Если и это не сработало, пробуем стандартный метод

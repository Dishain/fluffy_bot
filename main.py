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
                    video_path = download_video(user_text, is_tiktok=True)
                    logger.info("Видео TikTok успешно скачано стандартным методом")
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

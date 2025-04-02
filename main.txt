# main.py
from flask import Flask, request
import telegram
from telegram.ext import Dispatcher
import logging
import threading
from database import init_db
from utils import auto_clean_database, clean_globals, daily_reminder
from handlers import get_handlers
from config import TOKEN, WEBHOOK_URL

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicialización de Flask y Telegram
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=0)

# Registrar handlers
for handler in get_handlers():
    dispatcher.add_handler(handler)

# Inicializar la base de datos
init_db()

# Iniciar tareas automáticas
threading.Thread(target=auto_clean_database, daemon=True).start()
threading.Thread(target=clean_globals, daemon=True).start()
threading.Thread(target=daily_reminder, args=(bot,), daemon=True).start()

# Configurar el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return '', 200

@app.route('/')
def index():
    return 'Bot is running!'

if __name__ == '__main__':
    bot.set_webhook(WEBHOOK_URL)
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
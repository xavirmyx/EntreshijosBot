from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler
from datetime import datetime
import pytz

# Configura tu token aquí
TOKEN = '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY'  # Token de tu bot
GROUP_DESTINO = '-1002641818457'  # ID del grupo destino

# Configura la URL del webhook (ajusta esta URL según la que te dé Replit al correr el proyecto)
WEBHOOK_URL = 'https://cac6e97c-cf96-418f-910d-801c340f9200-1fa26n9bvzsgx.janeway.replit.dev/webhook'

# Inicializa el bot y Flask
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Configura el Dispatcher
dispatcher = Dispatcher(bot, None, workers=1)  # Usa al menos 1 worker

# Función para manejar mensajes
def handle_message(update, context):
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'

    # Obtiene la fecha y hora en formato local
    timestamp = datetime.now(pytz.timezone('UTC')).strftime('%d/%m/%Y %H:%M:%S')

    # Verifica si el mensaje contiene #solicito o /solicito
    if '#solicito' in message_text.lower() or message_text.lower().startswith('/solicito'):
        # Mensaje para el grupo destino
        destino_message = (
            "📬 **Nueva solicitud recibida**  \n"
            f"👤 **Usuario:** {username} (ID: {user_id})  \n"
            f"📝 **Mensaje:** {message_text}  \n"
            f"🏠 **Grupo:** {chat_title}  \n"
            f"🕒 **Fecha y hora:** {timestamp}  \n"
            "🌟 **Bot de Entreshijos**"
        )
        bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')

        # Mensaje de confirmación al usuario
        confirmacion_message = (
            "✅ **¡Solicitud enviada con éxito!**  \n"
            f"Hola {username}, tu solicitud ha sido registrada y enviada al equipo de Entreshijos. 📩  \n"
            "Pronto recibirás una respuesta. ¡Gracias por confiar en nosotros! 🙌  \n"
            f"🕒 **Fecha y hora:** {timestamp}  \n"
            "🌟 **Bot de Entreshijos**"
        )
        bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')

# Añade el handler para mensajes
message_handler = MessageHandler(Filters.text & ~Filters.command, handle_message)
dispatcher.add_handler(message_handler)

# Ruta para el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok', 200

# Ruta para configurar el webhook
@app.route('/')
def set_webhook():
    bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
    return "Webhook set!", 200

if __name__ == '__main__':
    # Inicia el servidor Flask
    app.run(host='0.0.0.0', port=5000)
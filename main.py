from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters
from datetime import datetime
import pytz
import os

# Configura tu token, grupo y URL del webhook usando variables de entorno
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')

# Inicializa el bot y Flask
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Configura el Dispatcher con al menos 1 worker
dispatcher = Dispatcher(bot, None, workers=1)

# Función para manejar mensajes con #solicito, /solicito o #peticion
def handle_message(update, context):
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'

    # Obtiene la fecha y hora en formato local
    timestamp = datetime.now(pytz.timezone('UTC')).strftime('%d/%m/%Y %H:%M:%S')

    # Verifica si el mensaje contiene #solicito, /solicito o #peticion
    if any(cmd in message_text.lower() for cmd in ['#solicito', '/solicito', '#peticion']):
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
            f"👤 **ID:** {user_id}  \n"
            f"🏠 **Grupo:** {chat_title}  \n"
            f"🕒 **Fecha y hora:** {timestamp}  \n"
            f"📝 **Mensaje de la petición:** {message_text}  \n"
            "¡Gracias por confiar en nosotros! 🙌  \n"
            "🌟 **Bot de Entreshijos**"
        )
        bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')

# Añade el handler para mensajes
message_handler = MessageHandler(Filters.text & ~Filters.command, handle_message)
dispatcher.add_handler(message_handler)

# Ruta para el webhook con token dinámico
@app.route('/webhook/<path:token>', methods=['POST'])
def webhook(token):
    if token != TOKEN:
        return 'Invalid token', 403
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok', 200

# Ruta raíz (para verificar que el servidor está vivo)
@app.route('/')
def health_check():
    return "Bot de Entreshijos está activo!", 200

if __name__ == '__main__':
    # Para desarrollo local, usa el puerto 5000
    app.run(host='0.0.0.0', port=5000)
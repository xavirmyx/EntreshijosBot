from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters
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

# Configura el Dispatcher con al least 1 worker
dispatcher = Dispatcher(bot, None, workers=1)

# Diccionario para almacenar las peticiones en memoria (se reinicia con cada reinicio del bot)
peticiones_por_usuario = {}  # Formato: {user_id: {"count": X, "chat_id": Y, "username": Z, "message_text": W}}
ultima_peticion_por_usuario = {}  # Formato: {username: {"chat_id": X, "message_text": Y, "message_id": Z}}

# Función para escapar caracteres especiales en Markdown
def escape_markdown(text):
    if not text:
        return text
    characters_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in characters_to_escape:
        text = text.replace(char, f'\\{char}')
    return text

# Función para manejar mensajes con #solicito, /solicito, #peticion o /peticion
def handle_message(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'

    # Obtiene la fecha y hora en formato local
    timestamp = datetime.now(pytz.timezone('UTC')).strftime('%d/%m/%Y %H:%M:%S')

    # Escapa caracteres especiales para Markdown
    username_escaped = escape_markdown(username)
    message_text_escaped = escape_markdown(message_text)
    chat_title_escaped = escape_markdown(chat_title)

    # Verifica si el mensaje contiene #solicito, /solicito, #peticion o /peticion
    if any(cmd in message_text.lower() for cmd in ['#solicito', '/solicito', '#peticion', '/peticion']):
        # Verifica el límite de 2 peticiones por usuario
        if user_id not in peticiones_por_usuario:
            peticiones_por_usuario[user_id] = {"count": 0, "chat_id": chat_id, "username": username}

        # Incrementa el conteo de peticiones
        peticiones_por_usuario[user_id]["count"] += 1

        # Si excede el límite, notifica y activa GroupHelp
        if peticiones_por_usuario[user_id]["count"] > 2:
            limite_message = (
                f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta de nuevo más tarde. 🌟"
            )
            bot.send_message(chat_id=chat_id, text=limite_message)

            # Activa GroupHelp para el /warn
            warn_message = f"@GroupHelpBot /warn {username_escaped} Abuso de peticiones diarias"
            bot.send_message(chat_id=chat_id, text=warn_message)
            return

        # Mensaje para el grupo destino
        destino_message = (
            "📬 **Nueva solicitud recibida**  \n"
            f"👤 **Usuario:** {username_escaped} (ID: {user_id})  \n"
            f"📝 **Mensaje:** {message_text_escaped}  \n"
            f"🏠 **Grupo:** {chat_title_escaped}  \n"
            f"🕒 **Fecha y hora:** {timestamp}  \n"
            "🌟 **Bot de Entreshijos**"
        )
        try:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
            # Almacena información para eliminar después
            ultima_peticion_por_usuario[username] = {
                "chat_id": chat_id,
                "message_text": message_text,
                "message_id": sent_message.message_id
            }
        except telegram.error.BadRequest as e:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode=None)
            ultima_peticion_por_usuario[username] = {
                "chat_id": chat_id,
                "message_text": message_text,
                "message_id": sent_message.message_id
            }

        # Mensaje de confirmación al usuario
        confirmacion_message = (
            "✅ **¡Solicitud enviada con éxito!**  \n"
            f"Hola {username_escaped}, tu solicitud ha sido registrada y enviada al equipo de Entreshijos. 📩  \n"
            f"👤 **ID:** {user_id}  \n"
            f"🏠 **Grupo:** {chat_title_escaped}  \n"
            f"🕒 **Fecha y hora:** {timestamp}  \n"
            f"📝 **Mensaje de la petición:** {message_text_escaped}  \n"
            "¡Gracias por confiar en nosotros! 🙌  \n"
            "🌟 **Bot de Entreshijos**"
        )
        try:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')
        except telegram.error.BadRequest as e:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode=None)

# Función para manejar el comando /eliminar [@name] [estado]
def handle_eliminar(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id

    # Solo permitir este comando en el grupo destino
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="Este comando solo puede usarse en el grupo destino. 🌟")
        return

    # Obtiene los argumentos del comando
    args = context.args
    if len(args) < 1:
        bot.send_message(chat_id=chat_id, text="Uso: /eliminar [@username] [aprobada/denegada]. Ejemplo: /eliminar @Juan aprobada 🌟")
        return

    username = args[0]
    estado = args[1].lower() if len(args) > 1 else None

    # Verifica si el username está en las peticiones recientes
    if username not in ultima_peticion_por_usuario:
        bot.send_message(chat_id=chat_id, text=f"No se encontró una solicitud reciente de {username}. 🌟")
        return

    # Obtiene la información almacenada
    user_info = ultima_peticion_por_usuario[username]
    user_chat_id = user_info["chat_id"]
    message_text = user_info["message_text"]
    message_id = user_info["message_id"]

    # Escapa caracteres para Markdown
    username_escaped = escape_markdown(username)
    message_text_escaped = escape_markdown(message_text)

    # Elimina el mensaje del grupo destino
    try:
        bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
        bot.send_message(chat_id=chat_id, text=f"✅ Solicitud de {username_escaped} eliminada ({estado if estado else 'sin estado'}).")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"No se pudo eliminar el mensaje: {e}. Notificando al usuario de todos modos. 🌟")

    # Notifica al usuario según el estado
    if estado == "aprobada":
        notificacion = (
            f"✅ Tu solicitud \"{message_text_escaped}\" ha sido aprobada. ¡Gracias por tu paciencia! 🌟"
        )
    elif estado == "denegada":
        notificacion = (
            f"❌ Tu solicitud \"{message_text_escaped}\" ha sido denegada. Si tienes dudas, contacta a un administrador. 🌟"
        )
    else:
        notificacion = (
            f"ℹ️ Tu solicitud \"{message_text_escaped}\" ha sido eliminada. 🌟"
        )

    try:
        bot.send_message(chat_id=user_chat_id, text=notificacion)
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"No se pudo notificar al usuario {username_escaped}: {e}. 🌟")

    # Elimina la información del usuario del diccionario
    del ultima_peticion_por_usuario[username]

# Añade los handlers
message_handler = MessageHandler(Filters.text & ~Filters.command, handle_message)
dispatcher.add_handler(message_handler)

eliminar_handler = CommandHandler('eliminar', handle_eliminar)
dispatcher.add_handler(eliminar_handler)

# Ruta para el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
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
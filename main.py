from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters
from datetime import datetime
import pytz
import os
import random

# Configura tu token, grupo y URL del webhook usando variables de entorno
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')

# Inicializa el bot y Flask
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Configura el Dispatcher con al menos 1 worker
dispatcher = Dispatcher(bot, None, workers=1)

# Diccionarios para almacenamiento en memoria
ticket_counter = 150  # Comienza en 150
peticiones_por_usuario = {}  # {user_id: {"count": X, "chat_id": Y, "username": Z}}
peticiones_registradas = {}  # {ticket_number: {"chat_id": X, "username": Y, "message_text": Z, "message_id": W, "timestamp": T}}
admin_ids = set([12345678])  # Lista de IDs de administradores (cámbialos según necesites)
aceptar_solicitudes = True  # Controla si se aceptan solicitudes
grupos_activos = set()  # Almacena los chat_ids de los grupos donde está el bot

# Frases de agradecimiento aleatorias
frases_agradecimiento = [
    "¡Gracias por tu paciencia! 🙌",
    "¡Agradecemos tu confianza! 💖",
    "¡Tu apoyo es valioso! 🌟",
    "¡Gracias por usar el bot! 🎉"
]

# Sticker IDs (puedes reemplazarlos con los tuyos)
STICKER_OFF = "CAACAgUAAxkBAAEBzIZjG5r6c4n9Xv7bK7XwG2g5i1jVAAL_AQACZQcYSrZ2q2s3T0sZHgQ"
STICKER_ON = "CAACAgUAAxkBAAEBzIdjG5r8wU0fQ6zU5H8Xg3O5cK9xAAL_AQACZQcYSvN8XhR0jW0ZHgQ"

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

    # Registra el grupo activo
    grupos_activos.add(chat_id)

    # Obtiene la fecha y hora en formato local
    timestamp = datetime.now(pytz.timezone('UTC')).strftime('%d/%m/%Y %H:%M:%S')

    # Escapa caracteres especiales para Markdown
    username_escaped = escape_markdown(username)
    message_text_escaped = escape_markdown(message_text)
    chat_title_escaped = escape_markdown(chat_title)

    # Verifica si el mensaje contiene #solicito, /solicito, #peticion o /peticion
    if any(cmd in message_text.lower() for cmd in ['#solicito', '/solicito', '#peticion', '/peticion']):
        if not aceptar_solicitudes and user_id not in admin_ids:
            notificacion = (
                f"🚫 {username_escaped}, de momento no se aceptan solicitudes. Equipo de administración. 🌟"
            )
            bot.send_message(chat_id=chat_id, text=notificacion)
            return

        # Excepción para administradores
        if user_id in admin_ids:
            pass  # Los administradores no tienen límite
        else:
            # Verifica el límite de 2 peticiones por usuario
            if user_id not in peticiones_por_usuario:
                peticiones_por_usuario[user_id] = {"count": 0, "chat_id": chat_id, "username": username}
            peticiones_por_usuario[user_id]["count"] += 1

            # Si excede el límite, notifica y activa GroupHelp
            if peticiones_por_usuario[user_id]["count"] > 2:
                limite_message = (
                    f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta de nuevo mañana. 🌟"
                )
                bot.send_message(chat_id=chat_id, text=limite_message)
                warn_message = f"@GroupHelpBot /warn {username_escaped} Peticiones diarias superadas"
                bot.send_message(chat_id=chat_id, text=warn_message)
                return

        # Incrementa el contador de tickets global
        global ticket_counter
        ticket_counter += 1
        ticket_number = ticket_counter

        # Mensaje para el grupo destino
        peticion_count = peticiones_por_usuario[user_id]["count"]
        destino_message = (
            "📬 Nueva solicitud recibida  \n"
            f"👤 Usuario: {username_escaped} (ID: {user_id})  \n"
            f"     ticket Número - {ticket_number}  \n"
            f"     Petición {peticion_count}/2  \n"
            f"📝 Mensaje: {message_text_escaped}  \n"
            f"🏠 Grupo: {chat_title_escaped}  \n"
            f"🕒 Fecha y hora: {timestamp}  \n"
            "🌟 Bot de Entreshijos"
        )
        try:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
            # Almacena información con timestamp
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": datetime.now(pytz.timezone('UTC'))
            }
        except telegram.error.BadRequest as e:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode=None)
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": datetime.now(pytz.timezone('UTC'))
            }

        # Mensaje de confirmación al usuario
        agradecimiento = random.choice(frases_agradecimiento)
        confirmacion_message = (
            "✅ ¡Solicitud enviada con éxito! 🎉  \n"
            f"Hola {username_escaped}, tu solicitud ha sido registrada con ticket #{ticket_number}. 📩  \n"
            f"👤 ID: {user_id}  \n"
            f"🏠 Grupo: {chat_title_escaped}  \n"
            f"🕒 Fecha y hora: {timestamp}  \n"
            f"📝 Mensaje: {message_text_escaped}  \n"
            f"{agradecimiento}  \n"
            "🌟 Bot de Entreshijos"
        )
        try:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')
            bot.send_sticker(chat_id=chat_id, sticker=STICKER_ON)  # Sticker de confirmación
        except telegram.error.BadRequest as e:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode=None)

# Función para manejar el comando /eliminar [ticket] [estado]
def handle_eliminar(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id

    # Solo permitir este comando en el grupo destino
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        return

    # Obtiene los argumentos del comando
    args = context.args
    if len(args) < 2:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /eliminar [ticket] [aprobada/denegada/eliminada]. Ejemplo: /eliminar 150 aprobada 🌟")
        return

    try:
        ticket_number = int(args[0])
        estado = args[1].lower()
    except (ValueError, IndexError):
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número válido. Ejemplo: /eliminar 150 aprobada 🌟")
        return

    # Verifica si el ticket existe
    if ticket_number not in peticiones_registradas:
        bot.send_message(chat_id=chat_id, text=f"❌ No se encontró una solicitud con ticket #{ticket_number}. 🌟")
        return

    # Obtiene la información almacenada
    peticion_info = peticiones_registradas[ticket_number]
    user_chat_id = peticion_info["chat_id"]
    username = peticion_info["username"]
    message_text = peticion_info["message_text"]
    message_id = peticion_info["message_id"]

    # Escapa caracteres para Markdown
    username_escaped = escape_markdown(username)
    message_text_escaped = escape_markdown(message_text)

    # Elimina el mensaje del grupo destino
    try:
        bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
        bot.send_message(chat_id=chat_id, text=f"✅ Solicitud con ticket #{ticket_number} de {username_escaped} eliminada ({estado}). 🌟")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {e}. Notificando de todos modos. 🌟")

    # Notifica al usuario en su grupo
    if estado == "aprobada":
        notificacion = (
            f"✅ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text_escaped}\" ha sido aprobada. ¡Gracias! 🎉"
        )
    elif estado == "denegada":
        notificacion = (
            f"❌ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text_escaped}\" ha sido denegada. Contacta a un administrador si tienes dudas. 🌟"
        )
    elif estado == "eliminada":
        notificacion = (
            f"ℹ️ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text_escaped}\" ha sido eliminada. 🌟"
        )
    else:
        notificacion = (
            f"ℹ️ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text_escaped}\" ha sido eliminada. 🌟"
        )

    try:
        bot.send_message(chat_id=user_chat_id, text=notificacion)
        bot.send_sticker(chat_id=user_chat_id, sticker=STICKER_ON)  # Sticker de confirmación
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo notificar a {username_escaped}: {e}. 🌟")

    # Elimina la información del diccionario
    del peticiones_registradas[ticket_number]

# Función para manejar el comando /pendientes (solo para administradores)
def handle_pendientes(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    # Solo permitir este comando en el grupo destino y para administradores
    if str(chat_id) != GROUP_DESTINO or user_id not in admin_ids:
        return

    pendientes = [f"{i}. Ticket #{k} - {v['username']}: \"{escape_markdown(v['message_text'])}\" (Grupo: {escape_markdown(v.get('chat_title', 'Desconocido'))})" 
                  for k, v in peticiones_registradas.items()]
    if not pendientes:
        respuesta = "📋 No hay solicitudes pendientes. 🌟"
    else:
        respuesta = "📋 Solicitudes pendientes 🌟\n" + "\n".join(pendientes) + f"\nTotal: {len(pendientes)} pendientes ⏳"
    try:
        bot.send_message(chat_id=chat_id, text=respuesta, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        bot.send_message(chat_id=chat_id, text=respuesta, parse_mode=None)

# Función para manejar el comando /ayuda
def handle_ayuda(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario"

    ayuda_message = (
        "📖 Guía de EntreshijosBot 🌟\n"
        "Usa /solicito, #solicito, /peticion o #peticion para enviar solicitudes (máx. 2 por día).\n"
        "📋 Consulta el estado con /estado [ticket].\n"
        "❓ Escribe /ayuda para esta guía.\n"
        f"¡Gracias {username} por usar el bot! 🙌"
    )
    try:
        bot.send_message(chat_id=chat_id, text=ayuda_message, parse_mode='Markdown')
        bot.send_sticker(chat_id=chat_id, sticker=STICKER_ON)  # Sticker de ayuda
    except telegram.error.BadRequest as e:
        bot.send_message(chat_id=chat_id, text=ayuda_message, parse_mode=None)

# Función para manejar el comando /estado
def handle_estado(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario"
    args = context.args

    if not args:
        bot.send_message(chat_id=chat_id, text="❗ Usa: /estado [ticket]. Ejemplo: /estado 150 🌟")
        return

    try:
        ticket_number = int(args[0])
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número válido. Ejemplo: /estado 150 🌟")
        return

    if ticket_number in peticiones_registradas:
        peticion_info = peticiones_registradas[ticket_number]
        timestamp = peticion_info["timestamp"].strftime('%d/%m/%Y %H:%M:%S')
        estado_message = (
            f"📋 Estado de tu solicitud, {username} 🌟\n"
            f"Ticket #{ticket_number}: \"{escape_markdown(peticion_info['message_text'])}\"\n"
            f"Estado: Pendiente ⏳\n"
            f"🕒 Enviada: {timestamp}"
        )
    else:
        estado_message = (
            f"📋 Estado de tu solicitud, {username} 🌟\n"
            f"Ticket #{ticket_number}: Ya fue gestionada (aprobada, denegada o eliminada). ✅"
        )
    try:
        bot.send_message(chat_id=chat_id, text=estado_message, parse_mode='Markdown')
        bot.send_sticker(chat_id=chat_id, sticker=STICKER_ON)  # Sticker de estado
    except telegram.error.BadRequest as e:
        bot.send_message(chat_id=chat_id, text=estado_message, parse_mode=None)

# Función para manejar el comando /off (solo para administradores)
def handle_off(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    # Solo permitir este comando para administradores
    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Solo administradores pueden usar este comando. 🌟")
        return

    global aceptar_solicitudes
    aceptar_solicitudes = False

    # Notificación a todos los grupos
    off_message = (
        "🚫 ¡Atención usuarios! 🌟\n"
        "De momento no se aceptan solicitudes hasta nuevo aviso. Equipo de administración.\n"
        "Disculpen las molestias. 🙏"
    )
    for grupo in grupos_activos:
        try:
            bot.send_message(chat_id=grupo, text=off_message)
            bot.send_sticker(chat_id=grupo, sticker=STICKER_OFF)  # Sticker de pausa
        except telegram.error.TelegramError as e:
            continue

    bot.send_message(chat_id=chat_id, text="🔴 Bot desactivado para nuevas solicitudes. 🌟")

# Función para manejar el comando /on (solo para administradores)
def handle_on(update, context):
    if not update.message:  # Verifica que update.message no sea None
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    # Solo permitir este comando para administradores
    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Solo administradores pueden usar este comando. 🌟")
        return

    global aceptar_solicitudes
    aceptar_solicitudes = True

    # Notificación a todos los grupos
    on_message = (
        "🎉 ¡Buenas noticias! 🌟\n"
        "Ya se pueden enviar solicitudes con /solicito, #solicito, /peticion o #peticion.\n"
        "Máximo 2 por día por usuario cada 24 horas. Equipo de Entreshijos. 🙌"
    )
    for grupo in grupos_activos:
        try:
            bot.send_message(chat_id=grupo, text=on_message)
            bot.send_sticker(chat_id=grupo, sticker=STICKER_ON)  # Sticker de reactivación
        except telegram.error.TelegramError as e:
            continue

    bot.send_message(chat_id=chat_id, text="🟢 Bot reactivado para recibir solicitudes. 🌟")

# Añade los handlers
message_handler = MessageHandler(Filters.text & ~Filters.command, handle_message)
dispatcher.add_handler(message_handler)

eliminar_handler = CommandHandler('eliminar', handle_eliminar)
dispatcher.add_handler(eliminar_handler)

pendientes_handler = CommandHandler('pendientes', handle_pendientes)
dispatcher.add_handler(pendientes_handler)

ayuda_handler = CommandHandler('ayuda', handle_ayuda)
dispatcher.add_handler(ayuda_handler)

estado_handler = CommandHandler('estado', handle_estado)
dispatcher.add_handler(estado_handler)

off_handler = CommandHandler('off', handle_off)
dispatcher.add_handler(off_handler)

on_handler = CommandHandler('on', handle_on)
dispatcher.add_handler(on_handler)

# Ruta para el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok', 200

# Ruta raíz (para verificar que el servidor está vivo)
@app.route('/')
def health_check():
    return "Bot de Entreshijos está activo! 🌟", 200

if __name__ == '__main__':
    # Para desarrollo local, usa el puerto 5000
    app.run(host='0.0.0.0', port=5000)
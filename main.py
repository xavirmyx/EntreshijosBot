from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters
from datetime import datetime
import pytz
import os
import random
import logging

# Configura tu token, grupo y URL del webhook usando variables de entorno
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')

# Configura el logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicializa el bot y Flask
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Configura el Dispatcher con al menos 1 worker
dispatcher = Dispatcher(bot, None, workers=1)

# Diccionarios para almacenamiento en memoria
ticket_counter = 150  # Comienza en 150
peticiones_por_usuario = {}  # {user_id: {"count": X, "chat_id": Y, "username": Z}}
peticiones_registradas = {}  # {ticket_number: {"chat_id": X, "username": Y, "message_text": Z, "message_id": W, "timestamp": T}}
procesado = {}  # Flag para evitar duplicación de mensajes (update_id: True)
admin_ids = set([12345678])  # Lista de IDs de administradores
aceptar_solicitudes = True  # Controla si se aceptan solicitudes
grupos_activos = set()  # Almacena los chat_ids de los grupos donde está el bot

# Frases de agradecimiento aleatorias
frases_agradecimiento = [
    "¡Gracias por tu paciencia! 🙌",
    "¡Agradecemos tu confianza! 💖",
    "¡Tu apoyo es valioso! 🌟",
    "¡Gracias por usar el bot! 🎉"
]

# Función para escapar caracteres especiales en Markdown, pero preservando @name
def escape_markdown(text, preserve_username=False):
    if not text:
        return text
    if preserve_username and text.startswith('@'):
        return text  # No escapamos el @name
    characters_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in characters_to_escape:
        text = text.replace(char, f'\\{char}')
    return text

# Función para manejar mensajes con #solicito, /solicito, #peticion o /peticion
def handle_message(update, context):
    if not update.message:
        logger.warning("Mensaje recibido es None")
        return

    update_id = update.update_id
    if update_id in procesado:
        logger.info(f"Duplicación detectada, actualización {update_id} ya procesada")
        return
    procesado[update_id] = True

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'

    grupos_activos.add(chat_id)
    logger.info(f"Grupo activo registrado: {chat_id}")

    timestamp = datetime.now(pytz.timezone('UTC')).strftime('%d/%m/%Y %H:%M:%S')
    username_escaped = escape_markdown(username, preserve_username=True)
    message_text_escaped = escape_markdown(message_text)
    chat_title_escaped = escape_markdown(chat_title)

    if any(cmd in message_text.lower() for cmd in ['#solicito', '/solicito', '#peticion', '/peticion']):
        logger.info(f"Solicitud recibida de {username} en {chat_title}: {message_text}")
        if not aceptar_solicitudes:
            notificacion = (
                f"🚫 {username_escaped}, de momento no se aceptan solicitudes. Equipo de administración. 🌟"
            )
            bot.send_message(chat_id=chat_id, text=notificacion)
            logger.info(f"Solicitudes desactivadas, notificado a {username}")
            return

        if user_id in admin_ids:
            pass
        else:
            if user_id not in peticiones_por_usuario:
                peticiones_por_usuario[user_id] = {"count": 0, "chat_id": chat_id, "username": username}
            peticiones_por_usuario[user_id]["count"] += 1

            if peticiones_por_usuario[user_id]["count"] > 2:
                limite_message = (
                    f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta de nuevo mañana. 🌟"
                )
                bot.send_message(chat_id=chat_id, text=limite_message)
                warn_message = f"/warn {username_escaped} Limite de peticiones diarias superadas"
                bot.send_message(chat_id=chat_id, text=warn_message)
                logger.info(f"Límite excedido por {username}, advertencia enviada: {warn_message}")
                return

        global ticket_counter
        ticket_counter += 1
        ticket_number = ticket_counter

        destino_message = (
            "📬 Nueva solicitud recibida  \n"
            f"👤 Usuario: {username_escaped} (ID: {user_id})  \n"
            f"     ticket Número - {ticket_number}  \n"
            f"     Petición {peticiones_por_usuario[user_id]['count']}/2  \n"
            f"📝 Mensaje: {message_text}  \n"  # Texto plano
            f"🏠 Grupo: {chat_title_escaped}  \n"
            f"🕒 Fecha y hora: {timestamp}  \n"
            "🌟 Bot de Entreshijos"
        )
        try:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": datetime.now(pytz.timezone('UTC')),
                "chat_title": chat_title
            }
            logger.info(f"Solicitud #{ticket_number} enviada al grupo destino")
        except telegram.error.BadRequest as e:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message.replace('*', '').replace('**', ''))
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": datetime.now(pytz.timezone('UTC')),
                "chat_title": chat_title
            }
            logger.error(f"Error al enviar al grupo destino con Markdown: {str(e)}")

        confirmacion_message = (
            "✅ ¡Solicitud enviada con éxito! 🎉  \n"
            f"Hola {username_escaped}, tu solicitud ha sido registrada con ticket #{ticket_number}. 📩  \n"
            f"👤 ID: {user_id}  \n"
            f"🏠 Grupo: {chat_title}  \n"  # Texto plano
            f"🕒 Fecha y hora: {timestamp}  \n"
            f"📝 Mensaje: {message_text}  \n"  # Texto plano
            f"{random.choice(frases_agradecimiento)}  \n"
            "🌟 Bot de Entreshijos"
        )
        try:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')
            logger.info(f"Confirmación enviada a {username} en {chat_id}")
        except telegram.error.BadRequest as e:
            bot.send_message(chat_id=chat_id, text=confirmacion_message.replace('*', '').replace('**', ''))
            logger.error(f"Error al enviar confirmación con Markdown: {str(e)}")

# Función para manejar el comando /eliminar [ticket] [estado]
def handle_eliminar(update, context):
    if not update.message:
        logger.warning("Mensaje /eliminar recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /eliminar fuera del grupo destino: {chat_id}")
        return

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

    if ticket_number not in peticiones_registradas:
        bot.send_message(chat_id=chat_id, text=f"❌ No se encontró una solicitud con ticket #{ticket_number}. 🌟")
        logger.info(f"Ticket #{ticket_number} no encontrado para /eliminar")
        return

    peticion_info = peticiones_registradas[ticket_number]
    user_chat_id = peticion_info["chat_id"]
    username = peticion_info["username"]
    message_text = peticion_info["message_text"]
    message_id = peticion_info["message_id"]

    username_escaped = escape_markdown(username, preserve_username=True)
    message_text_escaped = escape_markdown(message_text)

    try:
        bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
        bot.send_message(chat_id=chat_id, text=f"✅ Solicitud con ticket #{ticket_number} de {username_escaped} eliminada ({estado}). 🌟")
        logger.info(f"Solicitud #{ticket_number} eliminada del grupo destino")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos. 🌟")
        logger.error(f"Error al eliminar mensaje #{ticket_number}: {str(e)}")

    if estado == "aprobada":
        notificacion = (
            f"✅ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text}\" ha sido aprobada. ¡Gracias! 🎉"
        )
    elif estado == "denegada":
        notificacion = (
            f"❌ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text}\" ha sido denegada. Contacta a un administrador si tienes dudas. 🌟"
        )
    elif estado == "eliminada":
        notificacion = (
            f"ℹ️ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text}\" ha sido eliminada. 🌟"
        )
    else:
        notificacion = (
            f"ℹ️ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text}\" ha sido eliminada. 🌟"
        )

    try:
        bot.send_message(chat_id=user_chat_id, text=notificacion)
        logger.info(f"Notificación de /eliminar enviada a {username} en {user_chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo notificar a {username_escaped}: {str(e)}. 🌟")
        logger.error(f"Error al notificar a {username_escaped}: {str(e)}")

    del peticiones_registradas[ticket_number]

# Función para manejar el comando /subido [ticket]
def handle_subido(update, context):
    if not update.message:
        logger.warning("Mensaje /subido recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /subido fuera del grupo destino: {chat_id}")
        return

    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /subido [ticket]. Ejemplo: /subido 150 🌟")
        return

    try:
        ticket_number = int(args[0])
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número válido. Ejemplo: /subido 150 🌟")
        return

    if ticket_number not in peticiones_registradas:
        bot.send_message(chat_id=chat_id, text=f"❌ No se encontró una solicitud con ticket #{ticket_number}. 🌟")
        logger.info(f"Ticket #{ticket_number} no encontrado para /subido")
        return

    peticion_info = peticiones_registradas[ticket_number]
    user_chat_id = peticion_info["chat_id"]
    username = peticion_info["username"]
    message_text = peticion_info["message_text"]

    username_escaped = escape_markdown(username, preserve_username=True)

    notificacion = (
        f"✅ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text}\" ha sido subida. ¡Gracias! 🎉"
    )
    try:
        bot.send_message(chat_id=user_chat_id, text=notificacion)
        bot.send_message(chat_id=chat_id, text=f"✅ Solicitud con ticket #{ticket_number} de {username_escaped} marcada como subida. 🌟")
        logger.info(f"Notificación de /subido enviada a {username} en {user_chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo notificar a {username_escaped}: {str(e)}. 🌟")
        logger.error(f"Error al notificar a {username_escaped}: {str(e)}")

# Función para manejar el comando /denegado [ticket]
def handle_denegado(update, context):
    if not update.message:
        logger.warning("Mensaje /denegado recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /denegado fuera del grupo destino: {chat_id}")
        return

    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /denegado [ticket]. Ejemplo: /denegado 150 🌟")
        return

    try:
        ticket_number = int(args[0])
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número válido. Ejemplo: /denegado 150 🌟")
        return

    if ticket_number not in peticiones_registradas:
        bot.send_message(chat_id=chat_id, text=f"❌ No se encontró una solicitud con ticket #{ticket_number}. 🌟")
        logger.info(f"Ticket #{ticket_number} no encontrado para /denegado")
        return

    peticion_info = peticiones_registradas[ticket_number]
    user_chat_id = peticion_info["chat_id"]
    username = peticion_info["username"]
    message_text = peticion_info["message_text"]

    username_escaped = escape_markdown(username, preserve_username=True)

    notificacion = (
        f"❌ {username_escaped}, tu solicitud con ticket #{ticket_number} \"{message_text}\" ha sido denegada. Contacta a un administrador si tienes dudas. 🌟"
    )
    try:
        bot.send_message(chat_id=user_chat_id, text=notificacion)
        bot.send_message(chat_id=chat_id, text=f"✅ Solicitud con ticket #{ticket_number} de {username_escaped} marcada como denegada. 🌟")
        logger.info(f"Notificación de /denegado enviada a {username} en {user_chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo notificar a {username_escaped}: {str(e)}. 🌟")
        logger.error(f"Error al notificar a {username_escaped}: {str(e)}")

# Función para manejar el comando /menu (solo en grupo destino)
def handle_menu(update, context):
    if not update.message:
        logger.warning("Mensaje /menu recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /menu fuera del grupo destino: {chat_id}")
        return

    menu_message = (
        "📋 **Menú de comandos** 🌟\n"
        "Aquí tienes todos los comandos disponibles:\n"
        "🔧 **Comandos para usuarios:**\n"
        "✅ **/solicito** o **#solicito** - Enviar una solicitud (máx. 2 por día).\n"
        "✅ **/peticion** o **#peticion** - Enviar una solicitud (máx. 2 por día).\n"
        "✅ **/ayuda** - Ver esta guía.\n"
        "✅ **/estado [ticket]** - Consultar el estado de una solicitud (ejemplo: /estado 150).\n"
        "🔧 **Comandos para administradores:**\n"
        "✅ **/eliminar [ticket] [estado]** - Elimina una solicitud y notifica al usuario (ejemplo: /eliminar 150 aprobada).\n"
        "✅ **/subido [ticket]** - Marca una solicitud como subida y notifica al usuario.\n"
        "✅ **/denegado [ticket]** - Marca una solicitud como denegada y notifica al usuario.\n"
        "✅ **/notificar [username] [mensaje]** - Envía un mensaje personalizado a un usuario (ejemplo: /notificar @MRS_K98 Tu solicitud está lista).\n"
        "📌 Estados válidos: aprobada, denegada, eliminada.\n"
        "📋 **/pendientes** - Ver lista de solicitudes pendientes.\n"
        "🔴 **/off** - Desactiva la recepción de solicitudes.\n"
        "🟢 **/on** - Reactiva la recepción de solicitudes.\n"
        "🌟 Bot de Entreshijos"
    )
    try:
        bot.send_message(chat_id=chat_id, text=menu_message, parse_mode='Markdown')
        logger.info("Menú enviado al grupo destino")
    except telegram.error.BadRequest as e:
        bot.send_message(chat_id=chat_id, text=menu_message.replace('*', '').replace('**', ''))  # Fallback a texto plano
        logger.error(f"Error al enviar menú con Markdown: {str(e)}")

# Función para manejar el comando /off (solo en grupo destino)
def handle_off(update, context):
    if not update.message:
        logger.warning("Mensaje /off recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /off fuera del grupo destino: {chat_id}")
        return

    global aceptar_solicitudes
    aceptar_solicitudes = False

    off_message = (
        "🚫 ¡Atención usuarios! 🌟\n"
        "De momento no se aceptan solicitudes hasta nuevo aviso. Equipo de administración.\n"
        "Disculpen las molestias. 🙏"
    )
    for grupo in grupos_activos:
        try:
            bot.send_message(chat_id=grupo, text=off_message)
            logger.info(f"Notificación /off enviada al grupo {grupo}")
        except telegram.error.TelegramError as e:
            logger.error(f"Error al notificar /off al grupo {grupo}: {str(e)}")

    bot.send_message(chat_id=chat_id, text="🔴 Bot desactivado para nuevas solicitudes. 🌟")
    logger.info("Bot desactivado para nuevas solicitudes")

# Función para manejar el comando /on (solo en grupo destino)
def handle_on(update, context):
    if not update.message:
        logger.warning("Mensaje /on recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /on fuera del grupo destino: {chat_id}")
        return

    global aceptar_solicitudes
    aceptar_solicitudes = True

    on_message = (
        "🎉 ¡Buenas noticias! 🌟\n"
        "Ya se pueden enviar solicitudes con /solicito, #solicito, /peticion o #peticion.\n"
        "Máximo 2 por día por usuario cada 24 horas. Equipo de Entreshijos. 🙌"
    )
    for grupo in grupos_activos:
        try:
            bot.send_message(chat_id=grupo, text=on_message)
            logger.info(f"Notificación /on enviada al grupo {grupo}")
        except telegram.error.TelegramError as e:
            logger.error(f"Error al notificar /on al grupo {grupo}: {str(e)}")

    bot.send_message(chat_id=chat_id, text="🟢 Bot reactivado para recibir solicitudes. 🌟")
    logger.info("Bot reactivado para nuevas solicitudes")

# Función para manejar el comando /pendientes (solo en grupo destino)
def handle_pendientes(update, context):
    if not update.message:
        logger.warning("Mensaje /pendientes recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /pendientes fuera del grupo destino: {chat_id}")
        return

    pendientes = [f"{i}. Ticket #{k} - {v['username']}: {v['message_text']} (Grupo: {v.get('chat_title', 'Desconocido')})"
                  for i, (k, v) in enumerate(peticiones_registradas.items(), 1)]
    if not pendientes:
        respuesta = "📋 No hay solicitudes pendientes. 🌟"
    else:
        respuesta = "📋 Solicitudes pendientes 🌟\n" + "\n".join(pendientes) + f"\nTotal: {len(pendientes)} pendientes ⏳"
    try:
        bot.send_message(chat_id=chat_id, text=respuesta)
        logger.info("Lista de pendientes enviada al grupo destino")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=respuesta)
        logger.error(f"Error al enviar pendientes: {str(e)}")

# Función para manejar el comando /ayuda
def handle_ayuda(update, context):
    if not update.message:
        logger.warning("Mensaje /ayuda recibido es None")
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
        logger.info(f"Ayuda enviada a {username} en {chat_id}")
    except telegram.error.BadRequest as e:
        bot.send_message(chat_id=chat_id, text=ayuda_message.replace('*', '').replace('**', ''))
        logger.error(f"Error al enviar ayuda con Markdown: {str(e)}")

# Función para manejar el comando /estado
def handle_estado(update, context):
    if not update.message:
        logger.warning("Mensaje /estado recibido es None")
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
            f"Ticket #{ticket_number}: {peticion_info['message_text']}\n"
            f"Estado: Pendiente ⏳\n"
            f"🕒 Enviada: {timestamp}"
        )
    else:
        estado_message = (
            f"📋 Estado de tu solicitud, {username} 🌟\n"
            f"Ticket #{ticket_number}: Ya fue gestionada (aprobada, denegada o eliminada). ✅"
        )
    try:
        bot.send_message(chat_id=chat_id, text=estado_message)
        logger.info(f"Estado de ticket #{ticket_number} enviado a {username} en {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=estado_message)
        logger.error(f"Error al enviar estado: {str(e)}")

# Función para manejar el comando /notificar [username] [mensaje]
def handle_notificar(update, context):
    if not update.message:
        logger.warning("Mensaje /notificar recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /notificar fuera del grupo destino: {chat_id}")
        return

    args = context.args
    if len(args) < 2:
        bot.send_message(chat_id=chat_id, text="❗ Usa: /notificar [username] [mensaje]. Ejemplo: /notificar @MRS_K98 Tu solicitud está lista 🌟")
        return

    username = args[0]
    message_text = " ".join(args[1:])
    user_chat_id = next((info["chat_id"] for info in peticiones_registradas.values() if info["username"] == username), None)

    if user_chat_id:
        try:
            bot.send_message(chat_id=user_chat_id, text=f"📩 {username}, mensaje del equipo: {message_text} 🌟")
            bot.send_message(chat_id=chat_id, text=f"✅ Notificación enviada a {username}. 🌟")
            logger.info(f"Notificación enviada a {username} en {user_chat_id}")
        except telegram.error.TelegramError as e:
            bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo notificar a {username}: {str(e)}. 🌟")
            logger.error(f"Error al notificar a {username}: {str(e)}")
    else:
        bot.send_message(chat_id=chat_id, text=f"❌ No se encontró a {username} en las solicitudes registradas. 🌟")
        logger.info(f"Usuario {username} no encontrado para notificación")

# Añade los handlers
message_handler = MessageHandler(Filters.text & ~Filters.command, handle_message)
dispatcher.add_handler(message_handler)

eliminar_handler = CommandHandler('eliminar', handle_eliminar)
dispatcher.add_handler(eliminar_handler)

subido_handler = CommandHandler('subido', handle_subido)
dispatcher.add_handler(subido_handler)

denegado_handler = CommandHandler('denegado', handle_denegado)
dispatcher.add_handler(denegado_handler)

menu_handler = CommandHandler('menu', handle_menu)
dispatcher.add_handler(menu_handler)

pendientes_handler = CommandHandler('pendientes', handle_pendientes)
dispatcher.add_handler(pendientes_handler)

ayuda_handler = CommandHandler('ayuda', handle_ayuda)
dispatcher.add_handler(ayuda_handler)

estado_handler = CommandHandler('estado', handle_estado)
dispatcher.add_handler(estado_handler)

notificar_handler = CommandHandler('notificar', handle_notificar)
dispatcher.add_handler(notificar_handler)

off_handler = CommandHandler('off', handle_off)
dispatcher.add_handler(off_handler)

on_handler = CommandHandler('on', handle_on)
dispatcher.add_handler(on_handler)

# Ruta para el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update_json = request.get_json(force=True)
        if not update_json:
            logger.error("No se recibió un JSON válido en el webhook")
            return 'No JSON', 400
        update = telegram.Update.de_json(update_json, bot)
        if not update:
            logger.error("No se pudo deserializar la actualización")
            return 'Invalid update', 400
        dispatcher.process_update(update)
        logger.info("Webhook procesado correctamente")
        return 'ok', 200
    except telegram.error.TelegramError as e:
        logger.error(f"Error de Telegram en el webhook: {str(e)}")
        return f'Error: {str(e)}', 500
    except Exception as e:
        logger.error(f"Error inesperado en el webhook: {str(e)}")
        return f'Error inesperado: {str(e)}', 500

# Ruta raíz (para verificar que el servidor está vivo)
@app.route('/')
def health_check():
    logger.info("Health check solicitado")
    return "Bot de Entreshijos está activo! 🌟", 200

if __name__ == '__main__':
    logger.info("Iniciando el bot en modo local")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta
import pytz
import os
import random
import logging

# Configura tu token, grupo y URL del webhook usando variables de entorno
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')  # Grupo de administradores
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
ticket_counter = 1  # Comienza en 1 para claridad
peticiones_por_usuario = {}  # {user_id: {"count": X, "chat_id": Y, "username": Z}}
peticiones_registradas = {}  # {ticket_number: {"chat_id": X, "username": Y, "message_text": Z, "message_id": W, "timestamp": T, "chat_title": V, "thread_id": T}}
historial_solicitudes = {}   # {ticket_number: {"chat_id": X, "username": Y, "message_text": Z, "chat_title": V, "estado": "subido/denegado/eliminado/notificado", "fecha_gestion": T, "admin_username": "@admin"}}
procesado = {}  # Flag para evitar duplicación de mensajes (update_id: True)
admin_ids = set([12345678])  # Lista de IDs de administradores (opcional, para excepciones en límites)
peticiones_incorrectas = {}  # {user_id: [{"timestamp": T, "chat_id": X}]}

# Lista de grupos predefinidos donde actúa el bot con sus nombres reales
GRUPOS_PREDEFINIDOS = {
    -1002350263641: "Biblioteca EnTresHijos",
    -1001886336551: "Biblioteca Privada EntresHijos",
    -1001918569531: "SALA DE ENTRESHIJOS.📽",
    -1002034968062: "ᏉᏗᏒᎥᎧᏕ 🖤",
    -1002348662107: "GLOBAL SPORTS STREAM",
}

# Mapeo de grupos a canales/temas específicos para respuestas de peticiones
CANALES_PETICIONES = {
    -1002350263641: {"chat_id": -1002350263641, "thread_id": 19},     # https://t.me/c/2350263641/19
    -1001886336551: {"chat_id": -1001886336551, "thread_id": 652},    # https://t.me/c/1886336551/652
    -1001918569531: {"chat_id": -1001918569531, "thread_id": 228298}, # https://t.me/c/1918569531/228298
    -1002034968062: {"chat_id": -1002034968062, "thread_id": 157047}, # https://t.me/c/2034968062/157047
    -1002348662107: {"chat_id": -1002348662107, "thread_id": 53411},  # https://t.me/c/2348662107/53411
}

# Inicializar grupos activos y estados con nombres reales
grupos_activos = set(GRUPOS_PREDEFINIDOS.keys())
grupos_estados = {gid: {"activo": True, "title": title} for gid, title in GRUPOS_PREDEFINIDOS.items()}
grupos_seleccionados = {}  # {chat_id: {"accion": "on/off", "grupos": set(), "mensaje_id": int, "estado": "seleccion/confirmacion/notificacion"}}

# Frases de agradecimiento aleatorias
frases_agradecimiento = [
    "¡Gracias por tu paciencia! 🙌",
    "¡Agradecemos tu confianza! 💖",
    "¡Tu apoyo es valioso! 🌟",
    "¡Gracias por usar el bot! 🎉"
]

# Respuestas divertidas para /ping
ping_respuestas = [
    "🏓 *¡Pong!* El bot está en línea, listo para arrasar. 🌟",
    "🎾 *¡Pong!* Aquí estoy, más vivo que nunca. 💪✨",
    "🚀 *¡Pong!* El bot despega, todo en orden. 🌍",
    "🎉 *¡Pong!* Online y con ganas de fiesta. 🥳🌟"
]

# Lista de comandos válidos para solicitudes
VALID_REQUEST_COMMANDS = [
    '/solicito', '/solícito', '#solícito', '#solicito', 
    '/Solicito', '/Solícito', '#Solícito', '#Solicito', 
    '/petición', '#petición', '/peticion', '#peticion', 
    '/Petición', '#Petición', '/Peticion', '#Peticion'
]

# Zona horaria de España (Península)
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Función para escapar caracteres especiales en Markdown
def escape_markdown(text, preserve_username=False):
    if not text:
        return text
    if preserve_username and text.startswith('@'):
        return text
    characters_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in characters_to_escape:
        text = text.replace(char, f'\\{char}')
    return text

# Actualizar estado de grupos
def update_grupos_estados(chat_id, title=None):
    if chat_id not in grupos_estados:
        grupos_estados[chat_id] = {"activo": True, "title": title if title else f"Grupo {chat_id}"}
        grupos_activos.add(chat_id)
    elif title and grupos_estados[chat_id]["title"] == f"Grupo {chat_id}":
        grupos_estados[chat_id]["title"] = title
    logger.info(f"Grupo registrado/actualizado: {chat_id} - {grupos_estados[chat_id]['title']}")

# Obtener hora actual de España
def get_spain_time():
    return datetime.now(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')

# Función para manejar mensajes
def handle_message(update, context):
    if not update.message:
        return  # Ignorar silenciosamente para callbacks

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
    thread_id = message.message_thread_id
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})

    # Registrar cualquier grupo donde el bot reciba un mensaje
    update_grupos_estados(chat_id, chat_title)

    timestamp = datetime.now(SPAIN_TZ)
    timestamp_str = get_spain_time()
    username_escaped = escape_markdown(username, preserve_username=True)
    chat_title_escaped = escape_markdown(chat_title)
    message_text_escaped = escape_markdown(message_text)

    # Verificar si el mensaje contiene un comando válido
    is_valid_request = any(cmd in message_text for cmd in VALID_REQUEST_COMMANDS)

    # Detección de solicitudes válidas
    if is_valid_request:
        logger.info(f"Solicitud recibida de {username} en {chat_title}: {message_text}")
        # Verificar si está en el canal de peticiones correcto
        if chat_id not in CANALES_PETICIONES or thread_id != CANALES_PETICIONES[chat_id]["thread_id"]:
            notificacion = (
                f"🚫 {username_escaped}, las solicitudes solo son válidas en el canal de peticiones correspondiente. 🌟"
            )
            warn_message = f"/warn {username_escaped} Petición fuera del canal correspondiente."
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=notificacion,
                message_thread_id=canal_info["thread_id"],
                parse_mode='Markdown'
            )
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=warn_message,
                message_thread_id=canal_info["thread_id"]
            )
            logger.info(f"Solicitud de {username} denegada: fuera del canal correcto")
            return

        if not grupos_estados.get(chat_id, {}).get("activo", True):
            notificacion = (
                f"🚫 {username_escaped}, las solicitudes están desactivadas en este grupo. Contacta a un administrador. 🌟"
            )
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=notificacion,
                message_thread_id=canal_info["thread_id"],
                parse_mode='Markdown'
            )
            logger.info(f"Solicitudes desactivadas en {chat_id}, notificado a {username}")
            return

        if user_id not in peticiones_por_usuario:
            peticiones_por_usuario[user_id] = {"count": 0, "chat_id": chat_id, "username": username}
        peticiones_por_usuario[user_id]["count"] += 1

        if peticiones_por_usuario[user_id]["count"] > 2 and user_id not in admin_ids:
            limite_message = (
                f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta mañana. 🌟"
            )
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=limite_message,
                message_thread_id=canal_info["thread_id"],
                parse_mode='Markdown'
            )
            warn_message = f"/warn {username_escaped} Límite de peticiones diarias superado"
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=warn_message,
                message_thread_id=canal_info["thread_id"]
            )
            logger.info(f"Límite excedido por {username}, advertencia enviada")
            return

        global ticket_counter
        ticket_counter += 1
        ticket_number = ticket_counter

        destino_message = (
            "📬 *Nueva solicitud recibida* 🌟\n"
            f"👤 *Usuario:* {username_escaped} (ID: {user_id})\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"📊 *Petición:* {peticiones_por_usuario.get(user_id, {'count': 1})['count']}/2\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp_str}\n"
            "🌟 *Bot de Entreshijos*"
        )
        try:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": timestamp,
                "chat_title": chat_title,
                "thread_id": thread_id
            }
            logger.info(f"Solicitud #{ticket_number} enviada al grupo destino")
        except telegram.error.BadRequest as e:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message.replace('*', ''))
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": timestamp,
                "chat_title": chat_title,
                "thread_id": thread_id
            }
            logger.error(f"Error al enviar con Markdown: {str(e)}")

        confirmacion_message = (
            "✅ *Solicitud registrada con éxito* 🎉\n"
            f"Hola {username_escaped}, tu solicitud ha sido guardada con el ticket *#{ticket_number}* en *📚 Bot EnTresHijos*.\n\n"
            "📌 *Detalles:*  \n"
            f"🆔 *ID:* {user_id}  \n"
            f"🏠 *Grupo:* {chat_title_escaped}  \n"
            f"📅 *Fecha:* {timestamp_str}  \n"
            f"📝 *Mensaje:* {message_text_escaped}  \n"
            f"🎫 *Ticket:* #{ticket_number} se te ha asignado  \n"
            "🔹 *Consulta tu solicitud:*  \n"
            "🔍 /estado {ticket_number} – Ver estado 📌  \n"
            "📖 /ayuda – Más información ℹ️  \n\n"
            "⏳ *Tu solicitud será atendida pronto. ¡Gracias por tu paciencia!* 🙌"
        )
        try:
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=confirmacion_message,
                parse_mode='Markdown',
                message_thread_id=canal_info["thread_id"]
            )
            logger.info(f"Confirmación enviada a {username} en chat {canal_info['chat_id']} thread {canal_info['thread_id']}")
        except telegram.error.BadRequest as e:
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=confirmacion_message.replace('*', ''),
                message_thread_id=canal_info["thread_id"]
            )
            logger.error(f"Error al enviar confirmación con Markdown a {canal_info['chat_id']}: {str(e)}")
        except telegram.error.TelegramError as e:
            logger.error(f"Error de Telegram al enviar a {canal_info['chat_id']} thread {canal_info['thread_id']}: {str(e)}")

    # Detección de solicitudes incorrectas
    elif any(word in message_text.lower() for word in ['solicito', 'solícito', 'peticion', 'petición']) and chat_id in CANALES_PETICIONES:
        if user_id not in peticiones_incorrectas:
            peticiones_incorrectas[user_id] = []

        # Registrar intento incorrecto
        peticiones_incorrectas[user_id].append({"timestamp": timestamp, "chat_id": chat_id})

        # Filtrar intentos en las últimas 24 horas
        cutoff_time = timestamp - timedelta(hours=24)
        intentos_recientes = [intento for intento in peticiones_incorrectas[user_id] if intento["timestamp"] > cutoff_time]
        peticiones_incorrectas[user_id] = intentos_recientes

        notificacion_incorrecta = (
            f"⚠️ {username_escaped}, tu petición no está bien formulada. "
            f"Usa solo: {', '.join(VALID_REQUEST_COMMANDS)}. "
            "Consulta /ayuda para más detalles. 🌟\n"
            "📋 *Equipo de Administración EnTresHijos*"
        )
        warn_message = f"/warn {username_escaped} Petición no bien formulada"

        if len(intentos_recientes) > 2:
            warn_message = f"/warn {username_escaped} Abuso de peticiones mal formuladas detectado"

        try:
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=notificacion_incorrecta,
                parse_mode='Markdown',
                message_thread_id=canal_info["thread_id"]
            )
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=warn_message,
                message_thread_id=canal_info["thread_id"]
            )
            logger.info(f"Notificación de petición incorrecta enviada a {username} en {chat_id}")
        except telegram.error.TelegramError as e:
            logger.error(f"Error al enviar notificación de petición incorrecta: {str(e)}")

# Comando /on con botones
def handle_on(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟", parse_mode='Markdown')
        return

    keyboard = []
    for grupo_id in grupos_activos:
        title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}",
                                             callback_data=f"select_on_{grupo_id}")])
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_on")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    grupos_seleccionados[chat_id] = {"accion": "on", "grupos": set(), "mensaje_id": None, "estado": "seleccion"}
    sent_message = bot.send_message(chat_id=chat_id,
                                    text="🟢 *Activar solicitudes* 🌟\nSelecciona los grupos para activar las solicitudes (puedes elegir varios):",
                                    reply_markup=reply_markup, parse_mode='Markdown')
    grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id

# Comando /off con botones
def handle_off(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟", parse_mode='Markdown')
        return

    keyboard = []
    for grupo_id in grupos_activos:
        title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}",
                                             callback_data=f"select_off_{grupo_id}")])
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_off")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    grupos_seleccionados[chat_id] = {"accion": "off", "grupos": set(), "mensaje_id": None, "estado": "seleccion"}
    sent_message = bot.send_message(chat_id=chat_id,
                                    text="🔴 *Desactivar solicitudes* 🌟\nSelecciona los grupos para desactivar las solicitudes (puedes elegir varios):",
                                    reply_markup=reply_markup, parse_mode='Markdown')
    grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id

# Comando /grupos
def handle_grupos(update, context):
    if not update.message and not update.callback_query:
        return

    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not grupos_estados:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟", parse_mode='Markdown')
        return

    estado = "\n".join([f"🏠 {info['title']}: {'🟢 Activo' if info['activo'] else '🔴 Inactivo'} (ID: {gid})"
                        for gid, info in sorted(grupos_estados.items(), key=lambda x: x[1]['title'])])
    keyboard = [[InlineKeyboardButton("🔙 Retroceder", callback_data="grupos_retroceder")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        bot.send_message(chat_id=chat_id,
                         text=f"📋 *Estado de los grupos* 🌟\n{estado}",
                         reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        update.callback_query.message.delete()
        bot.send_message(chat_id=chat_id,
                         text=f"📋 *Estado de los grupos* 🌟\n{estado}",
                         reply_markup=reply_markup, parse_mode='Markdown')

# Comando /historial
def handle_historial(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not historial_solicitudes:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes gestionadas en el historial. 🌟", parse_mode='Markdown')
        return

    solicitudes_ordenadas = sorted(historial_solicitudes.items(), key=lambda x: x[0], reverse=True)
    historial = []
    for ticket, info in solicitudes_ordenadas:
        estado_str = {
            "subido": "✅ Aceptada",
            "denegado": "❌ Denegada",
            "eliminado": "🗑️ Eliminada",
            "notificado": "📢 Respondida"
        }.get(info["estado"], "🔄 Desconocido")
        historial.append(
            f"🎫 *Ticket #{ticket}* 🌟\n"
            f"👤 *Usuario:* {escape_markdown(info['username'], True)}\n"
            f"📝 *Mensaje:* {escape_markdown(info['message_text'])}\n"
            f"🏠 *Grupo:* {escape_markdown(info['chat_title'])}\n"
            f"📅 *Gestionada:* {info['fecha_gestion'].strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"👥 *Admin:* {info['admin_username']}\n"
            f"📌 *Estado:* {estado_str}\n"
        )
    historial_message = "📜 *Historial de Solicitudes Gestionadas* 🌟\n\n" + "\n".join(historial)
    bot.send_message(chat_id=chat_id, text=historial_message, parse_mode='Markdown')

# Comando /recuperar
def handle_recuperar(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not historial_solicitudes:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes procesadas para recuperar. 🌟", parse_mode='Markdown')
        return

    keyboard = []
    for ticket, info in sorted(historial_solicitudes.items(), key=lambda x: x[0]):
        estado_icon = {"subido": "✅", "denegado": "❌", "eliminado": "🗑️", "notificado": "📢"}.get(info["estado"], "🔄")
        keyboard.append([InlineKeyboardButton(f"#{ticket} - {info['username']} ({info['chat_title']}) {estado_icon}",
                                             callback_data=f"recuperar_{ticket}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id,
                     text="🔍 *Recuperar solicitudes procesadas* 🌟\nSelecciona una solicitud para restaurarla:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /pendientes con botones
def handle_pendientes(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not peticiones_registradas:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes. 🌟", parse_mode='Markdown')
        return

    keyboard = []
    for ticket, info in sorted(peticiones_registradas.items(), key=lambda x: x[0]):
        keyboard.append([InlineKeyboardButton(f"#{ticket} - {info['username']} ({info['chat_title']})",
                                             callback_data=f"pend_{ticket}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id,
                     text="📋 *Solicitudes pendientes* 🌟\nSelecciona una solicitud para gestionarla:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /eliminar con confirmación
def handle_eliminar(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not peticiones_registradas:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes para eliminar. 🌟", parse_mode='Markdown')
        return

    keyboard = []
    for ticket, info in peticiones_registradas.items():
        keyboard.append([InlineKeyboardButton(f"Ticket #{ticket} - {info['username']}",
                                             callback_data=f"eliminar_{ticket}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id,
                     text="🗑️ *Eliminar solicitud* 🌟\nSelecciona el ticket a eliminar:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /ping
def handle_ping(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    bot.send_message(chat_id=chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')

# Comando /subido con confirmación
def handle_subido(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /subido [ticket] 🌟", parse_mode='Markdown')
        return
    try:
        ticket = int(args[0])
        if ticket not in peticiones_registradas:
            bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return
        info = peticiones_registradas[ticket]
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_subido_{ticket}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id,
                         text=f"📋 *Confirmar acción* 🌟\n¿Marcar el Ticket #{ticket} de {info['username']} como subido?",
                         reply_markup=reply_markup, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟", parse_mode='Markdown')

# Comando /denegado con confirmación
def handle_denegado(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /denegado [ticket] 🌟", parse_mode='Markdown')
        return
    try:
        ticket = int(args[0])
        if ticket not in peticiones_registradas:
            bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return
        info = peticiones_registradas[ticket]
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_denegado_{ticket}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id,
                         text=f"📋 *Confirmar acción* 🌟\n¿Marcar el Ticket #{ticket} de {info['username']} como denegado?",
                         reply_markup=reply_markup, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟", parse_mode='Markdown')

# Comando /alerta
def handle_alerta(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    if not peticiones_registradas:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes activas para alertar. 🌟", parse_mode='Markdown')
        return

    keyboard = []
    for ticket, info in sorted(peticiones_registradas.items(), key=lambda x: x[0]):
        keyboard.append([InlineKeyboardButton(f"#{ticket} - {info['username']} ({info['chat_title']})",
                                             callback_data=f"alerta_select_{ticket}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id,
                     text="📢 *Seleccionar solicitud para alerta* 🌟\nElige una solicitud activa:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /restar (reemplaza a /addplus)
def handle_restar(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    args = context.args
    if len(args) != 2 or not args[0].startswith('@'):
        bot.send_message(chat_id=chat_id, text="❗ Uso: /restar @username [número] 🌟", parse_mode='Markdown')
        return

    username = args[0]
    try:
        amount = int(args[1])
        if amount <= 0:
            bot.send_message(chat_id=chat_id, text="❌ El número debe ser positivo. 🌟", parse_mode='Markdown')
            return
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ El segundo argumento debe ser un número. 🌟", parse_mode='Markdown')
        return

    user_id = next((uid for uid, info in peticiones_por_usuario.items() if info["username"] == username), None)
    if not user_id:
        bot.send_message(chat_id=chat_id, text=f"❌ {username} no encontrado en las peticiones. 🌟", parse_mode='Markdown')
        return

    peticiones_por_usuario[user_id]["count"] = max(0, peticiones_por_usuario[user_id]["count"] - amount)  # Resta para aumentar capacidad
    bot.send_message(chat_id=chat_id, text=f"✅ Restadas {amount} peticiones a {username}. Nuevo conteo: {peticiones_por_usuario[user_id]['count']}/2 🌟", parse_mode='Markdown')

# Comando /sumar (reemplaza a /addminus)
def handle_sumar(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return

    args = context.args
    if len(args) != 2 or not args[0].startswith('@'):
        bot.send_message(chat_id=chat_id, text="❗ Uso: /sumar @username [número] 🌟", parse_mode='Markdown')
        return

    username = args[0]
    try:
        amount = int(args[1])
        if amount <= 0:
            bot.send_message(chat_id=chat_id, text="❌ El número debe ser positivo. 🌟", parse_mode='Markdown')
            return
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ El segundo argumento debe ser un número. 🌟", parse_mode='Markdown')
        return

    user_id = next((uid for uid, info in peticiones_por_usuario.items() if info["username"] == username), None)
    if not user_id:
        bot.send_message(chat_id=chat_id, text=f"❌ {username} no encontrado en las peticiones. 🌟", parse_mode='Markdown')
        return

    peticiones_por_usuario[user_id]["count"] += amount  # Suma para reducir capacidad
    bot.send_message(chat_id=chat_id, text=f"✅ Sumadas {amount} peticiones a {username}. Nuevo conteo: {peticiones_por_usuario[user_id]['count']}/2 🌟", parse_mode='Markdown')

# Manejo de botones
def button_handler(update, context):
    query = update.callback_query
    if not query:
        return
    query.answer()
    data = query.data
    chat_id = query.message.chat_id
    mensaje_id = query.message.message_id
    current_text = query.message.text
    current_markup = query.message.reply_markup
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"

    if data == "grupos_retroceder":
        handle_grupos(update, context)
        return

    if data == "cancel_action":
        query.edit_message_text(text="❌ Acción cancelada. 🌟", parse_mode='Markdown')
        return

    # Manejo de /on y /off
    if data.startswith("select_") or data.startswith("confirm_") or data.startswith("notify_") or data.startswith("back_"):
        if chat_id not in grupos_seleccionados:
            return
        estado = grupos_seleccionados[chat_id]["estado"]

        if estado == "seleccion" and (data.startswith("select_on_") or data.startswith("select_off_")):
            accion = "on" if data.startswith("select_on_") else "off"
            grupo_id_str = data.split("_", 2)[2]
            try:
                grupo_id = int(grupo_id_str)
            except ValueError:
                logger.error(f"Error al convertir grupo_id a entero: {grupo_id_str}")
                return

            if mensaje_id == grupos_seleccionados[chat_id]["mensaje_id"]:
                title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
                if grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                    grupos_seleccionados[chat_id]["grupos"].remove(grupo_id)
                    new_text = current_text.replace(f"\n{'🟢' if accion == 'on' else '🔴'} {title} seleccionado.", "")
                else:
                    grupos_seleccionados[chat_id]["grupos"].add(grupo_id)
                    new_text = current_text + f"\n{'🟢' if accion == 'on' else '🔴'} {title} seleccionado."

                if new_text != current_text:
                    keyboard = []
                    for gid in grupos_activos:
                        title = grupos_estados.get(gid, {}).get("title", f"Grupo {gid}")
                        seleccionado = gid in grupos_seleccionados[chat_id]["grupos"]
                        callback = f"select_{accion}_{gid}"
                        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(gid, {}).get('activo', True) else '🔴'}{' ✅' if seleccionado else ''}",
                                                             callback_data=callback)])
                    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    query.edit_message_text(text=new_text, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if estado == "seleccion" and (data == "confirm_on" or data == "confirm_off"):
            accion = "on" if data == "confirm_on" else "off"
            if not grupos_seleccionados[chat_id]["grupos"]:
                query.edit_message_text(text=f"ℹ️ No se seleccionaron grupos para {'activar' if accion == 'on' else 'desactivar'}. 🌟", parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
                return

            grupos_seleccionados[chat_id]["estado"] = "confirmacion"
            grupos = "\n".join([grupos_estados[gid]["title"] for gid in grupos_seleccionados[chat_id]["grupos"]])
            texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'}* 🌟\n" \
                    f"Grupos afectados:\n{grupos}\n\n¿Enviar notificación a los grupos seleccionados?"
            keyboard = [
                [InlineKeyboardButton("✅ Sí", callback_data=f"notify_{accion}_yes")],
                [InlineKeyboardButton("❌ No", callback_data=f"notify_{accion}_no")],
                [InlineKeyboardButton("🔙 Retroceder", callback_data=f"back_{accion}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if estado == "confirmacion" and data.startswith("notify_"):
            accion, decision = data.split("_", 2)[1:]
            if decision == "yes":
                mensaje = (
                    "🎉 *¡Solicitudes reactivadas!* 🌟\nYa se pueden enviar solicitudes.\nMáximo 2 por día por usuario. 🙌"
                ) if accion == "on" else (
                    "🚫 *Solicitudes desactivadas* 🌟\nNo se aceptan nuevas solicitudes hasta nuevo aviso.\nDisculpen las molestias. 🙏"
                )
                for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                    canal_info = CANALES_PETICIONES.get(grupo_id, {"chat_id": grupo_id, "thread_id": None})
                    try:
                        bot.send_message(
                            chat_id=canal_info["chat_id"],
                            text=mensaje,
                            parse_mode='Markdown',
                            message_thread_id=canal_info["thread_id"]
                        )
                        logger.info(f"Notificación /{accion} enviada a {grupo_id} en canal {canal_info['chat_id']} thread {canal_info['thread_id']}")
                    except telegram.error.TelegramError as e:
                        logger.error(f"Error al notificar /{accion} a {grupo_id}: {str(e)}")
                texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} y notificadas.* 🌟"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
            elif decision == "no":
                for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                    grupos_estados[grupo_id]["activo"] = (accion == "on")
                texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} sin notificación.* 🌟"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
            return

        if estado == "confirmacion" and data.startswith("back_"):
            accion = data.split("_")[1]
            grupos_seleccionados[chat_id]["estado"] = "seleccion"
            keyboard = []
            for grupo_id in grupos_activos:
                title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
                seleccionado = grupo_id in grupos_seleccionados[chat_id]["grupos"]
                callback = f"select_{accion}_{grupo_id}"
                keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}{' ✅' if seleccionado else ''}",
                                                     callback_data=callback)])
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"{'🟢' if accion == 'on' else '🔴'} *{'Activar' if accion == 'on' else 'Desactivar'} solicitudes* 🌟\nSelecciona los grupos (puedes elegir varios):"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

    # Manejo de /pendientes
    if data.startswith("pend_"):
        if data == "pend_regresar":
            keyboard = []
            for ticket, info in sorted(peticiones_registradas.items(), key=lambda x: x[0]):
                keyboard.append([InlineKeyboardButton(f"#{ticket} - {info['username']} ({info['chat_title']})",
                                                     callback_data=f"pend_{ticket}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = "📋 *Solicitudes pendientes* 🌟\nSelecciona una solicitud para gestionarla:"
            if texto != current_text or str(reply_markup) != str(current_markup):
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar ticket en callback pend_: {data}")
            return

        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

        info = peticiones_registradas[ticket]
        if len(data.split("_")) == 2:
            keyboard = [
                [InlineKeyboardButton("✅ Subido", callback_data=f"pend_{ticket}_subido")],
                [InlineKeyboardButton("❌ Denegado", callback_data=f"pend_{ticket}_denegado")],
                [InlineKeyboardButton("🗑️ Eliminar", callback_data=f"pend_{ticket}_eliminar")],
                [InlineKeyboardButton("🔙 Regresar", callback_data="pend_regresar")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = (
                f"📋 *Solicitud #{ticket}* 🌟\n"
                f"👤 *Usuario:* {escape_markdown(info['username'], True)}\n"
                f"📝 *Mensaje:* {escape_markdown(info['message_text'])}\n"
                f"🏠 *Grupo:* {escape_markdown(info['chat_title'])}\n"
                f"🕒 *Fecha:* {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}\n"
                "Selecciona una acción:"
            )
            if texto != current_text or str(reply_markup) != str(current_markup):
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        try:
            accion = data.split("_")[2]
        except IndexError:
            logger.error(f"Error al procesar acción en callback pend_: {data}")
            return

        if accion in ["subido", "denegado", "eliminar"] and len(data.split("_")) == 3:
            keyboard = [
                [InlineKeyboardButton("✅ Confirmar", callback_data=f"pend_{ticket}_{accion}_confirm")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            accion_str = {"subido": "subido", "denegado": "denegado", "eliminar": "eliminado"}[accion]
            texto = f"📋 *Confirmar acción* 🌟\n¿Marcar el Ticket #{ticket} de {info['username']} como {accion_str}?"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if len(data.split("_")) == 4 and data.endswith("confirm"):
            accion = data.split("_")[2]
            username_escaped = escape_markdown(info["username"], True)
            message_text_escaped = escape_markdown(info["message_text"])
            user_chat_id = info["chat_id"]
            message_id = info["message_id"]
            thread_id = info.get("thread_id")

            historial_solicitudes[ticket] = {
                "chat_id": user_chat_id,
                "username": info["username"],
                "message_text": info["message_text"],
                "chat_title": info["chat_title"],
                "estado": accion,
                "fecha_gestion": datetime.now(SPAIN_TZ),
                "admin_username": admin_username
            }

            if accion == "subido":
                notificacion = f"✅ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido subida. 🎉"
                bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown', message_thread_id=thread_id)
                texto = f"✅ *Ticket #{ticket} procesado como subido.* 🌟"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del peticiones_registradas[ticket]

            elif accion == "denegado":
                notificacion = f"❌ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada. 🌟"
                bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown', message_thread_id=thread_id)
                texto = f"✅ *Ticket #{ticket} procesado como denegado.* 🌟"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del peticiones_registradas[ticket]

            elif accion == "eliminar":
                try:
                    bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
                    bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} de {username_escaped} eliminado. 🌟", parse_mode='Markdown')
                except telegram.error.TelegramError as e:
                    bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos. 🌟", parse_mode='Markdown')
                notificacion = f"ℹ️ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada. 🌟"
                bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown', message_thread_id=thread_id)
                texto = f"✅ *Ticket #{ticket} procesado como eliminado.* 🌟"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del peticiones_registradas[ticket]

    # Manejo de /eliminar
    if data.startswith("eliminar_"):
        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar eliminar_ callback: {data}")
            return

        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

        info = peticiones_registradas[ticket]
        if len(data.split("_")) == 2:
            keyboard = [
                [InlineKeyboardButton("✅ Aprobada", callback_data=f"eliminar_{ticket}_aprobada")],
                [InlineKeyboardButton("❌ Denegada", callback_data=f"eliminar_{ticket}_denegada")],
                [InlineKeyboardButton("🗑️ Eliminada", callback_data=f"eliminar_{ticket}_eliminada")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"🗑️ *Eliminar Ticket #{ticket}* 🌟\nSelecciona el estado:"
            if texto != current_text or str(reply_markup) != str(current_markup):
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        try:
            estado = data.split("_")[2]
        except IndexError:
            logger.error(f"Error al procesar estado en callback eliminar_: {data}")
            return

        user_chat_id = info["chat_id"]
        username = info["username"]
        message_text = info["message_text"]
        message_id = info["message_id"]
        thread_id = info.get("thread_id")

        historial_solicitudes[ticket] = {
            "chat_id": user_chat_id,
            "username": username,
            "message_text": message_text,
            "chat_title": info["chat_title"],
            "estado": "eliminado",
            "fecha_gestion": datetime.now(SPAIN_TZ),
            "admin_username": admin_username
        }

        try:
            bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
            bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} de {escape_markdown(username, True)} eliminado ({estado}). 🌟", parse_mode='Markdown')
        except telegram.error.TelegramError as e:
            bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos. 🌟", parse_mode='Markdown')

        username_escaped = escape_markdown(username, True)
        message_text_escaped = escape_markdown(message_text)

        if estado == "aprobada":
            notificacion = f"✅ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido aprobada. 🎉"
            historial_solicitudes[ticket]["estado"] = "subido"
        elif estado == "denegada":
            notificacion = f"❌ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada. 🌟"
            historial_solicitudes[ticket]["estado"] = "denegado"
        else:
            notificacion = f"ℹ️ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada. 🌟"

        bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown', message_thread_id=thread_id)
        texto = f"✅ *Ticket #{ticket} procesado como {estado}.* 🌟"
        query.edit_message_text(text=texto, parse_mode='Markdown')
        del peticiones_registradas[ticket]

    # Manejo de confirmaciones /subido y /denegado
    if data.startswith("confirm_subido_"):
        ticket = int(data.split("_")[2])
        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return
        info = peticiones_registradas[ticket]
        historial_solicitudes[ticket] = {
            "chat_id": info["chat_id"],
            "username": info["username"],
            "message_text": info["message_text"],
            "chat_title": info["chat_title"],
            "estado": "subido",
            "fecha_gestion": datetime.now(SPAIN_TZ),
            "admin_username": admin_username
        }
        bot.send_message(chat_id=info["chat_id"],
                         text=f"✅ {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido subida. 🎉",
                         parse_mode='Markdown', message_thread_id=info.get("thread_id"))
        bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como subido. 🌟", parse_mode='Markdown')
        query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como subido.* 🌟", parse_mode='Markdown')
        del peticiones_registradas[ticket]

    if data.startswith("confirm_denegado_"):
        ticket = int(data.split("_")[2])
        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return
        info = peticiones_registradas[ticket]
        historial_solicitudes[ticket] = {
            "chat_id": info["chat_id"],
            "username": info["username"],
            "message_text": info["message_text"],
            "chat_title": info["chat_title"],
            "estado": "denegado",
            "fecha_gestion": datetime.now(SPAIN_TZ),
            "admin_username": admin_username
        }
        bot.send_message(chat_id=info["chat_id"],
                         text=f"❌ {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido denegada. 🌟",
                         parse_mode='Markdown', message_thread_id=info.get("thread_id"))
        bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como denegado. 🌟", parse_mode='Markdown')
        query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como denegado.* 🌟", parse_mode='Markdown')
        del peticiones_registradas[ticket]

    # Manejo de /recuperar
    if data.startswith("recuperar_"):
        ticket = int(data.split("_")[1])
        if ticket not in historial_solicitudes:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado en el historial. 🌟", parse_mode='Markdown')
            return
        info = historial_solicitudes[ticket]
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"recuperar_confirm_{ticket}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        texto = (
            f"🔍 *Recuperar Ticket #{ticket}* 🌟\n"
            f"👤 *Usuario:* {escape_markdown(info['username'], True)}\n"
            f"📝 *Mensaje:* {escape_markdown(info['message_text'])}\n"
            f"🏠 *Grupo:* {escape_markdown(info['chat_title'])}\n"
            f"¿Restaurar esta solicitud para procesarla nuevamente?"
        )
        query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')

    if data.startswith("recuperar_confirm_"):
        ticket = int(data.split("_")[2])
        if ticket not in historial_solicitudes:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado en el historial. 🌟", parse_mode='Markdown')
            return
        info = historial_solicitudes[ticket]
        destino_message = (
            "📬 *Solicitud recuperada* 🌟\n"
            f"👤 *Usuario:* {escape_markdown(info['username'], True)} (ID: {info.get('user_id', 'N/A')})\n"
            f"🎫 *Ticket:* #{ticket}\n"
            f"📝 *Mensaje:* {escape_markdown(info['message_text'])}\n"
            f"🏠 *Grupo:* {escape_markdown(info['chat_title'])}\n"
            f"🕒 *Fecha original:* {info.get('timestamp', datetime.now(SPAIN_TZ)).strftime('%d/%m/%Y %H:%M:%S')}\n"
            "🌟 *Bot de Entreshijos*"
        )
        sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
        peticiones_registradas[ticket] = {
            "chat_id": info["chat_id"],
            "username": info["username"],
            "message_text": info["message_text"],
            "message_id": sent_message.message_id,
            "timestamp": info.get("timestamp", datetime.now(SPAIN_TZ)),
            "chat_title": info["chat_title"],
            "thread_id": info.get("thread_id")
        }
        del historial_solicitudes[ticket]
        query.edit_message_text(text=f"✅ *Ticket #{ticket} restaurado para procesamiento.* 🌟", parse_mode='Markdown')

    # Manejo de /alerta
    if data.startswith("alerta_select_"):
        ticket = int(data.split("_")[2])
        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return
        info = peticiones_registradas[ticket]
        texto = (
            f"📢 *Alerta para Ticket #{ticket}* 🌟\n"
            f"👤 *Usuario:* {escape_markdown(info['username'], True)}\n"
            f"📝 *Mensaje:* {escape_markdown(info['message_text'])}\n"
            f"🏠 *Grupo:* {escape_markdown(info['chat_title'])}\n"
            "Por favor, responde con la URL de la solicitud resuelta (https://t.me/...):"
        )
        query.edit_message_text(text=texto, parse_mode='Markdown')
        context.user_data["alerta_ticket"] = ticket
        context.user_data["alerta_chat_id"] = chat_id  # Guardar el chat_id para validar
        logger.info(f"Ticket #{ticket} seleccionado para alerta, esperando URL")

# Manejo de respuestas para /alerta
def handle_alerta_respuesta(update, context):
    if not update.message:
        logger.info("No hay mensaje en la actualización")
        return

    message = update.message
    chat_id = message.chat_id

    # Verificar si estamos esperando una respuesta para /alerta
    if "alerta_ticket" not in context.user_data or "alerta_chat_id" not in context.user_data:
        logger.info("No se encontró alerta_ticket o alerta_chat_id en context.user_data")
        return

    # Validar que el mensaje proviene del chat correcto
    if str(chat_id) != str(context.user_data["alerta_chat_id"]):
        logger.info(f"Mensaje recibido en chat incorrecto: {chat_id}, esperado: {context.user_data['alerta_chat_id']}")
        return

    ticket = context.user_data.get("alerta_ticket")
    if ticket is None or ticket not in peticiones_registradas:
        bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado o sesión expirada. Usa /alerta nuevamente. 🌟", parse_mode='Markdown')
        if "alerta_ticket" in context.user_data:
            del context.user_data["alerta_ticket"]
        if "alerta_chat_id" in context.user_data:
            del context.user_data["alerta_chat_id"]
        return

    url = message.text.strip()
    if not url.startswith("https://t.me/"):
        bot.send_message(chat_id=chat_id, text="❌ La URL debe ser un enlace válido de Telegram (https://t.me/...). 🌟", parse_mode='Markdown')
        return

    info = peticiones_registradas[ticket]
    notificacion = (
        f"📢 *Alerta* 🌟\n"
        f"Hola {escape_markdown(info['username'], True)}, aquí tienes el enlace a tu solicitud:\n"
        f"[Solicitud #{ticket}]({url})\n"
        f"{random.choice(frases_agradecimiento)}"
    )
    try:
        bot.send_message(
            chat_id=info["chat_id"],
            text=notificacion,
            parse_mode='Markdown',
            message_thread_id=info.get("thread_id")
        )
        bot.send_message(
            chat_id=chat_id,
            text=f"✅ Alerta enviada a {escape_markdown(info['username'], True)} con el enlace {url}. 🌟",
            parse_mode='Markdown'
        )
        logger.info(f"Alerta enviada para Ticket #{ticket} a {info['username']} con URL {url}")
    except telegram.error.TelegramError as e:
        bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Error al enviar la alerta: {str(e)}. Por favor, intenta de nuevo. 🌟",
            parse_mode='Markdown'
        )
        logger.error(f"Error al enviar alerta para Ticket #{ticket}: {str(e)}")
    finally:
        if "alerta_ticket" in context.user_data:
            del context.user_data["alerta_ticket"]
        if "alerta_chat_id" in context.user_data:
            del context.user_data["alerta_chat_id"]

# Comando /menu
def handle_menu(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟", parse_mode='Markdown')
        return
    menu_message = (
        "📋 *Menú de comandos* 🌟\n"
        "🔧 *Usuarios:*\n"
        "✅ */solicito*, */solícito*, *#solicito*, etc. - Enviar solicitud (máx. 2/día).\n"
        "🔧 *Comandos en grupo destino:*\n"
        "📋 */pendientes* - Gestionar solicitudes.\n"
        "📢 */alerta* - Enviar alerta con enlace.\n"
        "🔍 */recuperar* - Restaurar solicitudes procesadas.\n"
        "➖ */restar @username [número]* - Restar peticiones.\n"
        "➕ */sumar @username [número]* - Sumar peticiones.\n"
        "🟢 */on* - Activar solicitudes.\n"
        "🔴 */off* - Desactivar solicitudes.\n"
        "🏠 */grupos* - Ver estado de grupos.\n"
        "📜 */historial* - Ver solicitudes gestionadas.\n"
        "🏓 */ping* - Verificar si el bot está vivo.\n"
        "🌟 *Bot de Entreshijos*"
    )
    bot.send_message(chat_id=chat_id, text=menu_message, parse_mode='Markdown')

# Comando /ayuda
def handle_ayuda(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    thread_id = message.message_thread_id if chat_id in CANALES_PETICIONES else None
    username = escape_markdown(f"@{message.from_user.username}", True) if message.from_user.username else "Usuario"
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})
    ayuda_message = (
        "📖 *Guía rápida* 🌟\n"
        f"Hola {username}, usa comandos como */solicito*, *#peticion*, etc., para enviar una solicitud (máx. 2/día).\n"
        f"Comandos válidos: {', '.join(VALID_REQUEST_COMMANDS)}\n"
        "🔍 */estado [ticket]* - Consulta el estado.\n"
        "🌟 *¡Gracias por usar el bot!* 🙌"
    )
    bot.send_message(chat_id=canal_info["chat_id"], text=ayuda_message, parse_mode='Markdown', message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None)

# Comando /estado
def handle_estado(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    thread_id = message.message_thread_id if chat_id in CANALES_PETICIONES else None
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})
    username = escape_markdown(f"@{message.from_user.username}", True) if message.from_user.username else "Usuario"
    args = context.args
    if not args:
        bot.send_message(chat_id=canal_info["chat_id"], text="❗ Uso: /estado [ticket] 🌟", parse_mode='Markdown', message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None)
        return
    try:
        ticket = int(args[0])
        if ticket in peticiones_registradas:
            info = peticiones_registradas[ticket]
            estado_message = (
                f"📋 *Estado* 🌟\n"
                f"Ticket #{ticket}: {escape_markdown(info['message_text'])}\n"
                f"Estado: Pendiente ⏳\n"
                f"🕒 Enviada: {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}"
            )
        elif ticket in historial_solicitudes:
            info = historial_solicitudes[ticket]
            estado_str = {
                "subido": "✅ Aceptada",
                "denegado": "❌ Denegada",
                "eliminado": "🗑️ Eliminada",
                "notificado": "📢 Respondida"
            }.get(info["estado"], "🔄 Desconocido")
            estado_message = (
                f"📋 *Estado* 🌟\n"
                f"Ticket #{ticket}: {escape_markdown(info['message_text'])}\n"
                f"Estado: {estado_str}\n"
                f"🕒 Gestionada: {info['fecha_gestion'].strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"👥 Admin: {info['admin_username']}"
            )
        else:
            estado_message = f"❌ Ticket #{ticket} no encontrado. 🌟"
        bot.send_message(
            chat_id=canal_info["chat_id"],
            text=estado_message,
            parse_mode='Markdown',
            message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None
        )
    except ValueError:
        bot.send_message(
            chat_id=canal_info["chat_id"],
            text="❗ Ticket debe ser un número. 🌟",
            parse_mode='Markdown',
            message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None
        )

# Configurar handlers
dispatcher.add_handler(CommandHandler("on", handle_on))
dispatcher.add_handler(CommandHandler("off", handle_off))
dispatcher.add_handler(CommandHandler("grupos", handle_grupos))
dispatcher.add_handler(CommandHandler("historial", handle_historial))
dispatcher.add_handler(CommandHandler("recuperar", handle_recuperar))
dispatcher.add_handler(CommandHandler("pendientes", handle_pendientes))
dispatcher.add_handler(CommandHandler("eliminar", handle_eliminar))
dispatcher.add_handler(CommandHandler("ping", handle_ping))
dispatcher.add_handler(CommandHandler("subido", handle_subido))
dispatcher.add_handler(CommandHandler("denegado", handle_denegado))
dispatcher.add_handler(CommandHandler("alerta", handle_alerta))
dispatcher.add_handler(CommandHandler("restar", handle_restar))
dispatcher.add_handler(CommandHandler("sumar", handle_sumar))
dispatcher.add_handler(CommandHandler("menu", handle_menu))
dispatcher.add_handler(CommandHandler("ayuda", handle_ayuda))
dispatcher.add_handler(CommandHandler("estado", handle_estado))
dispatcher.add_handler(CallbackQueryHandler(button_handler))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_alerta_respuesta))
dispatcher.add_handler(MessageHandler(Filters.text, handle_message))

# Ruta para el webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = telegram.Update.de_json(request.get_json(force=True), bot)
        if update:
            dispatcher.process_update(update)
        else:
            logger.error("No se pudo procesar la actualización: update es None")
        return 'ok', 200
    except Exception as e:
        logger.error(f"Error en el webhook: {str(e)}")
        return 'error', 500

# Configurar el webhook
def set_webhook():
    try:
        webhook_info = bot.get_webhook_info()
        if webhook_info.url != WEBHOOK_URL:
            bot.delete_webhook()
            bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Webhook configurado en {WEBHOOK_URL}")
        else:
            logger.info("Webhook ya configurado correctamente")
    except telegram.error.TelegramError as e:
        logger.error(f"Error al configurar el webhook: {str(e)}")

# Ruta raíz para verificar que el servidor está activo
@app.route('/')
def home():
    return "Bot de EnTresHijos activo!"

if __name__ == '__main__':
    set_webhook()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
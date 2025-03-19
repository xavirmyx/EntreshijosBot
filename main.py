from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime
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
ticket_counter = 150  # Comienza en 150
peticiones_por_usuario = {}  # {user_id: {"count": X, "chat_id": Y, "username": Z}}
peticiones_registradas = {}  # {ticket_number: {"chat_id": X, "username": Y, "message_text": Z, "message_id": W, "timestamp": T, "chat_title": V}}
procesado = {}  # Flag para evitar duplicación de mensajes (update_id: True)
admin_ids = set([12345678])  # Lista de IDs de administradores (opcional, para excepciones en límites)

# Lista de grupos predefinidos donde actúa el bot con sus nombres reales
GRUPOS_PREDEFINIDOS = {
    -1002350263641: "Biblioteca EnTresHijos",
    -1001886336551: "Biblioteca Privada EntresHijos",
    -1001918569531: "SALA DE ENTRESHIJOS.📽",
    -1002034968062: "ᏉᏗᏒᎥᎧᏕ 🖤",
    -1002348662107: "GLOBAL SPORTS STREAM",
}

# Inicializar grupos activos y estados con nombres reales
grupos_activos = set(GRUPOS_PREDEFINIDOS.keys())
grupos_estados = {gid: {"activo": True, "title": title} for gid, title in GRUPOS_PREDEFINIDOS.items()}
grupos_seleccionados = {}  # {chat_id_admin: {"accion": "on/off", "grupos": set(), "mensaje_id": int}}

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

# Función para manejar mensajes
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

    # Registrar cualquier grupo donde el bot reciba un mensaje
    update_grupos_estados(chat_id, chat_title)

    timestamp = datetime.now(pytz.timezone('UTC')).strftime('%d/%m/%Y %H:%M:%S')
    username_escaped = escape_markdown(username, preserve_username=True)
    chat_title_escaped = escape_markdown(chat_title)
    message_text_escaped = escape_markdown(message_text)

    if any(cmd in message_text.lower() for cmd in ['#solicito', '/solicito', '#peticion', '/peticion']):
        logger.info(f"Solicitud recibida de {username} en {chat_title}: {message_text}")
        if not grupos_estados.get(chat_id, {}).get("activo", True):
            notificacion = (
                f"🚫 {username_escaped}, las solicitudes están desactivadas en este grupo. Contacta a un administrador. 🌟"
            )
            bot.send_message(chat_id=chat_id, text=notificacion)
            logger.info(f"Solicitudes desactivadas en {chat_id}, notificado a {username}")
            return

        if user_id not in peticiones_por_usuario:
            peticiones_por_usuario[user_id] = {"count": 0, "chat_id": chat_id, "username": username}
        peticiones_por_usuario[user_id]["count"] += 1

        if peticiones_por_usuario[user_id]["count"] > 2 and user_id not in admin_ids:
            limite_message = (
                f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta mañana. 🌟"
            )
            bot.send_message(chat_id=chat_id, text=limite_message)
            warn_message = f"/warn {username_escaped} Límite de peticiones diarias superado"
            bot.send_message(chat_id=chat_id, text=warn_message)
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
            f"🕒 *Fecha:* {timestamp}\n"
            "🌟 *Bot de Entreshijos*"
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
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message.replace('*', ''))
            peticiones_registradas[ticket_number] = {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": datetime.now(pytz.timezone('UTC')),
                "chat_title": chat_title
            }
            logger.error(f"Error al enviar con Markdown: {str(e)}")

        confirmacion_message = (
            "✅ *Solicitud registrada con éxito* 🎉\n"
            f"Hola {username_escaped}, tu solicitud ha sido guardada con el ticket *#{ticket_number}* en *📚 Bot EnTresHijos*.\n\n"
            "📌 *Detalles:*  \n"
            f"🆔 *ID:* {user_id}  \n"
            f"🏠 *Grupo:* {chat_title_escaped}  \n"
            f"📅 *Fecha:* {timestamp}  \n"
            f"📝 *Mensaje:* {message_text_escaped}  \n"
            f"🎫 *Ticket:* {ticket_number} se te ha asignado  \n"
            "🔹 *Consulta tu solicitud:*  \n"
            "🔍 /estado {ticket_number} – Ver estado 📌  \n"
            "📖 /ayuda – Más información ℹ️  \n\n"
            "⏳ *Tu solicitud será atendida pronto. ¡Gracias por tu paciencia!* 🙌"
        )
        try:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')
            logger.info(f"Confirmación enviada a {username}")
        except telegram.error.BadRequest as e:
            bot.send_message(chat_id=chat_id, text=confirmacion_message.replace('*', ''))
            logger.error(f"Error al enviar confirmación con Markdown: {str(e)}")

# Comando /on con botones
def handle_on(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /on recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
        return

    keyboard = []
    for grupo_id in grupos_activos:
        title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}",
                                             callback_data=f"on_{grupo_id}")])
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="on_confirmar")])
    keyboard.append([InlineKeyboardButton("🔙 Retroceder", callback_data="on_retroceder")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    grupos_seleccionados[chat_id] = {"accion": "on", "grupos": set(), "mensaje_id": None}
    sent_message = bot.send_message(chat_id=chat_id,
                                    text="🟢 *Activar solicitudes* 🌟\nSelecciona los grupos para activar las solicitudes (puedes elegir varios):",
                                    reply_markup=reply_markup, parse_mode='Markdown')
    grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id

# Comando /off con botones
def handle_off(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /off recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
        return

    keyboard = []
    for grupo_id in grupos_activos:
        title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}",
                                             callback_data=f"off_{grupo_id}")])
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="off_confirmar")])
    keyboard.append([InlineKeyboardButton("🔙 Retroceder", callback_data="off_retroceder")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    grupos_seleccionados[chat_id] = {"accion": "off", "grupos": set(), "mensaje_id": None}
    sent_message = bot.send_message(chat_id=chat_id,
                                    text="🔴 *Desactivar solicitudes* 🌟\nSelecciona los grupos para desactivar las solicitudes (puedes elegir varios):",
                                    reply_markup=reply_markup, parse_mode='Markdown')
    grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id

# Comando /grupos
def handle_grupos(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /grupos recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not grupos_estados:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
        return

    estado = "\n".join([f"🏠 {info['title']}: {'🟢 Activo' if info['activo'] else '🔴 Inactivo'} (ID: {gid})"
                        for gid, info in sorted(grupos_estados.items(), key=lambda x: x[1]['title'])])
    keyboard = [[InlineKeyboardButton("🔙 Retroceder", callback_data="grupos_retroceder")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id,
                     text=f"📋 *Estado de los grupos* 🌟\n{estado}",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /pendientes con botones
def handle_pendientes(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /pendientes recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not peticiones_registradas:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes. 🌟")
        return

    keyboard = []
    for ticket, info in sorted(peticiones_registradas.items(), key=lambda x: x[0]):
        keyboard.append([InlineKeyboardButton(f"#{ticket} - {info['username']} ({info['chat_title']})",
                                             callback_data=f"pend_{ticket}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(chat_id=chat_id,
                     text="📋 *Solicitudes pendientes* 🌟\nSelecciona una solicitud para gestionarla:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /eliminar con botones
def handle_eliminar(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /eliminar recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not peticiones_registradas:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes para eliminar. 🌟")
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
    if not update or not update.message:
        logger.warning("Mensaje /ping recibido es None")
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    bot.send_message(chat_id=chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')

# Manejo de botones
def button_handler(update, context):
    query = update.callback_query
    if not query:
        logger.warning("CallbackQuery recibido es None")
        return
    query.answer()
    data = query.data
    chat_id = query.message.chat_id
    mensaje_id = query.message.message_id
    current_text = query.message.text
    current_markup = query.message.reply_markup

    # Manejo de Retroceder para /on, /off, /grupos
    if data in ["on_retroceder", "off_retroceder", "grupos_retroceder"]:
        if data == "on_retroceder":
            handle_on(update, context)
        elif data == "off_retroceder":
            handle_off(update, context)
        elif data == "grupos_retroceder":
            handle_grupos(update, context)
        return

    # Manejo de /on y /off
    if data.startswith("on_") or data.startswith("off_"):
        if not (data.startswith("on_") or data.startswith("off_")) or "_" not in data:
            logger.error(f"Datos de callback inválidos: {data}")
            return

        accion, grupo_id_str = data.split("_", 1)
        try:
            grupo_id = int(grupo_id_str)
        except ValueError:
            logger.error(f"Error al convertir grupo_id a entero: {grupo_id_str}")
            return

        if chat_id in grupos_seleccionados and mensaje_id == grupos_seleccionados[chat_id]["mensaje_id"]:
            title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
            if grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                grupos_seleccionados[chat_id]["grupos"].remove(grupo_id)
                texto = current_text.replace(f"\n{'🟢' if accion == 'on' else '🔴'} {title} seleccionado.", "")
            else:
                grupos_seleccionados[chat_id]["grupos"].add(grupo_id)
                texto = current_text + f"\n{'🟢' if accion == 'on' else '🔴'} {title} seleccionado."

            keyboard = []
            for gid in grupos_activos:
                title = grupos_estados.get(gid, {}).get("title", f"Grupo {gid}")
                seleccionado = gid in grupos_seleccionados[chat_id]["grupos"]
                keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(gid, {}).get('activo', True) else '🔴'}{' ✅' if seleccionado else ''}",
                                                     callback_data=f"{accion}_{gid}")])
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"{accion}_confirmar")])
            keyboard.append([InlineKeyboardButton("🔙 Retroceder", callback_data=f"{accion}_retroceder")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "on_confirmar" or data == "off_confirmar":
        accion = "on" if data == "on_confirmar" else "off"
        if chat_id not in grupos_seleccionados or not grupos_seleccionados[chat_id]["grupos"]:
            query.edit_message_text(text=f"ℹ️ No se seleccionaron grupos para {'activar' if accion == 'on' else 'desactivar'}. 🌟", parse_mode='Markdown')
            if chat_id in grupos_seleccionados:
                del grupos_seleccionados[chat_id]
            return

        for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
            grupos_estados[grupo_id]["activo"] = (accion == "on")

        keyboard = [
            [InlineKeyboardButton("✅ Sí", callback_data=f"{accion}_notificar_sí")],
            [InlineKeyboardButton("❌ No", callback_data=f"{accion}_notificar_no")],
            [InlineKeyboardButton("🔙 Retroceder", callback_data=f"{accion}_retroceder")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        grupos = "\n".join([grupos_estados[gid]["title"] for gid in grupos_seleccionados[chat_id]["grupos"]])
        texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'}* 🌟\n" \
                f"Grupos afectados:\n{grupos}\n\n¿Enviar notificación a los grupos seleccionados?"
        query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data.startswith("on_notificar_") or data.startswith("off_notificar_"):
        accion, decision = data.split("_notificar_")
        if decision == "sí":
            mensaje = (
                "🎉 *¡Solicitudes reactivadas!* 🌟\nYa se pueden enviar solicitudes.\nMáximo 2 por día por usuario. 🙌"
            ) if accion == "on" else (
                "🚫 *Solicitudes desactivadas* 🌟\nNo se aceptan nuevas solicitudes hasta nuevo aviso.\nDisculpen las molestias. 🙏"
            )
            for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                try:
                    bot.send_message(chat_id=grupo_id, text=mensaje, parse_mode='Markdown')
                    logger.info(f"Notificación /{accion} enviada a {grupo_id}")
                except telegram.error.TelegramError as e:
                    logger.error(f"Error al notificar /{accion} a {grupo_id}: {str(e)}")
            query.edit_message_text(
                text=f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} y notificadas.* 🌟",
                parse_mode='Markdown')
            del grupos_seleccionados[chat_id]
        elif decision == "no":
            query.edit_message_text(
                text=f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} sin notificación.* 🌟",
                parse_mode='Markdown')
            del grupos_seleccionados[chat_id]
        elif decision == "retroceder":
            keyboard = []
            for grupo_id in grupos_activos:
                title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
                seleccionado = grupo_id in grupos_seleccionados[chat_id]["grupos"]
                keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}{' ✅' if seleccionado else ''}",
                                                     callback_data=f"{accion}_{grupo_id}")])
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"{accion}_confirmar")])
            keyboard.append([InlineKeyboardButton("🔙 Retroceder", callback_data=f"{accion}_retroceder")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"{'🟢' if accion == 'on' else '🔴'} *{'Activar' if accion == 'on' else 'Desactivar'} solicitudes* 🌟\nSelecciona los grupos (puedes elegir varios):"
            for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                grupos_estados[grupo_id]["activo"] = not (accion == "on")  # Revertir cambios
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
        keyboard = [
            [InlineKeyboardButton("✅ Subido", callback_data=f"pend_{ticket}_subido")],
            [InlineKeyboardButton("❌ Denegado", callback_data=f"pend_{ticket}_denegado")],
            [InlineKeyboardButton("🗑️ Eliminar", callback_data=f"pend_{ticket}_eliminar")],
            [InlineKeyboardButton("📢 Notificar", callback_data=f"pend_{ticket}_notificar")],
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
        query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data.startswith("pend_") and len(data.split("_")) > 2:
        try:
            ticket = int(data.split("_")[1])
            accion = data.split("_")[2]
        except (IndexError, ValueError):
            logger.error(f"Error al procesar pend_ callback: {data}")
            return

        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

        info = peticiones_registradas[ticket]
        username_escaped = escape_markdown(info["username"], True)
        message_text_escaped = escape_markdown(info["message_text"])
        user_chat_id = info["chat_id"]
        message_id = info["message_id"]

        if accion == "subido":
            notificacion = f"✅ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido subida. 🎉"
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
            bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como subido. 🌟")
            del peticiones_registradas[ticket]
            query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como subido.* 🌟", parse_mode='Markdown')

        elif accion == "denegado":
            notificacion = f"❌ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada. 🌟"
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
            bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como denegado. 🌟")
            del peticiones_registradas[ticket]
            query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como denegado.* 🌟", parse_mode='Markdown')

        elif accion == "eliminar":
            try:
                bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
                bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} de {username_escaped} eliminado. 🌟")
            except telegram.error.TelegramError as e:
                bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos. 🌟")
            notificacion = f"ℹ️ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada. 🌟"
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
            del peticiones_registradas[ticket]
            query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como eliminado.* 🌟", parse_mode='Markdown')

        elif accion == "notificar":
            keyboard = [
                [InlineKeyboardButton("🔙 Regresar", callback_data=f"pend_{ticket}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"📢 *Notificar Ticket #{ticket}* 🌟\nEscribe el mensaje a enviar a {username_escaped} (responde a este mensaje):"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            context.user_data["notificar_ticket"] = ticket
            return

    # Manejo de /eliminar
    if data.startswith("eliminar_"):
        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar eliminar_ callback: {data}")
            return

        keyboard = [
            [InlineKeyboardButton("✅ Aprobada", callback_data=f"eliminar_{ticket}_aprobada")],
            [InlineKeyboardButton("❌ Denegada", callback_data=f"eliminar_{ticket}_denegada")],
            [InlineKeyboardButton("🗑️ Eliminada", callback_data=f"eliminar_{ticket}_eliminada")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        texto = f"🗑️ *Eliminar Ticket #{ticket}* 🌟\nSelecciona el estado:"
        query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("eliminar_") and len(data.split("_")) > 2:
        try:
            ticket = int(data.split("_")[1])
            estado = data.split("_")[2]
        except (IndexError, ValueError):
            logger.error(f"Error al procesar eliminar_ callback: {data}")
            return

        if ticket not in peticiones_registradas:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

        peticion_info = peticiones_registradas[ticket]
        user_chat_id = peticion_info["chat_id"]
        username = peticion_info["username"]
        message_text = peticion_info["message_text"]
        message_id = peticion_info["message_id"]

        username_escaped = escape_markdown(username, preserve_username=True)
        message_text_escaped = escape_markdown(message_text)

        try:
            bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
            bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} de {username_escaped} eliminado ({estado}). 🌟")
        except telegram.error.TelegramError as e:
            bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos. 🌟")

        if estado == "aprobada":
            notificacion = f"✅ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido aprobada. 🎉"
        elif estado == "denegada":
            notificacion = f"❌ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada. 🌟"
        else:
            notificacion = f"ℹ️ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada. 🌟"

        try:
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
        except telegram.error.TelegramError as e:
            bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo notificar a {username_escaped}: {str(e)}. 🌟")

        del peticiones_registradas[ticket]
        query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como {estado}.* 🌟", parse_mode='Markdown')

# Comando /subido
def handle_subido(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /subido recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /subido [ticket] 🌟")
        return
    try:
        ticket = int(args[0])
        if ticket not in peticiones_registradas:
            bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟")
            return
        info = peticiones_registradas[ticket]
        bot.send_message(chat_id=info["chat_id"],
                         text=f"✅ {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido subida. 🎉",
                         parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como subido. 🌟")
        del peticiones_registradas[ticket]
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

# Comando /denegado
def handle_denegado(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /denegado recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /denegado [ticket] 🌟")
        return
    try:
        ticket = int(args[0])
        if ticket not in peticiones_registradas:
            bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟")
            return
        info = peticiones_registradas[ticket]
        bot.send_message(chat_id=info["chat_id"],
                         text=f"❌ {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido denegada. 🌟",
                         parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como denegado. 🌟")
        del peticiones_registradas[ticket]
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

# Comando /notificar (manual)
def handle_notificar(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /notificar recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    args = context.args
    if len(args) < 2:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /notificar [username] [mensaje] 🌟")
        return
    username = args[0]
    msg = " ".join(args[1:])
    user_chat_id = next((info["chat_id"] for info in peticiones_registradas.values() if info["username"] == username), None)
    if user_chat_id:
        bot.send_message(chat_id=user_chat_id, text=f"📢 *Notificación* 🌟\n{msg}", parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ Enviada notificación a {username}. 🌟")
    else:
        bot.send_message(chat_id=chat_id, text=f"❌ {username} no encontrado. 🌟")

# Manejo de respuestas para notificaciones desde /pendientes
def handle_notificar_respuesta(update, context):
    if not update or not update.message or "notificar_ticket" not in context.user_data:
        return

    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        return

    ticket = context.user_data["notificar_ticket"]
    if ticket not in peticiones_registradas:
        bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟")
        del context.user_data["notificar_ticket"]
        return

    info = peticiones_registradas[ticket]
    username_escaped = escape_markdown(info["username"], True)
    mensaje = message.text
    bot.send_message(chat_id=info["chat_id"],
                     text=f"📢 *Notificación* 🌟\n{mensaje}",
                     parse_mode='Markdown')
    bot.send_message(chat_id=chat_id,
                     text=f"✅ Enviada notificación a {username_escaped} para Ticket #{ticket}. 🌟")
    del context.user_data["notificar_ticket"]

# Comando /menu
def handle_menu(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /menu recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    menu_message = (
        "📋 *Menú de comandos* 🌟\n"
        "🔧 *Usuarios:*\n"
        "✅ */solicito*, *#solicito*, */peticion*, *#peticion* - Enviar solicitud (máx. 2/día).\n"
        "🔍 */estado [ticket]* - Consultar estado.\n"
        "📖 */ayuda* - Guía rápida.\n"
        "🔧 *Comandos en grupo destino:*\n"
        "📋 */pendientes* - Gestionar solicitudes con botones.\n"
        "🗑️ */eliminar* - Eliminar solicitud con botones.\n"
        "✅ */subido [ticket]* - Marcar como subida.\n"
        "❌ */denegado [ticket]* - Marcar como denegada.\n"
        "📢 */notificar [username] [mensaje]* - Enviar mensaje.\n"
        "🟢 */on* - Activar solicitudes.\n"
        "🔴 */off* - Desactivar solicitudes.\n"
        "🏠 */grupos* - Ver estado de grupos.\n"
        "🏓 */ping* - Verificar si el bot está vivo.\n"
        "🌟 *Bot de Entreshijos*"
    )
    bot.send_message(chat_id=chat_id, text=menu_message, parse_mode='Markdown')

# Comando /ayuda
def handle_ayuda(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /ayuda recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    username = escape_markdown(f"@{message.from_user.username}", True) if message.from_user.username else "Usuario"
    ayuda_message = (
        "📖 *Guía rápida* 🌟\n"
        f"Hola {username}, usa */solicito*, *#solicito*, */peticion* o *#peticion* para enviar una solicitud (máx. 2/día).\n"
        "🔍 */estado [ticket]* - Consulta el estado.\n"
        "🌟 *¡Gracias por usar el bot!* 🙌"
    )
    bot.send_message(chat_id=chat_id, text=ayuda_message, parse_mode='Markdown')

# Comando /estado
def handle_estado(update, context):
    if not update or not update.message:
        logger.warning("Mensaje /estado recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    username = escape_markdown(f"@{message.from_user.username}", True) if message.from_user.username else "Usuario"
    args = context.args
    if not args:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /estado [ticket] 🌟")
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
        else:
            estado_message = f"📋 *Estado* 🌟\nTicket #{ticket}: Gestionada o eliminada. ✅"
        bot.send_message(chat_id=chat_id, text=estado_message, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

# Añadir handlers
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
dispatcher.add_handler(CommandHandler('on', handle_on))
dispatcher.add_handler(CommandHandler('off', handle_off))
dispatcher.add_handler(CommandHandler('grupos', handle_grupos))
dispatcher.add_handler(CommandHandler('pendientes', handle_pendientes))
dispatcher.add_handler(CommandHandler('eliminar', handle_eliminar))
dispatcher.add_handler(CommandHandler('ping', handle_ping))
dispatcher.add_handler(CommandHandler('subido', handle_subido))
dispatcher.add_handler(CommandHandler('denegado', handle_denegado))
dispatcher.add_handler(CommandHandler('notificar', handle_notificar))
dispatcher.add_handler(CommandHandler('menu', handle_menu))
dispatcher.add_handler(CommandHandler('ayuda', handle_ayuda))
dispatcher.add_handler(CommandHandler('estado', handle_estado))
dispatcher.add_handler(CallbackQueryHandler(button_handler))
dispatcher.add_handler(MessageHandler(Filters.reply & Filters.text & ~Filters.command, handle_notificar_respuesta))

# Rutas Flask
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update_json = request.get_json(force=True)
        if not update_json:
            logger.error("No se recibió JSON válido")
            return 'No JSON', 400
        update = telegram.Update.de_json(update_json, bot)
        if not update:
            logger.error("No se pudo deserializar la actualización")
            return 'Invalid update', 400
        dispatcher.process_update(update)
        return 'ok', 200
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return f'Error: {str(e)}', 500

@app.route('/')
def health_check():
    return "Bot de Entreshijos está activo! 🌟", 200

if __name__ == '__main__':
    logger.info("Iniciando bot en modo local")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
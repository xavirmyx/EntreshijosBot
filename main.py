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
admin_ids = set([12345678])  # Lista de IDs de administradores (ajusta según tus admins)
grupos_estados = {}  # {chat_id: {"activo": True/False, "title": "Nombre del grupo"}}
grupos_activos = set()  # Almacena los chat_ids de los grupos donde está el bot

# Frases de agradecimiento aleatorias
frases_agradecimiento = [
    "¡Gracias por tu paciencia! 🙌",
    "¡Agradecemos tu confianza! 💖",
    "¡Tu apoyo es valioso! 🌟",
    "¡Gracias por usar el bot! 🎉"
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
def update_grupos_estados(chat_id, title):
    if chat_id not in grupos_estados:
        grupos_estados[chat_id] = {"activo": True, "title": title}
    else:
        grupos_estados[chat_id]["title"] = title

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
    update_grupos_estados(chat_id, chat_title)
    logger.info(f"Grupo activo registrado: {chat_id}")

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

        if user_id in admin_ids:
            pass
        else:
            if user_id not in peticiones_por_usuario:
                peticiones_por_usuario[user_id] = {"count": 0, "chat_id": chat_id, "username": username}
            peticiones_por_usuario[user_id]["count"] += 1

            if peticiones_por_usuario[user_id]["count"] > 2:
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
            "✅ *Solicitud enviada con éxito* 🎉\n"
            f"Hola {username_escaped}, tu solicitud ha sido registrada con *ticket #{ticket_number}*.\n"
            f"👤 *ID:* {user_id}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp}\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🌟 {random.choice(frases_agradecimiento)}\n\n"
            "📌 *Comandos útiles:*\n"
            "🔍 */estado {ticket_number}* - Consulta el estado.\n"
            "📖 */ayuda* - Más información.\n"
            "⏳ *Ten paciencia, pronto será atendida.*"
        )
        try:
            bot.send_message(chat_id=chat_id, text=confirmacion_message, parse_mode='Markdown')
            logger.info(f"Confirmación enviada a {username}")
        except telegram.error.BadRequest as e:
            bot.send_message(chat_id=chat_id, text=confirmacion_message.replace('*', ''))
            logger.error(f"Error al enviar confirmación con Markdown: {str(e)}")

# Comando /on con botones
def handle_on(update, context):
    if not update.message:
        logger.warning("Mensaje /on recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        return
    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Solo administradores pueden usar este comando. 🌟")
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
        return

    keyboard = []
    for grupo_id in grupos_activos:
        title = grupos_estados.get(grupo_id, {}).get("title", "Grupo desconocido")
        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}",
                                             callback_data=f"on_{grupo_id}")])
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="on_confirmar")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(chat_id=chat_id,
                     text="🟢 *Activar solicitudes* 🌟\nSelecciona los grupos para activar las solicitudes:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /off con botones
def handle_off(update, context):
    if not update.message:
        logger.warning("Mensaje /off recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        return
    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Solo administradores pueden usar este comando. 🌟")
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
        return

    keyboard = []
    for grupo_id in grupos_activos:
        title = grupos_estados.get(grupo_id, {}).get("title", "Grupo desconocido")
        keyboard.append([InlineKeyboardButton(f"{title} {'🟢' if grupos_estados.get(grupo_id, {}).get('activo', True) else '🔴'}",
                                             callback_data=f"off_{grupo_id}")])
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="off_confirmar")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(chat_id=chat_id,
                     text="🔴 *Desactivar solicitudes* 🌟\nSelecciona los grupos para desactivar las solicitudes:",
                     reply_markup=reply_markup, parse_mode='Markdown')

# Comando /grupos
def handle_grupos(update, context):
    if not update.message:
        logger.warning("Mensaje /grupos recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        return
    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Solo administradores pueden usar este comando. 🌟")
        return

    if not grupos_estados:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
        return

    estado = "\n".join([f"🏠 {info['title']}: {'🟢 Activo' if info['activo'] else '🔴 Inactivo'} (ID: {gid})"
                        for gid, info in grupos_estados.items()])
    bot.send_message(chat_id=chat_id,
                     text=f"📋 *Estado de los grupos* 🌟\n{estado}",
                     parse_mode='Markdown')

# Comando /eliminar con botones
def handle_eliminar(update, context):
    if not update.message:
        logger.warning("Mensaje /eliminar recibido es None")
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        return
    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Solo administradores pueden usar este comando. 🌟")
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

# Manejo de botones
def button_handler(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("on_") or data.startswith("off_"):
        accion, grupo_id = data.split("_")
        grupo_id = int(grupo_id)
        if accion == "on":
            grupos_estados[grupo_id]["activo"] = True
            query.edit_message_text(text=query.message.text + f"\n✅ {grupos_estados[grupo_id]['title']} activado.")
        else:
            grupos_estados[grupo_id]["activo"] = False
            query.edit_message_text(text=query.message.text + f"\n❌ {grupos_estados[grupo_id]['title']} desactivado.")
        return

    if data == "on_confirmar":
        on_message = (
            "🎉 *¡Solicitudes reactivadas!* 🌟\n"
            "Se pueden enviar solicitudes en los grupos activados.\n"
            "Máximo 2 por día por usuario. 🙌"
        )
        for grupo_id, info in grupos_estados.items():
            if info["activo"]:
                try:
                    bot.send_message(chat_id=grupo_id, text=on_message, parse_mode='Markdown')
                    logger.info(f"Notificación /on enviada a {grupo_id}")
                except telegram.error.TelegramError as e:
                    logger.error(f"Error al notificar /on a {grupo_id}: {str(e)}")
        query.edit_message_text(text="🟢 *Solicitudes activadas en los grupos seleccionados.* 🌟", parse_mode='Markdown')

    elif data == "off_confirmar":
        off_message = (
            "🚫 *Solicitudes desactivadas* 🌟\n"
            "No se aceptan nuevas solicitudes hasta nuevo aviso.\n"
            "Disculpen las molestias. 🙏"
        )
        for grupo_id, info in grupos_estados.items():
            if not info["activo"]:
                try:
                    bot.send_message(chat_id=grupo_id, text=off_message, parse_mode='Markdown')
                    logger.info(f"Notificación /off enviada a {grupo_id}")
                except telegram.error.TelegramError as e:
                    logger.error(f"Error al notificar /off a {grupo_id}: {str(e)}")
        query.edit_message_text(text="🔴 *Solicitudes desactivadas en los grupos seleccionados.* 🌟", parse_mode='Markdown')

    elif data.startswith("eliminar_"):
        ticket = int(data.split("_")[1])
        keyboard = [
            [InlineKeyboardButton("✅ Aprobada", callback_data=f"eliminar_{ticket}_aprobada")],
            [InlineKeyboardButton("❌ Denegada", callback_data=f"eliminar_{ticket}_denegada")],
            [InlineKeyboardButton("🗑️ Eliminada", callback_data=f"eliminar_{ticket}_eliminada")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            text=f"🗑️ *Eliminar Ticket #{ticket}* 🌟\nSelecciona el estado:",
            reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("eliminar_") and "_" in data.split("_", 2)[2]:
        ticket, estado = data.split("_")[1:]
        ticket = int(ticket)
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

# Añadir handlers
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
dispatcher.add_handler(CommandHandler('on', handle_on))
dispatcher.add_handler(CommandHandler('off', handle_off))
dispatcher.add_handler(CommandHandler('grupos', handle_grupos))
dispatcher.add_handler(CommandHandler('eliminar', handle_eliminar))
dispatcher.add_handler(CallbackQueryHandler(button_handler))
dispatcher.add_handler(CommandHandler('subido', lambda u, c: handle_subido(u, c)))  # Mantener los originales
dispatcher.add_handler(CommandHandler('denegado', lambda u, c: handle_denegado(u, c)))
dispatcher.add_handler(CommandHandler('menu', lambda u, c: handle_menu(u, c)))
dispatcher.add_handler(CommandHandler('pendientes', lambda u, c: handle_pendientes(u, c)))
dispatcher.add_handler(CommandHandler('ayuda', lambda u, c: handle_ayuda(u, c)))
dispatcher.add_handler(CommandHandler('estado', lambda u, c: handle_estado(u, c)))
dispatcher.add_handler(CommandHandler('notificar', lambda u, c: handle_notificar(u, c)))

# Funciones originales (sin cambios significativos, solo mejoras menores)
def handle_subido(update, context):
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO or message.from_user.id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Comando restringido al grupo destino y administradores. 🌟")
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
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

def handle_denegado(update, context):
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO or message.from_user.id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Comando restringido al grupo destino y administradores. 🌟")
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
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

def handle_menu(update, context):
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        return
    menu_message = (
        "📋 *Menú de comandos* 🌟\n"
        "🔧 *Usuarios:*\n"
        "✅ */solicito* o *#solicito* - Enviar solicitud (máx. 2/día).\n"
        "🔍 */estado [ticket]* - Consultar estado.\n"
        "📖 */ayuda* - Guía rápida.\n"
        "🔧 *Administradores:*\n"
        "🗑️ */eliminar* - Eliminar solicitud con botones.\n"
        "✅ */subido [ticket]* - Marcar como subida.\n"
        "❌ */denegado [ticket]* - Marcar como denegada.\n"
        "📢 */notificar [username] [mensaje]* - Enviar mensaje.\n"
        "📋 */pendientes* - Ver solicitudes pendientes.\n"
        "🟢 */on* - Activar solicitudes.\n"
        "🔴 */off* - Desactivar solicitudes.\n"
        "🏠 */grupos* - Ver estado de grupos.\n"
        "🌟 *Bot de Entreshijos*"
    )
    bot.send_message(chat_id=chat_id, text=menu_message, parse_mode='Markdown')

def handle_pendientes(update, context):
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO or message.from_user.id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Comando restringido al grupo destino y administradores. 🌟")
        return
    pendientes = [f"#{k} - {v['username']}: {escape_markdown(v['message_text'])} ({v['chat_title']})"
                  for k, v in peticiones_registradas.items()]
    respuesta = "📋 *Solicitudes pendientes* 🌟\n" + "\n".join(pendientes) if pendientes else "ℹ️ Sin pendientes. 🌟"
    bot.send_message(chat_id=chat_id, text=respuesta, parse_mode='Markdown')

def handle_ayuda(update, context):
    message = update.message
    chat_id = message.chat_id
    username = escape_markdown(f"@{message.from_user.username}", True) if message.from_user.username else "Usuario"
    ayuda_message = (
        "📖 *Guía rápida* 🌟\n"
        f"Hola {username}, usa */solicito* o *#solicito* para enviar una solicitud (máx. 2/día).\n"
        "🔍 */estado [ticket]* - Consulta el estado.\n"
        "🌟 *¡Gracias por usar el bot!* 🙌"
    )
    bot.send_message(chat_id=chat_id, text=ayuda_message, parse_mode='Markdown')

def handle_estado(update, context):
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

def handle_notificar(update, context):
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO or message.from_user.id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Comando restringido al grupo destino y administradores. 🌟")
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
# handlers.py
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, CommandHandler, Filters, CallbackQueryHandler, ConversationHandler
from datetime import datetime, timedelta
from database import (get_peticiones_por_usuario, set_peticiones_por_usuario, get_user_id_by_username,
                     get_peticion_registrada, set_peticion_registrada, del_peticion_registrada,
                     get_historial_solicitud, set_historial_solicitud, get_grupos_estados,
                     set_grupo_estado, get_peticiones_incorrectas, add_peticion_incorrecta,
                     clean_database, get_advanced_stats, increment_ticket_counter)
from utils import escape_markdown, update_grupos_estados, get_spain_time, menu_activos, grupos_seleccionados
from config import (GROUP_DESTINO, CANALES_PETICIONES, VALID_REQUEST_COMMANDS, frases_agradecimiento,
                    ping_respuestas, admin_ids)
import random
import re

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración de zona horaria
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Estados para la conversación de búsqueda y URL
TICKET_SEARCH, URL_INPUT, NO_URL_CONFIRM = range(3)

# Función para manejar métodos del bot con reintentos
def safe_bot_method(method, retries=3, delay=1, *args, **kwargs):
    for attempt in range(retries):
        try:
            return method(*args, **kwargs)
        except Exception as e:
            logger.error(f"Intento {attempt + 1} fallido: {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"Error persistente: {str(e)}")
                return None

# Handler para mensajes de solicitud
def handle_message(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    chat_type = message.chat.type
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'
    thread_id = message.message_thread_id
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})

    update_grupos_estados(chat_id, chat_type, chat_title, set_grupo_estado, get_grupos_estados, GROUP_DESTINO)

    timestamp = datetime.now(SPAIN_TZ)
    timestamp_str = get_spain_time()
    username_escaped = escape_markdown(username, preserve_username=True)
    chat_title_escaped = escape_markdown(chat_title)
    message_text_escaped = escape_markdown(message_text)

    is_valid_request = any(cmd in message_text for cmd in VALID_REQUEST_COMMANDS)
    grupos_estados = get_grupos_estados()

    if is_valid_request:
        logger.info(f"Solicitud recibida de {username} en {chat_title}: {message_text}")
        if chat_id not in CANALES_PETICIONES or thread_id != CANALES_PETICIONES[chat_id]["thread_id"]:
            notificacion = f"🚫 {username_escaped}, las solicitudes solo son válidas en el canal de peticiones correspondiente. 🌟"
            warn_message = f"/warn {username_escaped} (Petición fuera del canal correspondiente)"
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=notificacion, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=warn_message, message_thread_id=canal_info["thread_id"])
            return

        if not grupos_estados.get(chat_id, {}).get("activo", True):
            notificacion = f"🚫 {username_escaped}, las solicitudes están desactivadas en este grupo. Contacta a un administrador. 🌟"
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=notificacion, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            return

        user_data = get_peticiones_por_usuario(user_id)
        if not user_data:
            set_peticiones_por_usuario(user_id, 0, chat_id, username)
            user_data = {"count": 0, "chat_id": chat_id, "username": username}
        elif user_data["count"] >= 2 and user_id not in admin_ids:
            limite_message = f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta mañana. 🌟"
            warn_message = f"/warn {username_escaped} (Límite de peticiones diarias superado)"
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=limite_message, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=warn_message, message_thread_id=canal_info["thread_id"])
            return

        ticket_number = increment_ticket_counter()
        destino_message = (
            f"📬 *Nueva solicitud recibida* 🌟\n"
            f"👤 *Usuario:* {username_escaped} (ID: {user_id})\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp_str}\n"
            "🌟 *Bot de Entreshijos*"
        )
        sent_message = safe_bot_method(context.bot.send_message, chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
        if sent_message:
            set_peticion_registrada(ticket_number, {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": timestamp,
                "chat_title": chat_title,
                "thread_id": thread_id
            })

        user_data["count"] += 1
        set_peticiones_por_usuario(user_id, user_data["count"], user_data["chat_id"], user_data["username"])

        destino_message = (
            f"📬 *Nueva solicitud recibida* 🌟\n"
            f"👤 *Usuario:* {username_escaped} (ID: {user_id})\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"📊 *Petición:* {user_data['count']}/2\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp_str}\n"
            "🌟 *Bot de Entreshijos*"
        )
        if sent_message:
            safe_bot_method(context.bot.edit_message_text, chat_id=GROUP_DESTINO, message_id=sent_message.message_id, text=destino_message, parse_mode='Markdown')

        confirmacion_message = (
            f"✅ *Solicitud registrada* 🎉\n"
            f"Hola {username_escaped}, tu solicitud (Ticket #{ticket_number}) ha sido registrada.\n"
            f"📌 *Detalles:*\n"
            f"🆔 ID: {user_id}\n"
            f"🏠 Grupo: {chat_title_escaped}\n"
            f"📅 Fecha: {timestamp_str}\n"
            f"📝 Mensaje: {message_text_escaped}\n"
            "⏳ Será atendida pronto. 🙌"
        )
        safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=confirmacion_message, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])

    elif any(word in message_text.lower() for word in ['solicito', 'solícito', 'peticion', 'petición']) and chat_id in CANALES_PETICIONES:
        add_peticion_incorrecta(user_id, timestamp, chat_id)
        intentos_recientes = [i for i in get_peticiones_incorrectas(user_id) 
                            if i["timestamp"].astimezone(SPAIN_TZ) > timestamp - timedelta(hours=24)]

        notificacion_incorrecta = (
            f"⚠️ {username_escaped}, usa solo: {', '.join(VALID_REQUEST_COMMANDS)}.\n"
            "Consulta /ayuda para más detalles. 🌟"
        )
        warn_message = f"/warn {username_escaped} (Petición mal formulada)" if len(intentos_recientes) <= 2 else f"/warn {username_escaped} (Abuso de peticiones mal formuladas)"

        safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=notificacion_incorrecta, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
        safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=warn_message, message_thread_id=canal_info["thread_id"])

# Handler para el comando /menu
def handle_menu(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    admin_username = f"@{message.from_user.username}" if message.from_user.username else "Admin sin @"
    if str(chat_id) != GROUP_DESTINO:
        safe_bot_method(context.bot.send_message, chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟", parse_mode='Markdown')
        return

    keyboard = [
        [InlineKeyboardButton("📋 Pendientes", callback_data="menu_pendientes")],
        [InlineKeyboardButton("📜 Historial", callback_data="menu_historial")],
        [InlineKeyboardButton("📊 Gráficas", callback_data="menu_graficas")],
        [InlineKeyboardButton("🏠 Grupos", callback_data="menu_grupos")],
        [InlineKeyboardButton("🟢 Activar", callback_data="menu_on"), InlineKeyboardButton("🔴 Desactivar", callback_data="menu_off")],
        [InlineKeyboardButton("➕ Sumar", callback_data="menu_sumar"), InlineKeyboardButton("➖ Restar", callback_data="menu_restar")],
        [InlineKeyboardButton("🧹 Limpiar", callback_data="menu_clean"), InlineKeyboardButton("🏓 Ping", callback_data="menu_ping")],
        [InlineKeyboardButton("📈 Stats", callback_data="menu_stats"), InlineKeyboardButton("🔍 Buscar", callback_data="menu_search")],
        [InlineKeyboardButton("📉 Priorizar", callback_data="menu_prioritize"), InlineKeyboardButton("📊 Mis Stats", callback_data="menu_mystats")],
        [InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"👤 {admin_username}\n📋 *Menú Principal* 🌟\nSelecciona una opción:"
    sent_message = safe_bot_method(context.bot.send_message, chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
    if sent_message:
        menu_activos[(chat_id, sent_message.message_id)] = datetime.now(SPAIN_TZ)

# Handler para el comando /ping
def handle_ping(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    response = random.choice(ping_respuestas)
    safe_bot_method(context.bot.send_message, chat_id=chat_id, text=response, parse_mode='Markdown')

# Handler para el comando /mystats
def handle_mystats(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    username_escaped = escape_markdown(username, preserve_username=True)

    user_data = get_peticiones_por_usuario(user_id)
    if not user_data:
        text = f"👤 {username_escaped}\n📊 *Tus estadísticas* 🌟\nNo tienes solicitudes registradas."
    else:
        text = (
            f"👤 {username_escaped}\n📊 *Tus estadísticas* 🌟\n"
            f"📋 *Solicitudes hoy:* {user_data['count']}/2\n"
            f"🕒 *Último reinicio:* {user_data['last_reset'].astimezone(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')}"
        )
    safe_bot_method(context.bot.send_message, chat_id=chat_id, text=text, parse_mode='Markdown')

# Handler para botones
def button_handler(update, context):
    query = update.callback_query
    if not query:
        return
    query.answer()
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    data = query.data
    admin_username = f"@{query.from_user.username}" if query.from_user.username else "Admin sin @"
    admin_username_escaped = escape_markdown(admin_username, preserve_username=True)

    if data == "menu_close":
        safe_bot_method(context.bot.delete_message, chat_id=chat_id, message_id=message_id)
        if (chat_id, message_id) in menu_activos:
            del menu_activos[(chat_id, message_id)]
        return

    if data == "menu_principal":
        keyboard = [
            [InlineKeyboardButton("📋 Pendientes", callback_data="menu_pendientes")],
            [InlineKeyboardButton("📜 Historial", callback_data="menu_historial")],
            [InlineKeyboardButton("📊 Gráficas", callback_data="menu_graficas")],
            [InlineKeyboardButton("🏠 Grupos", callback_data="menu_grupos")],
            [InlineKeyboardButton("🟢 Activar", callback_data="menu_on"), InlineKeyboardButton("🔴 Desactivar", callback_data="menu_off")],
            [InlineKeyboardButton("➕ Sumar", callback_data="menu_sumar"), InlineKeyboardButton("➖ Restar", callback_data="menu_restar")],
            [InlineKeyboardButton("🧹 Limpiar", callback_data="menu_clean"), InlineKeyboardButton("🏓 Ping", callback_data="menu_ping")],
            [InlineKeyboardButton("📈 Stats", callback_data="menu_stats"), InlineKeyboardButton("🔍 Buscar", callback_data="menu_search")],
            [InlineKeyboardButton("📉 Priorizar", callback_data="menu_prioritize"), InlineKeyboardButton("📊 Mis Stats", callback_data="menu_mystats")],
            [InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"👤 {admin_username_escaped}\n📋 *Menú Principal* 🌟\nSelecciona una opción:"
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_grupos":
        grupos = get_grupos_estados()
        text = "📋 *Estado de los grupos* 🌟\n"
        for gid, info in grupos.items():
            estado = "🟢 Activo" if info["activo"] else "🔴 Inactivo"
            text += f"🏠 {escape_markdown(info['title'])}: {estado} (ID: {gid})\n"
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_clean":
        try:
            clean_database()
            text = "🧹 *Base de datos limpiada* 🌟\nSe eliminaron registros obsoletos."
        except Exception as e:
            text = f"❌ *Error al limpiar la base de datos* 🌟\n{str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_stats":
        try:
            stats = get_advanced_stats()
            text = (
                f"📈 *Estadísticas avanzadas* 🌟\n"
                f"📋 *Pendientes:* {stats['pendientes']}\n"
                f"✅ *Gestionadas:* {stats['gestionadas']}\n"
                f"👥 *Usuarios:* {stats['usuarios']}"
            )
        except Exception as e:
            text = f"❌ *Error al obtener estadísticas* 🌟\n{str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_ping":
        response = random.choice(ping_respuestas)
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=response, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_mystats":
        user_id = query.from_user.id
        user_data = get_peticiones_por_usuario(user_id)
        if not user_data:
            text = f"👤 {admin_username_escaped}\n📊 *Tus estadísticas* 🌟\nNo tienes solicitudes registradas."
        else:
            text = (
                f"👤 {admin_username_escaped}\n📊 *Tus estadísticas* 🌟\n"
                f"📋 *Solicitudes hoy:* {user_data['count']}/2\n"
                f"🕒 *Último reinicio:* {user_data['last_reset'].astimezone(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')}"
            )
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_search":
        text = "🔍 *Buscar solicitud* 🌟\nPor favor, envía el número del ticket que deseas buscar (ejemplo: 159)."
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        context.user_data['search_message_id'] = message_id
        return TICKET_SEARCH

    if data == "menu_prioritize":
        # Implementar lógica para priorizar (pendiente de definir cómo priorizar)
        text = "📉 *Priorizar solicitud* 🌟\nEsta función está en desarrollo."
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_pendientes":
        pendientes = []
        conn = get_db_connection()
        try:
            with conn.cursor() as c:
                c.execute("SELECT ticket_number, username, message_text, chat_title, timestamp FROM peticiones_registradas ORDER BY timestamp")
                pendientes = [dict(row) for row in c.fetchall()]
        finally:
            release_db_connection(conn)

        if not pendientes:
            text = "📋 *Pendientes* 🌟\nNo hay solicitudes pendientes."
        else:
            text = "📋 *Pendientes* 🌟\n"
            for p in pendientes[:5]:  # Mostrar solo las primeras 5
                timestamp_str = p['timestamp'].astimezone(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')
                text += (
                    f"🎫 *Ticket:* #{p['ticket_number']}\n"
                    f"👤 *Usuario:* {escape_markdown(p['username'], preserve_username=True)}\n"
                    f"📝 *Mensaje:* {escape_markdown(p['message_text'])}\n"
                    f"🏠 *Grupo:* {escape_markdown(p['chat_title'])}\n"
                    f"🕒 *Fecha:* {timestamp_str}\n\n"
                )
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        for p in pendientes[:5]:
            keyboard.append([
                InlineKeyboardButton(f"✅ Aceptar #{p['ticket_number']}", callback_data=f"aceptar_{p['ticket_number']}"),
                InlineKeyboardButton(f"❌ Rechazar #{p['ticket_number']}", callback_data=f"rechazar_{p['ticket_number']}")
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data.startswith("aceptar_"):
        ticket_number = int(data.split("_")[1])
        peticion = get_peticion_registrada(ticket_number)
        if not peticion:
            text = f"❌ *Error* 🌟\nEl ticket #{ticket_number} no existe o ya fue gestionado."
            keyboard = [
                [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
            return

        context.user_data['ticket_number'] = ticket_number
        context.user_data['peticion'] = peticion
        text = (
            f"✅ *Aceptar solicitud* 🌟\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"¿Deseas incluir una URL para este ticket?"
        )
        keyboard = [
            [InlineKeyboardButton("📎 Con URL", callback_data="con_url"), InlineKeyboardButton("📜 Sin URL", callback_data="sin_url")],
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "con_url":
        ticket_number = context.user_data.get('ticket_number')
        text = (
            f"📎 *Proporciona la URL* 🌟\n"
            f"Envía el enlace del mensaje o archivo subido para el Ticket #{ticket_number}."
        )
        keyboard = [
            [InlineKeyboardButton("🔙 Volver", callback_data=f"aceptar_{ticket_number}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return URL_INPUT

    if data == "sin_url":
        ticket_number = context.user_data.get('ticket_number')
        text = (
            f"📜 *Confirmar sin URL* 🌟\n"
            f"¿Estás seguro de que deseas aceptar el Ticket #{ticket_number} sin una URL?"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirmar_sin_url_{ticket_number}"),
             InlineKeyboardButton("🔙 Volver", callback_data=f"aceptar_{ticket_number}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return NO_URL_CONFIRM

    if data.startswith("confirmar_sin_url_"):
        ticket_number = int(data.split("_")[3])
        peticion = context.user_data.get('peticion')
        if not peticion:
            text = f"❌ *Error* 🌟\nEl ticket #{ticket_number} no existe o ya fue gestionado."
        else:
            set_historial_solicitud(ticket_number, {
                "chat_id": peticion["chat_id"],
                "username": peticion["username"],
                "message_text": peticion["message_text"],
                "chat_title": peticion["chat_title"],
                "estado": "aceptado",
                "fecha_gestion": datetime.now(SPAIN_TZ),
                "admin_username": admin_username,
                "url": None
            })
            del_peticion_registrada(ticket_number)
            text = (
                f"✅ *Solicitud aceptada* 🌟\n"
                f"🎫 *Ticket:* #{ticket_number}\n"
                f"👤 *Usuario:* {escape_markdown(peticion['username'], preserve_username=True)}\n"
                f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
                f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
                f"🕒 *Fecha de gestión:* {get_spain_time()}\n"
                f"👤 *Gestionado por:* {admin_username_escaped}\n"
                f"📜 *Sin URL*"
            )
            canal_info = CANALES_PETICIONES.get(peticion["chat_id"], {"chat_id": peticion["chat_id"], "thread_id": None})
            user_notification = (
                f"✅ *Solicitud aceptada* 🎉\n"
                f"Hola {escape_markdown(peticion['username'], preserve_username=True)}, tu solicitud (Ticket #{ticket_number}) ha sido aceptada.\n"
                f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
                f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
                f"🕒 *Fecha:* {get_spain_time()}\n"
                f"{random.choice(frases_agradecimiento)}"
            )
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=user_notification, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data.startswith("rechazar_"):
        ticket_number = int(data.split("_")[1])
        peticion = get_peticion_registrada(ticket_number)
        if not peticion:
            text = f"❌ *Error* 🌟\nEl ticket #{ticket_number} no existe o ya fue gestionado."
        else:
            set_historial_solicitud(ticket_number, {
                "chat_id": peticion["chat_id"],
                "username": peticion["username"],
                "message_text": peticion["message_text"],
                "chat_title": peticion["chat_title"],
                "estado": "rechazado",
                "fecha_gestion": datetime.now(SPAIN_TZ),
                "admin_username": admin_username,
                "url": None
            })
            del_peticion_registrada(ticket_number)
            text = (
                f"❌ *Solicitud rechazada* 🌟\n"
                f"🎫 *Ticket:* #{ticket_number}\n"
                f"👤 *Usuario:* {escape_markdown(peticion['username'], preserve_username=True)}\n"
                f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
                f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
                f"🕒 *Fecha de gestión:* {get_spain_time()}\n"
                f"👤 *Gestionado por:* {admin_username_escaped}"
            )
            canal_info = CANALES_PETICIONES.get(peticion["chat_id"], {"chat_id": peticion["chat_id"], "thread_id": None})
            user_notification = (
                f"❌ *Solicitud rechazada* 🌟\n"
                f"Hola {escape_markdown(peticion['username'], preserve_username=True)}, tu solicitud (Ticket #{ticket_number}) ha sido rechazada.\n"
                f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
                f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
                f"🕒 *Fecha:* {get_spain_time()}\n"
                f"📌 Contacta a un administrador para más detalles."
            )
            safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=user_notification, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return

# Handler para la entrada de URL
def handle_url_input(update, context):
    if not update.message:
        return ConversationHandler.END

    message = update.message
    chat_id = message.chat_id
    message_text = message.text or ''
    ticket_number = context.user_data.get('ticket_number')
    peticion = context.user_data.get('peticion')
    admin_username = f"@{message.from_user.username}" if message.from_user.username else "Admin sin @"
    admin_username_escaped = escape_markdown(admin_username, preserve_username=True)

    # Validar que el mensaje contenga una URL
    url_pattern = re.compile(r'https?://[^\s]+')
    if not url_pattern.search(message_text):
        text = (
            f"❌ *URL inválida* 🌟\n"
            f"Por favor, envía una URL válida para el Ticket #{ticket_number} (ejemplo: https://t.me/...)."
        )
        keyboard = [
            [InlineKeyboardButton("🔙 Volver", callback_data=f"aceptar_{ticket_number}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=context.user_data['search_message_id'], text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return URL_INPUT

    url = url_pattern.search(message_text).group()
    set_historial_solicitud(ticket_number, {
        "chat_id": peticion["chat_id"],
        "username": peticion["username"],
        "message_text": peticion["message_text"],
        "chat_title": peticion["chat_title"],
        "estado": "aceptado",
        "fecha_gestion": datetime.now(SPAIN_TZ),
        "admin_username": admin_username,
        "url": url
    })
    del_peticion_registrada(ticket_number)
    text = (
        f"✅ *Solicitud aceptada* 🌟\n"
        f"🎫 *Ticket:* #{ticket_number}\n"
        f"👤 *Usuario:* {escape_markdown(peticion['username'], preserve_username=True)}\n"
        f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
        f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
        f"🕒 *Fecha de gestión:* {get_spain_time()}\n"
        f"👤 *Gestionado por:* {admin_username_escaped}\n"
        f"🔗 *URL:* {url}"
    )
    canal_info = CANALES_PETICIONES.get(peticion["chat_id"], {"chat_id": peticion["chat_id"], "thread_id": None})
    user_notification = (
        f"✅ *Solicitud aceptada* 🎉\n"
        f"Hola {escape_markdown(peticion['username'], preserve_username=True)}, tu solicitud (Ticket #{ticket_number}) ha sido aceptada.\n"
        f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
        f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
        f"🕒 *Fecha:* {get_spain_time()}\n"
        f"🔗 *URL:* {url}\n"
        f"{random.choice(frases_agradecimiento)}"
    )
    safe_bot_method(context.bot.send_message, chat_id=canal_info["chat_id"], text=user_notification, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
    keyboard = [
        [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=context.user_data['search_message_id'], text=text, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

# Handler para la búsqueda de tickets
def handle_ticket_search(update, context):
    if not update.message:
        return ConversationHandler.END

    message = update.message
    chat_id = message.chat_id
    message_text = message.text or ''
    admin_username = f"@{message.from_user.username}" if message.from_user.username else "Admin sin @"
    admin_username_escaped = escape_markdown(admin_username, preserve_username=True)

    # Validar que el mensaje sea un número
    if not message_text.isdigit():
        text = (
            f"❌ *Número inválido* 🌟\n"
            f"Por favor, envía un número de ticket válido (ejemplo: 159)."
        )
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=context.user_data['search_message_id'], text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return TICKET_SEARCH

    ticket_number = int(message_text)
    peticion = get_peticion_registrada(ticket_number)
    historial = get_historial_solicitud(ticket_number)

    if not peticion and not historial:
        text = f"❌ *Ticket no encontrado* 🌟\nEl Ticket #{ticket_number} no existe."
    elif peticion:
        timestamp_str = peticion['timestamp'].astimezone(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')
        text = (
            f"🔍 *Estado del Ticket #{ticket_number}* 🌟\n"
            f"📋 *Estado:* Pendiente\n"
            f"👤 *Usuario:* {escape_markdown(peticion['username'], preserve_username=True)}\n"
            f"📝 *Mensaje:* {escape_markdown(peticion['message_text'])}\n"
            f"🏠 *Grupo:* {escape_markdown(peticion['chat_title'])}\n"
            f"🕒 *Fecha:* {timestamp_str}"
        )
    else:  # historial
        timestamp_str = historial['fecha_gestion'].astimezone(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')
        text = (
            f"🔍 *Estado del Ticket #{ticket_number}* 🌟\n"
            f"📋 *Estado:* {historial['estado'].capitalize()}\n"
            f"👤 *Usuario:* {escape_markdown(historial['username'], preserve_username=True)}\n"
            f"📝 *Mensaje:* {escape_markdown(historial['message_text'])}\n"
            f"🏠 *Grupo:* {escape_markdown(historial['chat_title'])}\n"
            f"🕒 *Fecha de gestión:* {timestamp_str}\n"
            f"👤 *Gestionado por:* {escape_markdown(historial['admin_username'], preserve_username=True)}\n"
        )
        if historial.get('url'):
            text += f"🔗 *URL:* {historial['url']}\n"
        else:
            text += f"📜 *Sin URL*\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=context.user_data['search_message_id'], text=text, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

# Handler para cancelar la conversación
def cancel(update, context):
    query = update.callback_query
    if query:
        query.answer()
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        text = "❌ *Operación cancelada* 🌟"
        keyboard = [
            [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        safe_bot_method(context.bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

# Definición de los handlers
def get_handlers():
    return [
        MessageHandler(Filters.text & ~Filters.command, handle_message),
        CommandHandler("menu", handle_menu),
        CommandHandler("ping", handle_ping),
        CommandHandler("mystats", handle_mystats),
        CallbackQueryHandler(button_handler, pattern="^(?!ticket_search_).*$"),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^menu_search$")],
            states={
                TICKET_SEARCH: [MessageHandler(Filters.text & ~Filters.command, handle_ticket_search)],
            },
            fallbacks=[CallbackQueryHandler(cancel, pattern="^menu_principal$|^menu_close$")]
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^con_url$")],
            states={
                URL_INPUT: [MessageHandler(Filters.text & ~Filters.command, handle_url_input)],
            },
            fallbacks=[CallbackQueryHandler(cancel, pattern="^aceptar_.*$|^menu_principal$|^menu_close$")]
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^sin_url$")],
            states={
                NO_URL_CONFIRM: [CallbackQueryHandler(button_handler, pattern="^confirmar_sin_url_.*$")]
            },
            fallbacks=[CallbackQueryHandler(cancel, pattern="^aceptar_.*$|^menu_principal$|^menu_close$")]
        ),
    ]
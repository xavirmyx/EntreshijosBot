from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta
import pytz
import os
import random
import logging
import psycopg2
from psycopg2.extras import DictCursor

# Configura tu token, grupo y URL del webhook usando variables de entorno
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada en las variables de entorno.")

# Configura el logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicializa el bot y Flask
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Configura el Dispatcher
dispatcher = Dispatcher(bot, None, workers=1)
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Variables globales
grupos_seleccionados = {}

# Inicialización de la base de datos PostgreSQL
def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_por_usuario 
                     (user_id BIGINT PRIMARY KEY, count INTEGER, chat_id BIGINT, username TEXT, last_reset TIMESTAMP WITH TIME ZONE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_registradas 
                     (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                      message_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_title TEXT, thread_id BIGINT, 
                      is_deleted BOOLEAN DEFAULT FALSE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS historial_solicitudes 
                     (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                      chat_title TEXT, estado TEXT, fecha_gestion TIMESTAMP WITH TIME ZONE, admin_username TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS grupos_estados 
                     (chat_id BIGINT PRIMARY KEY, title TEXT, activo BOOLEAN DEFAULT TRUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_incorrectas 
                     (id SERIAL PRIMARY KEY, user_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_id BIGINT)''')
        conn.commit()
        conn.close()
        logger.info("Base de datos inicializada correctamente.")
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {str(e)}")
        raise

def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
    except psycopg2.OperationalError as e:
        logger.error(f"Error al conectar a la base de datos: {str(e)}")
        raise

# Funciones de utilidad para la base de datos
def get_ticket_counter():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(ticket_number), 0) FROM peticiones_registradas")
        max_registradas = c.fetchone()[0]
        c.execute("SELECT COALESCE(MAX(ticket_number), 0) FROM historial_solicitudes")
        max_historial = c.fetchone()[0]
        return max(max_registradas, max_historial)

def increment_ticket_counter():
    return get_ticket_counter() + 1

def get_peticiones_por_usuario(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT count, chat_id, username, last_reset FROM peticiones_por_usuario WHERE user_id = %s", (user_id,))
        result = c.fetchone()
        if result:
            result_dict = dict(result)
            now = datetime.now(SPAIN_TZ)
            last_reset = result_dict['last_reset'].astimezone(SPAIN_TZ) if result_dict['last_reset'] else None
            if not last_reset or (now - last_reset).total_seconds() >= 86400:
                result_dict['count'] = 0
                result_dict['last_reset'] = now
                set_peticiones_por_usuario(user_id, 0, result_dict['chat_id'], result_dict['username'], now)
            return result_dict
        return None

def set_peticiones_por_usuario(user_id, count, chat_id, username, last_reset=None):
    if last_reset is None:
        last_reset = datetime.now(SPAIN_TZ)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO peticiones_por_usuario (user_id, count, chat_id, username, last_reset) 
                     VALUES (%s, %s, %s, %s, %s)
                     ON CONFLICT (user_id) DO UPDATE SET 
                     count = EXCLUDED.count, chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, last_reset = EXCLUDED.last_reset""",
                  (user_id, count, chat_id, username, last_reset))
        conn.commit()

def get_peticion_registrada(ticket_number):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id, username, message_text, message_id, timestamp, chat_title, thread_id "
                  "FROM peticiones_registradas WHERE ticket_number = %s AND is_deleted = FALSE", (ticket_number,))
        result = c.fetchone()
        return dict(result) if result else None

def set_peticion_registrada(ticket_number, data):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO peticiones_registradas 
                     (ticket_number, chat_id, username, message_text, message_id, timestamp, chat_title, thread_id, is_deleted) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                     ON CONFLICT (ticket_number) DO UPDATE SET 
                     chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, message_text = EXCLUDED.message_text, 
                     message_id = EXCLUDED.message_id, timestamp = EXCLUDED.timestamp, chat_title = EXCLUDED.chat_title, 
                     thread_id = EXCLUDED.thread_id, is_deleted = FALSE""",
                  (ticket_number, data["chat_id"], data["username"], data["message_text"],
                   data["message_id"], data["timestamp"], data["chat_title"], data["thread_id"]))
        conn.commit()

def del_peticion_registrada(ticket_number):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE peticiones_registradas SET is_deleted = TRUE WHERE ticket_number = %s", (ticket_number,))
        conn.commit()

def get_historial_solicitud(ticket_number):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username "
                  "FROM historial_solicitudes WHERE ticket_number = %s", (ticket_number,))
        result = c.fetchone()
        return dict(result) if result else None

def set_historial_solicitud(ticket_number, data):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO historial_solicitudes 
                     (ticket_number, chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (ticket_number) DO UPDATE SET 
                     chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, message_text = EXCLUDED.message_text, 
                     chat_title = EXCLUDED.chat_title, estado = EXCLUDED.estado, fecha_gestion = EXCLUDED.fecha_gestion, 
                     admin_username = EXCLUDED.admin_username""",
                  (ticket_number, data["chat_id"], data["username"], data["message_text"],
                   data["chat_title"], data["estado"], data["fecha_gestion"], data["admin_username"]))
        conn.commit()

def get_grupos_estados():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id, title, activo FROM grupos_estados")
        return {row['chat_id']: {'title': row['title'], 'activo': row['activo']} for row in c.fetchall()}

def set_grupo_estado(chat_id, title, activo=True):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO grupos_estados (chat_id, title, activo) 
                     VALUES (%s, %s, %s) 
                     ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, activo = EXCLUDED.activo""",
                  (chat_id, title, activo))
        conn.commit()

def get_peticiones_incorrectas(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT timestamp, chat_id FROM peticiones_incorrectas WHERE user_id = %s", (user_id,))
        return [dict(row) for row in c.fetchall()]

def add_peticion_incorrecta(user_id, timestamp, chat_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO peticiones_incorrectas (user_id, timestamp, chat_id) VALUES (%s, %s, %s)",
                  (user_id, timestamp, chat_id))
        conn.commit()

# Configuraciones estáticas
admin_ids = set([12345678])
GRUPOS_PREDEFINIDOS = {
    -1002350263641: "Biblioteca EnTresHijos",
    -1001886336551: "Biblioteca Privada EntresHijos",
    -1001918569531: "SALA DE ENTRESHIJOS.📽",
    -1002034968062: "ᏉᏗᏒᎥᎧᏕ 🖤",
    -1002348662107: "GLOBAL SPORTS STREAM",
}
CANALES_PETICIONES = {
    -1002350263641: {"chat_id": -1002350263641, "thread_id": 19},
    -1001886336551: {"chat_id": -1001886336551, "thread_id": 652},
    -1001918569531: {"chat_id": -1001918569531, "thread_id": 228298},
    -1002034968062: {"chat_id": -1002034968062, "thread_id": 157047},
    -1002348662107: {"chat_id": -1002348662107, "thread_id": 53411},
}
VALID_REQUEST_COMMANDS = [
    '/solicito', '/solícito', '#solícito', '#solicito',
    '/Solicito', '/Solícito', '#Solícito', '#Solicito',
    '/petición', '#petición', '/peticion', '#peticion',
    '/Petición', '#Petición', '/Peticion', '#Peticion'
]
frases_agradecimiento = [
    "¡Gracias por tu paciencia! 🙌",
    "¡Agradecemos tu confianza! 💖",
    "¡Tu apoyo es valioso! 🌟",
    "¡Gracias por usar el bot! 🎉"
]
ping_respuestas = [
    "🏓 *¡Pong!* El bot está en línea, listo para arrasar. 🌟",
    "🎾 *¡Pong!* Aquí estoy, más vivo que nunca. 💪✨",
    "🚀 *¡Pong!* El bot despega, todo en orden. 🌍",
    "🎉 *¡Pong!* Online y con ganas de fiesta. 🥳🌟"
]

# Funciones de utilidad
def escape_markdown(text, preserve_username=False):
    if not text:
        return text
    if preserve_username and text.startswith('@'):
        # Escapar todos los caracteres especiales dentro del @username
        return ''.join(['\\' + c if c in '_*[]()~`>#+-=|{}.!' else c for c in text])
    characters_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in characters_to_escape:
        text = text.replace(char, f'\\{char}')
    return text

def update_grupos_estados(chat_id, title=None):
    grupos = get_grupos_estados()
    if chat_id not in grupos:
        set_grupo_estado(chat_id, title if title else f"Grupo {chat_id}")
    elif title and grupos[chat_id]["title"] == f"Grupo {chat_id}":
        set_grupo_estado(chat_id, title)
    logger.info(f"Grupo registrado/actualizado: {chat_id} - {title or grupos.get(chat_id, {}).get('title')}")

def get_spain_time():
    return datetime.now(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')

# Función para manejar mensajes
def handle_message(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'
    thread_id = message.message_thread_id
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})

    update_grupos_estados(chat_id, chat_title)

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
            warn_message = f"/warn {username_escaped} Petición fuera del canal correspondiente."
            bot.send_message(chat_id=canal_info["chat_id"], text=notificacion, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            bot.send_message(chat_id=canal_info["chat_id"], text=warn_message, message_thread_id=None)
            logger.info(f"Solicitud de {username} denegada: fuera del canal correcto")
            return

        if not grupos_estados.get(chat_id, {}).get("activo", True):
            notificacion = f"🚫 {username_escaped}, las solicitudes están desactivadas en este grupo. Contacta a un administrador. 🌟"
            bot.send_message(chat_id=canal_info["chat_id"], text=notificacion, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            logger.info(f"Solicitudes desactivadas en {chat_id}, notificado a {username}")
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
        try:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
            set_peticion_registrada(ticket_number, {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": timestamp,
                "chat_title": chat_title,
                "thread_id": thread_id
            })
            logger.info(f"Solicitud #{ticket_number} registrada en la base de datos")
        except telegram.error.BadRequest as e:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message.replace('*', ''))
            set_peticion_registrada(ticket_number, {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "message_id": sent_message.message_id,
                "timestamp": timestamp,
                "chat_title": chat_title,
                "thread_id": thread_id
            })
            logger.error(f"Error al enviar con Markdown: {str(e)}")

        user_data = get_peticiones_por_usuario(user_id)
        if not user_data:
            set_peticiones_por_usuario(user_id, 1, chat_id, username)
            user_data = {"count": 1, "chat_id": chat_id, "username": username}
        else:
            user_data["count"] += 1
            set_peticiones_por_usuario(user_id, user_data["count"], user_data["chat_id"], user_data["username"])

        if user_data["count"] > 2 and user_id not in admin_ids:
            limite_message = f"🚫 Lo siento {username_escaped}, has alcanzado el límite de 2 peticiones por día. Intenta mañana. 🌟"
            bot.send_message(chat_id=canal_info["chat_id"], text=limite_message, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            warn_message = f"/warn {username_escaped} Límite de peticiones diarias superado"
            bot.send_message(chat_id=canal_info["chat_id"], text=warn_message, message_thread_id=None)
            logger.info(f"Límite excedido por {username}, advertencia enviada")

            set_historial_solicitud(ticket_number, {
                "chat_id": chat_id,
                "username": username,
                "message_text": message_text,
                "chat_title": chat_title,
                "estado": "limite_excedido",
                "fecha_gestion": datetime.now(SPAIN_TZ),
                "admin_username": "Sistema"
            })
            del_peticion_registrada(ticket_number)
            return

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
        try:
            bot.edit_message_text(chat_id=GROUP_DESTINO, message_id=sent_message.message_id, text=destino_message, parse_mode='Markdown')
        except telegram.error.BadRequest as e:
            bot.edit_message_text(chat_id=GROUP_DESTINO, message_id=sent_message.message_id, text=destino_message.replace('*', ''))

        confirmacion_message = (
            f"✅ *Solicitud registrada* 🎉\n"
            f"Hola {username_escaped}, tu solicitud (Ticket #{ticket_number}) ha sido registrada.\n"
            f"📌 *Detalles:*\n"
            f"🆔 ID: {user_id}\n"
            f"🏠 Grupo: {chat_title_escaped}\n"
            f"📅 Fecha: {timestamp_str}\n"
            f"📝 Mensaje: {message_text_escaped}\n"
            f"🔍 Consulta con: /estado {ticket_number}\n"
            "⏳ Será atendida pronto. 🙌"
        )
        try:
            bot.send_message(chat_id=canal_info["chat_id"], text=confirmacion_message, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
            logger.info(f"Confirmación enviada a {username} en chat {canal_info['chat_id']}")
        except telegram.error.BadRequest as e:
            bot.send_message(chat_id=canal_info["chat_id"], text=confirmacion_message.replace('*', ''), message_thread_id=canal_info["thread_id"])
            logger.error(f"Error al enviar confirmación con Markdown: {str(e)}")

    elif any(word in message_text.lower() for word in ['solicito', 'solícito', 'peticion', 'petición']) and chat_id in CANALES_PETICIONES:
        add_peticion_incorrecta(user_id, timestamp, chat_id)
        intentos_recientes = [i for i in get_peticiones_incorrectas(user_id) 
                            if i["timestamp"].astimezone(SPAIN_TZ) > timestamp - timedelta(hours=24)]

        notificacion_incorrecta = (
            f"⚠️ {username_escaped}, usa solo: {', '.join(VALID_REQUEST_COMMANDS)}.\n"
            "Consulta /ayuda para más detalles. 🌟"
        )
        warn_message = f"/warn {username_escaped} Petición mal formulada"
        if len(intentos_recientes) > 2:
            warn_message = f"/warn {username_escaped} Abuso de peticiones mal formuladas"

        bot.send_message(chat_id=canal_info["chat_id"], text=notificacion_incorrecta, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
        bot.send_message(chat_id=canal_info["chat_id"], text=warn_message, parse_mode='Markdown', message_thread_id=None)
        logger.info(f"Notificación de petición incorrecta enviada a {username} en {chat_id}")

# Handlers de comandos
def handle_menu(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟", parse_mode='Markdown')
        return
    keyboard = [
        [InlineKeyboardButton("📋 Pendientes", callback_data="menu_pendientes")],
        [InlineKeyboardButton("📜 Historial", callback_data="menu_historial")],
        [InlineKeyboardButton("📊 Gráficas", callback_data="menu_graficas")],
        [InlineKeyboardButton("🏠 Grupos", callback_data="menu_grupos")],
        [InlineKeyboardButton("🟢 Activar", callback_data="menu_on"), InlineKeyboardButton("🔴 Desactivar", callback_data="menu_off")],
        [InlineKeyboardButton("➕ Sumar", callback_data="menu_sumar"), InlineKeyboardButton("➖ Restar", callback_data="menu_restar")],
        [InlineKeyboardButton("🏓 Ping", callback_data="menu_ping")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id, text="📋 *Menú Principal* 🌟\nSelecciona una opción:", reply_markup=reply_markup, parse_mode='Markdown')

def handle_sumar(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟", parse_mode='Markdown')
        return
    bot.send_message(chat_id=chat_id, text="➕ *Sumar peticiones* 🌟\nPor favor, escribe: /sumar @username [número]", parse_mode='Markdown')

def handle_restar(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟", parse_mode='Markdown')
        return
    bot.send_message(chat_id=chat_id, text="➖ *Restar peticiones* 🌟\nPor favor, escribe: /restar @username [número]", parse_mode='Markdown')

def handle_ping(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟", parse_mode='Markdown')
        return
    bot.send_message(chat_id=chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')

def handle_ayuda(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    thread_id = message.message_thread_id if chat_id in CANALES_PETICIONES else None
    username = escape_markdown(f"@{message.from_user.username}", True) if message.from_user.username else "Usuario"
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})
    ayuda_message = (
        f"📖 *Guía rápida* 🌟\n"
        f"Hola {username}, usa {', '.join(VALID_REQUEST_COMMANDS)} para enviar una solicitud (máx. 2/día).\n"
        "🔍 */estado [ticket]* - Consulta el estado.\n"
        "🌟 *¡Gracias por usar el bot!* 🙌"
    )
    bot.send_message(chat_id=canal_info["chat_id"], text=ayuda_message, parse_mode='Markdown', 
                     message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None)

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
        bot.send_message(chat_id=canal_info["chat_id"], text="❗ Uso: /estado [ticket] 🌟", parse_mode='Markdown', 
                         message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None)
        return
    try:
        ticket = int(args[0])
        info = get_peticion_registrada(ticket)
        if info:
            estado_message = (
                f"📋 *Estado* 🌟\n"
                f"Ticket #{ticket}: {escape_markdown(info['message_text'])}\n"
                f"Estado: Pendiente ⏳\n"
                f"🕒 Enviada: {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}"
            )
        else:
            info = get_historial_solicitud(ticket)
            if info:
                estado_str = {
                    "subido": "✅ Aceptada",
                    "denegado": "❌ Denegada",
                    "eliminado": "🗑️ Eliminada",
                    "notificado": "📢 Respondida",
                    "limite_excedido": "🚫 Límite excedido"
                }.get(info["estado"], "🔄 Desconocido")
                estado_message = (
                    f"📋 *Estado* 🌟\n"
                    f"Ticket #{ticket}: {escape_markdown(info['message_text'])}\n"
                    f"Estado: {estado_str}\n"
                    f"🕒 Gestionada: {info['fecha_gestion'].strftime('%d/%m/%Y %H:%M:%S')}\n"
                    f"👥 Admin: {info['admin_username']}"
                )
            else:
                estado_message = f"📋 *Estado* 🌟\nTicket #{ticket}: No encontrado. 🔍"
        bot.send_message(chat_id=canal_info["chat_id"], text=estado_message, parse_mode='Markdown', 
                         message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None)
    except ValueError:
        bot.send_message(chat_id=canal_info["chat_id"], text="❗ Ticket debe ser un número. 🌟", parse_mode='Markdown', 
                         message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None)

def handle_graficas(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT estado, COUNT(*) as count FROM historial_solicitudes GROUP BY estado")
        stats = dict(c.fetchall())

    total = sum(stats.values())
    stats_msg = (
        f"📊 *Estadísticas de Solicitudes* 🌟\n"
        f"Total gestionadas: {total}\n"
        f"✅ Subidas: {stats.get('subido', 0)}\n"
        f"❌ Denegadas: {stats.get('denegado', 0)}\n"
        f"🗑️ Eliminadas: {stats.get('eliminado', 0)}\n"
        f"🚫 Límite excedido: {stats.get('limite_excedido', 0)}"
    )
    bot.send_message(chat_id=chat_id, text=stats_msg, parse_mode='Markdown')

# Manejador de botones
def button_handler(update, context):
    query = update.callback_query
    if not query:
        return
    query.answer()
    data = query.data
    chat_id = query.message.chat_id
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"
    logger.debug(f"Botón presionado: {data}")

    if data == "menu_principal":
        keyboard = [
            [InlineKeyboardButton("📋 Pendientes", callback_data="menu_pendientes")],
            [InlineKeyboardButton("📜 Historial", callback_data="menu_historial")],
            [InlineKeyboardButton("📊 Gráficas", callback_data="menu_graficas")],
            [InlineKeyboardButton("🏠 Grupos", callback_data="menu_grupos")],
            [InlineKeyboardButton("🟢 Activar", callback_data="menu_on"), InlineKeyboardButton("🔴 Desactivar", callback_data="menu_off")],
            [InlineKeyboardButton("➕ Sumar", callback_data="menu_sumar"), InlineKeyboardButton("➖ Restar", callback_data="menu_restar")],
            [InlineKeyboardButton("🏓 Ping", callback_data="menu_ping")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="📋 *Menú Principal* 🌟\nSelecciona una opción:", reply_markup=reply_markup, parse_mode='Markdown')
        return

    if data == "menu_pendientes":
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT ticket_number, username, chat_title FROM peticiones_registradas WHERE is_deleted = FALSE ORDER BY ticket_number")
                pendientes = c.fetchall()
            if not pendientes:
                bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes. 🌟", parse_mode='Markdown')
                query.message.delete()
                return

            ITEMS_PER_PAGE = 5
            page = 1
            start_idx = (page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_items = pendientes[start_idx:end_idx]
            total_pages = (len(pendientes) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

            keyboard = []
            for ticket, username, chat_title in page_items:
                try:
                    # Escapar completamente el username para evitar problemas con caracteres especiales
                    username_safe = escape_markdown(username, preserve_username=True)
                    chat_title_safe = escape_markdown(chat_title)
                    button_text = f"#{ticket} - {username_safe} ({chat_title_safe})"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pend_{ticket}")])
                except Exception as e:
                    logger.error(f"Error al procesar ticket #{ticket} con username {username}: {str(e)}")
                    # Fallback: usar texto sin Markdown
                    button_text = f"#{ticket} - {username} ({chat_title})"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pend_{ticket}")])

            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"))
                keyboard.append(nav_buttons)
                reply_markup = InlineKeyboardMarkup(keyboard)
                nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"pend_page_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"pend_page_{page+1}"))

            message_text = f"📋 *Solicitudes pendientes (Página {page}/{total_pages})* 🌟\nSelecciona una solicitud:"
            try:
                bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup, parse_mode='Markdown')
            except telegram.error.BadRequest as e:
                logger.error(f"Error al enviar mensaje con Markdown: {str(e)}")
                bot.send_message(chat_id=chat_id, text=message_text.replace('*', ''), reply_markup=reply_markup)
            query.message.delete()

        except Exception as e:
            logger.error(f"Error general en menu_pendientes: {str(e)}", exc_info=True)
            bot.send_message(chat_id=chat_id, text="❌ Ocurrió un error al mostrar las solicitudes pendientes. Por favor, intenta de nuevo más tarde. 🌟", parse_mode='Markdown')
            query.message.delete()
        return

    if data == "menu_historial":
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT ticket_number, username, message_text, chat_title, estado, fecha_gestion, admin_username "
                      "FROM historial_solicitudes ORDER BY ticket_number DESC")
            solicitudes = c.fetchall()
        if not solicitudes:
            bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes gestionadas en el historial. 🌟", parse_mode='Markdown')
            query.message.delete()
            return
        historial = []
        for row in solicitudes:
            ticket, username, message_text, chat_title, estado, fecha_gestion, admin_username = row
            estado_str = {
                "subido": "✅ Aceptada",
                "denegado": "❌ Denegada",
                "eliminado": "🗑️ Eliminada",
                "notificado": "📢 Respondida",
                "limite_excedido": "🚫 Límite excedido"
            }.get(estado, "🔄 Desconocido")
            historial.append(
                f"🎫 *Ticket #{ticket}*\n"
                f"👤 Usuario: {escape_markdown(username, True)}\n"
                f"📝 Mensaje: {escape_markdown(message_text)}\n"
                f"🏠 Grupo: {escape_markdown(chat_title)}\n"
                f"📅 Gestionada: {fecha_gestion.strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"👥 Admin: {admin_username}\n"
                f"📌 Estado: {estado_str}\n"
            )
        historial_message = "📜 *Historial de Solicitudes Gestionadas* 🌟\n\n" + "\n".join(historial[:5])
        keyboard = [[InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text=historial_message, reply_markup=reply_markup, parse_mode='Markdown')
        query.message.delete()
        return

    if data == "menu_graficas":
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT estado, COUNT(*) as count FROM historial_solicitudes GROUP BY estado")
            stats = dict(c.fetchall())

        total = sum(stats.values())
        stats_msg = (
            f"📊 *Estadísticas de Solicitudes* 🌟\n"
            f"Total gestionadas: {total}\n"
            f"✅ Subidas: {stats.get('subido', 0)}\n"
            f"❌ Denegadas: {stats.get('denegado', 0)}\n"
            f"🗑️ Eliminadas: {stats.get('eliminado', 0)}\n"
            f"🚫 Límite excedido: {stats.get('limite_excedido', 0)}"
        )
        keyboard = [[InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text=stats_msg, reply_markup=reply_markup, parse_mode='Markdown')
        query.message.delete()
        return

    if data == "menu_grupos":
        grupos_estados = get_grupos_estados()
        if not grupos_estados:
            bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟", parse_mode='Markdown')
            query.message.delete()
            return
        estado = "\n".join([f"🏠 {info['title']}: {'🟢 Activo' if info['activo'] else '🔴 Inactivo'} (ID: {gid})"
                           for gid, info in sorted(grupos_estados.items(), key=lambda x: x[1]['title'])])
        keyboard = [[InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text=f"📋 *Estado de los grupos* 🌟\n{estado}", reply_markup=reply_markup, parse_mode='Markdown')
        query.message.delete()
        return

    if data == "menu_on":
        grupos_estados = get_grupos_estados()
        if not grupos_estados:
            bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟", parse_mode='Markdown')
            query.message.delete()
            return
        # Excluir el grupo de administradores (-1002641818457)
        keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}",
                                        callback_data=f"select_on_{gid}")] 
                    for gid, info in grupos_estados.items() if str(gid) != '-1002641818457']
        keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_on"),
                         InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        grupos_seleccionados[chat_id] = {"accion": "on", "grupos": set(), "mensaje_id": None, "estado": "seleccion"}
        sent_message = bot.send_message(chat_id=chat_id, text="🟢 *Activar solicitudes* 🌟\nSelecciona los grupos:", 
                                       reply_markup=reply_markup, parse_mode='Markdown')
        grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id
        query.message.delete()
        return

    if data == "menu_off":
        grupos_estados = get_grupos_estados()
        if not grupos_estados:
            bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟", parse_mode='Markdown')
            query.message.delete()
            return
        # Excluir el grupo de administradores (-1002641818457)
        keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}",
                                        callback_data=f"select_off_{gid}")] 
                    for gid, info in grupos_estados.items() if str(gid) != '-1002641818457']
        keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_off"),
                         InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        grupos_seleccionados[chat_id] = {"accion": "off", "grupos": set(), "mensaje_id": None, "estado": "seleccion"}
        sent_message = bot.send_message(chat_id=chat_id, text="🔴 *Desactivar solicitudes* 🌟\nSelecciona los grupos:", 
                                       reply_markup=reply_markup, parse_mode='Markdown')
        grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id
        query.message.delete()
        return

    if data == "menu_sumar":
        bot.send_message(chat_id=chat_id, text="➕ *Sumar peticiones* 🌟\nPor favor, escribe: /sumar @username [número]", parse_mode='Markdown')
        query.message.delete()
        return

    if data == "menu_restar":
        bot.send_message(chat_id=chat_id, text="➖ *Restar peticiones* 🌟\nPor favor, escribe: /restar @username [número]", parse_mode='Markdown')
        query.message.delete()
        return

    if data == "menu_ping":
        bot.send_message(chat_id=chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')
        query.message.delete()
        return

    if data.startswith("select_") or data.startswith("confirm_") or data.startswith("notify_") or data.startswith("back_"):
        if chat_id not in grupos_seleccionados:
            return
        estado = grupos_seleccionados[chat_id]["estado"]

        if estado == "seleccion" and (data.startswith("select_on_") or data.startswith("select_off_")):
            accion = "on" if data.startswith("select_on_") else "off"
            grupo_id = int(data.split("_")[2])
            if grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                grupos_seleccionados[chat_id]["grupos"].remove(grupo_id)
            else:
                grupos_seleccionados[chat_id]["grupos"].add(grupo_id)
            grupos_estados = get_grupos_estados()
            keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}{' ✅' if gid in grupos_seleccionados[chat_id]['grupos'] else ''}",
                                            callback_data=f"select_{accion}_{gid}")] for gid, info in grupos_estados.items()]
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}"),
                             InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=f"{'🟢' if accion == 'on' else '🔴'} *{'Activar' if accion == 'on' else 'Desactivar'} solicitudes* 🌟\nSelecciona los grupos:", 
                                    reply_markup=reply_markup, parse_mode='Markdown')
            return

        if estado == "seleccion" and (data == "confirm_on" or data == "confirm_off"):
            accion = "on" if data == "confirm_on" else "off"
            if not grupos_seleccionados[chat_id]["grupos"]:
                query.edit_message_text(text=f"ℹ️ No se seleccionaron grupos para {'activar' if accion == 'on' else 'desactivar'}. 🌟", parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
                return
            grupos_seleccionados[chat_id]["estado"] = "confirmacion"
            grupos_estados = get_grupos_estados()
            grupos = "\n".join([escape_markdown(grupos_estados[gid]["title"]) for gid in grupos_seleccionados[chat_id]["grupos"]])
            texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'}* 🌟\nGrupos afectados:\n{grupos}\n\n¿Enviar notificación?"
            keyboard = [
                [InlineKeyboardButton("✅ Sí", callback_data=f"notify_{accion}_yes"),
                 InlineKeyboardButton("❌ No", callback_data=f"notify_{accion}_no")],
                [InlineKeyboardButton("🔙 Retroceder", callback_data=f"back_{accion}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if estado == "confirmacion" and data.startswith("notify_"):
            accion, decision = data.split("_")[1:]
            grupos_estados = get_grupos_estados()
            for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                set_grupo_estado(grupo_id, grupos_estados[grupo_id]["title"], accion == "on")
                if decision == "yes":
                    mensaje = "🎉 *¡Solicitudes reactivadas!* 🌟\nYa se pueden enviar solicitudes.\nMáx. 2/día." if accion == "on" else \
                              "🚫 *Solicitudes desactivadas* 🌟\nNo se aceptan nuevas solicitudes hasta nuevo aviso."
                    canal_info = CANALES_PETICIONES.get(grupo_id, {"chat_id": grupo_id, "thread_id": None})
                    bot.send_message(chat_id=canal_info["chat_id"], text=mensaje, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])
            texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} {'y notificadas' if decision == 'yes' else 'sin notificación'}.* 🌟"
            keyboard = [[InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            del grupos_seleccionados[chat_id]
            return

        if estado == "confirmacion" and data.startswith("back_"):
            accion = data.split("_")[1]
            grupos_seleccionados[chat_id]["estado"] = "seleccion"
            grupos_estados = get_grupos_estados()
            keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}{' ✅' if gid in grupos_seleccionados[chat_id]['grupos'] else ''}",
                                            callback_data=f"select_{accion}_{gid}")] for gid, info in grupos_estados.items()]
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}"),
                             InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=f"{'🟢' if accion == 'on' else '🔴'} *{'Activar' if accion == 'on' else 'Desactivar'} solicitudes* 🌟\nSelecciona los grupos:", 
                                    reply_markup=reply_markup, parse_mode='Markdown')
            return

    if data.startswith("pend_"):
        if data.startswith("pend_page_"):
            page = int(data.split("_")[2])
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT ticket_number, username, chat_title FROM peticiones_registradas WHERE is_deleted = FALSE ORDER BY ticket_number")
                pendientes = c.fetchall()
            ITEMS_PER_PAGE = 5
            total_pages = (len(pendientes) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            if page < 1 or page > total_pages:
                return
            start_idx = (page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_items = pendientes[start_idx:end_idx]

            keyboard = [[InlineKeyboardButton(f"#{ticket} - {username} ({chat_title})",
                                            callback_data=f"pend_{ticket}")] for ticket, username, chat_title in page_items]
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"pend_page_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"pend_page_{page+1}"))
            nav_buttons.append(InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"))
            keyboard.append(nav_buttons)
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=f"📋 *Solicitudes pendientes (Página {page}/{total_pages})* 🌟\nSelecciona una solicitud:", 
                                    reply_markup=reply_markup, parse_mode='Markdown')
            return

        ticket = int(data.split("_")[1])
        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

        if len(data.split("_")) == 2:  # Mostrar opciones iniciales
            keyboard = [
                [InlineKeyboardButton("✅ Subido", callback_data=f"pend_{ticket}_subido")],
                [InlineKeyboardButton("❌ Denegado", callback_data=f"pend_{ticket}_denegado")],
                [InlineKeyboardButton("🗑️ Eliminar", callback_data=f"pend_{ticket}_eliminar")],
                [InlineKeyboardButton("🔙 Pendientes", callback_data="pend_page_1")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = (
                f"📋 *Solicitud #{ticket}* 🌟\n"
                f"👤 Usuario: {escape_markdown(info['username'], True)}\n"
                f"📝 Mensaje: {escape_markdown(info['message_text'])}\n"
                f"🏠 Grupo: {escape_markdown(info['chat_title'])}\n"
                f"🕒 Fecha: {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}\n"
                "Selecciona una acción:"
            )
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if len(data.split("_")) == 3:  # Mostrar confirmación
            accion = data.split("_")[2]
            if accion in ["subido", "denegado", "eliminar"]:
                accion_str = {"subido": "Subido", "denegado": "Denegado", "eliminar": "Eliminado"}[accion]
                keyboard = [
                    [InlineKeyboardButton("✅ Confirmar", callback_data=f"pend_{ticket}_{accion}_confirm")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"pend_{ticket}_cancel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                texto = f"📋 *Confirmar acción* 🌟\n¿Marcar el Ticket #{ticket} como {accion_str}? 🔍\n(Tiempo: {datetime.now(SPAIN_TZ).strftime('%H:%M:%S')})"
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
                return

        if data.endswith("_confirm"):  # Procesar confirmación
            accion = data.split("_")[2]
            accion_str = {"subido": "Subido", "denegado": "Denegado", "eliminar": "Eliminado"}[accion]
            set_historial_solicitud(ticket, {
                "chat_id": info["chat_id"],
                "username": info["username"],
                "message_text": info["message_text"],
                "chat_title": info["chat_title"],
                "estado": accion,
                "fecha_gestion": datetime.now(SPAIN_TZ),
                "admin_username": admin_username
            })
            keyboard = [
                [InlineKeyboardButton("✅ Sí", callback_data=f"pend_{ticket}_{accion}_notify_yes"),
                 InlineKeyboardButton("❌ No", callback_data=f"pend_{ticket}_{accion}_notify_no")],
                [InlineKeyboardButton("🔙 Pendientes", callback_data="pend_page_1")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"✅ *Ticket #{ticket} procesado como {accion_str}.* 🌟\n¿Notificar al usuario? (Confirmado: {datetime.now(SPAIN_TZ).strftime('%H:%M:%S')})"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if data.endswith("_notify_yes") or data.endswith("_notify_no"):  # Manejar notificación
            accion = data.split("_")[2]
            notify = data.endswith("_notify_yes")
            username_escaped = escape_markdown(info["username"], True)
            message_text_escaped = escape_markdown(info["message_text"])
            accion_str = {"subido": "Subido", "denegado": "Denegado", "eliminar": "Eliminado"}[accion]
            if notify:
                if accion == "subido":
                    bot.send_message(chat_id=info["chat_id"], 
                                   text=f"✅ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido subida. 🎉", 
                                   parse_mode='Markdown', message_thread_id=info.get("thread_id"))
                elif accion == "denegado":
                    bot.send_message(chat_id=info["chat_id"], 
                                   text=f"❌ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada. 🌟", 
                                   parse_mode='Markdown', message_thread_id=info.get("thread_id"))
                elif accion == "eliminar":
                    bot.send_message(chat_id=info["chat_id"], 
                                   text=f"ℹ️ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada. 🌟", 
                                   parse_mode='Markdown', message_thread_id=info.get("thread_id"))
                    try:
                        bot.delete_message(chat_id=GROUP_DESTINO, message_id=info["message_id"])
                    except telegram.error.TelegramError as e:
                        logger.error(f"No se pudo eliminar el mensaje: {str(e)}")
            del_peticion_registrada(ticket)
            keyboard = [[InlineKeyboardButton("🔙 Pendientes", callback_data="pend_page_1")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"✅ *Ticket #{ticket} procesado como {accion_str}{' y notificado' if notify else ''}.* 🌟\n(Finalizado: {datetime.now(SPAIN_TZ).strftime('%H:%M:%S')})"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if data.endswith("_cancel"):  # Cancelar acción
            keyboard = [[InlineKeyboardButton("🔙 Pendientes", callback_data="pend_page_1")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"❌ Acción cancelada para Ticket #{ticket}. 🌟\n(Cancelado: {datetime.now(SPAIN_TZ).strftime('%H:%M:%S')})"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

# Añadir handlers
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
dispatcher.add_handler(CommandHandler('menu', handle_menu))
dispatcher.add_handler(CommandHandler('sumar', handle_sumar))
dispatcher.add_handler(CommandHandler('restar', handle_restar))
dispatcher.add_handler(CommandHandler('ping', handle_ping))
dispatcher.add_handler(CommandHandler('ayuda', handle_ayuda))
dispatcher.add_handler(CommandHandler('estado', handle_estado))
dispatcher.add_handler(CommandHandler('graficas', handle_graficas))
dispatcher.add_handler(CallbackQueryHandler(button_handler))

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

# Inicializar la base de datos al arrancar el servidor
init_db()
for chat_id, title in GRUPOS_PREDEFINIDOS.items():
    set_grupo_estado(chat_id, title)

if __name__ == '__main__':
    logger.info("Iniciando bot en modo local")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
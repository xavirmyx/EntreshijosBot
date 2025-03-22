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

# Configuración inicial
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada en las variables de entorno. Configúrala en Render.")

# Logging reducido a errores críticos
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicialización
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=1)
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Cache global para grupos_estados
grupos_estados_cache = {}

# Conexión a la base de datos
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
    except psycopg2.OperationalError as e:
        logger.error(f"Error al conectar a la base de datos: {str(e)}")
        raise

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_por_usuario 
                     (user_id BIGINT PRIMARY KEY, count INTEGER, chat_id BIGINT, username TEXT, last_reset TIMESTAMP WITH TIME ZONE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_registradas 
                     (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                      message_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_title TEXT, thread_id BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS historial_solicitudes 
                     (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                      chat_title TEXT, estado TEXT, fecha_gestion TIMESTAMP WITH TIME ZONE, admin_username TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS grupos_estados 
                     (chat_id BIGINT PRIMARY KEY, title TEXT, activo BOOLEAN DEFAULT TRUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_incorrectas 
                     (id SERIAL PRIMARY KEY, user_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_id BIGINT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {str(e)}")
        raise

# Funciones de base de datos
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
            if not last_reset or (now - last_reset).days >= 1:
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
                     count = %s, chat_id = %s, username = %s, last_reset = %s""",
                  (user_id, count, chat_id, username, last_reset,
                   count, chat_id, username, last_reset))
        conn.commit()

def get_peticion_registrada(ticket_number):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id, username, message_text, message_id, timestamp, chat_title, thread_id "
                  "FROM peticiones_registradas WHERE ticket_number = %s", (ticket_number,))
        result = c.fetchone()
        return dict(result) if result else None

def set_peticion_registrada(ticket_number, data):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO peticiones_registradas 
                     (ticket_number, chat_id, username, message_text, message_id, timestamp, chat_title, thread_id) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (ticket_number) DO UPDATE SET 
                     chat_id = %s, username = %s, message_text = %s, message_id = %s, timestamp = %s, 
                     chat_title = %s, thread_id = %s""",
                  (ticket_number, data["chat_id"], data["username"], data["message_text"],
                   data["message_id"], data["timestamp"], data["chat_title"], data["thread_id"],
                   data["chat_id"], data["username"], data["message_text"],
                   data["message_id"], data["timestamp"], data["chat_title"], data["thread_id"]))
        conn.commit()

def del_peticion_registrada(ticket_number):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM peticiones_registradas WHERE ticket_number = %s", (ticket_number,))
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
                     chat_id = %s, username = %s, message_text = %s, chat_title = %s, estado = %s, 
                     fecha_gestion = %s, admin_username = %s""",
                  (ticket_number, data["chat_id"], data["username"], data["message_text"],
                   data["chat_title"], data["estado"], data["fecha_gestion"], data["admin_username"],
                   data["chat_id"], data["username"], data["message_text"],
                   data["chat_title"], data["estado"], data["fecha_gestion"], data["admin_username"]))
        conn.commit()

def get_grupos_estados():
    global grupos_estados_cache
    if not grupos_estados_cache:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT chat_id, title, activo FROM grupos_estados")
            grupos_estados_cache = {row['chat_id']: {'title': row['title'], 'activo': row['activo']} for row in c.fetchall()}
    return grupos_estados_cache

def set_grupo_estado(chat_id, title, activo=True):
    global grupos_estados_cache
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO grupos_estados (chat_id, title, activo) 
                     VALUES (%s, %s, %s) 
                     ON CONFLICT (chat_id) DO UPDATE SET title = %s, activo = %s""",
                  (chat_id, title, activo, title, activo))
        conn.commit()
    grupos_estados_cache[chat_id] = {'title': title, 'activo': activo}

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

def get_top_users():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT username, count FROM peticiones_por_usuario ORDER BY count DESC LIMIT 5")
        return [f"{row['username']} ({row['count']})" for row in c.fetchall()]

# Configuraciones estáticas
admin_ids = {12345678}
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
INVALID_REQUEST_PATTERNS = [
    'Solicito', 'Solícito', 'solicito', 'solícito', 'SOLICITO', 'SOLÍCITO',
    'Peticion', 'Peticíon', 'peticion', 'peticíon', 'PETICION', 'PETICÍON'
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
        return text
    characters = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in characters:
        text = text.replace(char, f'\\{char}')
    return text

def update_grupos_estados(chat_id, title=None):
    grupos = get_grupos_estados()
    if chat_id not in grupos:
        set_grupo_estado(chat_id, title if title else f"Grupo {chat_id}")
    elif title and grupos[chat_id]["title"] == f"Grupo {chat_id}":
        set_grupo_estado(chat_id, title)

def get_spain_time():
    return datetime.now(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')

# Handlers
def handle_message(update, context):
    if not update.message:
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else f"Usuario_{user_id}"
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
        if chat_id not in CANALES_PETICIONES or thread_id != CANALES_PETICIONES[chat_id]["thread_id"]:
            bot.send_message(chat_id=canal_info["chat_id"], text=f"❌ *Error*: Las solicitudes solo son válidas en el canal correspondiente.", message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            bot.send_message(chat_id=canal_info["chat_id"], text=f"/warn {username_escaped} Solicitud fuera del canal permitido.", message_thread_id=canal_info["thread_id"])
            return

        if not grupos_estados.get(chat_id, {}).get("activo", True):
            bot.send_message(chat_id=canal_info["chat_id"], text=f"⛔ *Aviso*: Las solicitudes están desactivadas en este grupo. Contacta a un administrador.", message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            return

        user_data = get_peticiones_por_usuario(user_id) or {"count": 0, "chat_id": chat_id, "username": username}
        if user_data["count"] >= 2 and user_id not in admin_ids:
            bot.send_message(chat_id=canal_info["chat_id"], text=f"🚫 *Límite alcanzado*: Has usado tus 2 solicitudes diarias, {username_escaped}. Intenta mañana.", message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            bot.send_message(chat_id=canal_info["chat_id"], text=f"/warn {username_escaped} Límite de solicitudes diarias excedido.", message_thread_id=canal_info["thread_id"])
            return

        user_data["count"] += 1
        set_peticiones_por_usuario(user_id, user_data["count"], chat_id, username)

        ticket_number = increment_ticket_counter()
        destino_message = (
            f"📩 *Nueva Solicitud Registrada* #{ticket_number}\n"
            f"👤 *Usuario*: {username_escaped} (ID: {user_id})\n"
            f"📝 *Solicitud*: {message_text_escaped}\n"
            f"📊 *Peticiones*: {user_data['count']}/2\n"
            f"🏠 *Grupo*: {chat_title_escaped}\n"
            f"🕒 *Fecha*: {timestamp_str}\n"
            f"🤖 *Entreshijos Bot*"
        )
        sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
        set_peticion_registrada(ticket_number, {
            "chat_id": chat_id, "username": username, "message_text": message_text,
            "message_id": sent_message.message_id, "timestamp": timestamp, "chat_title": chat_title, "thread_id": thread_id
        })

        top_users = get_top_users()
        confirmacion_message = (
            f"✅ *Solicitud Registrada* #{ticket_number}\n"
            f"Hola {username_escaped}, tu solicitud ha sido enviada con éxito.\n"
            f"📝 *Detalles*: {message_text_escaped}\n"
            f"🏠 *Grupo*: {chat_title_escaped}\n"
            f"🕒 *Fecha*: {timestamp_str}\n"
            f"📊 *Tus peticiones*: {user_data['count']}/2\n"
            f"🔍 Consulta su estado con: `/estado {ticket_number}`\n"
            f"🏆 *Top 5 Solicitantes*: {', '.join(top_users) if top_users else 'Sin datos'}\n"
            f"⏳ Será procesada pronto. {random.choice(frases_agradecimiento)}"
        )
        bot.send_message(chat_id=canal_info["chat_id"], text=confirmacion_message, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')

    elif any(pattern in message_text for pattern in INVALID_REQUEST_PATTERNS) and chat_id in CANALES_PETICIONES:
        add_peticion_incorrecta(user_id, timestamp, chat_id)
        bot.send_message(chat_id=canal_info["chat_id"], text=f"⚠️ *Formato incorrecto*: Usa solo {', '.join(VALID_REQUEST_COMMANDS)}. Consulta `/ayuda` para más información.", message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
        bot.send_message(chat_id=canal_info["chat_id"], text=f"/warn {username_escaped} Solicitud mal formulada.", message_thread_id=canal_info["thread_id"])

def handle_estadistica(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM peticiones_registradas")
        pendientes = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM historial_solicitudes")
        gestionadas = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM historial_solicitudes WHERE estado = 'subido'")
        subidas = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM historial_solicitudes WHERE estado = 'denegado'")
        denegadas = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM historial_solicitudes WHERE estado = 'eliminado'")
        eliminadas = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT user_id) FROM peticiones_por_usuario WHERE last_reset > %s", (datetime.now(SPAIN_TZ) - timedelta(days=1),))
        usuarios_activos = c.fetchone()[0]
    stats_message = (
        f"📊 *Estadísticas del Bot*\n"
        f"📬 *Solicitudes pendientes*: {pendientes}\n"
        f"✅ *Solicitudes gestionadas*: {gestionadas}\n"
        f"   ↳ *Subidas*: {subidas}\n"
        f"   ↳ *Denegadas*: {denegadas}\n"
        f"   ↳ *Eliminadas*: {eliminadas}\n"
        f"👥 *Usuarios activos (24h)*: {usuarios_activos}\n"
        f"🕒 *Actualizado*: {get_spain_time()}\n"
        f"🤖 *Entreshijos Bot*"
    )
    bot.send_message(chat_id=chat_id, text=stats_message, parse_mode='Markdown')

def handle_on(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    grupos = get_grupos_estados()
    if not grupos:
        bot.send_message(chat_id=chat_id, text="ℹ️ *Sin datos*: No hay grupos registrados.", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}", callback_data=f"select_on_{gid}")] for gid, info in grupos.items()]
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_on")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    grupos_seleccionados[chat_id] = {"accion": "on", "grupos": set(), "mensaje_id": None, "estado": "seleccion"}
    sent_message = bot.send_message(chat_id=chat_id, text="🟢 *Activar Solicitudes*\nSelecciona los grupos:", reply_markup=reply_markup, parse_mode='Markdown')
    grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id

def handle_off(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    grupos = get_grupos_estados()
    if not grupos:
        bot.send_message(chat_id=chat_id, text="ℹ️ *Sin datos*: No hay grupos registrados.", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}", callback_data=f"select_off_{gid}")] for gid, info in grupos.items()]
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_off")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    grupos_seleccionados[chat_id] = {"accion": "off", "grupos": set(), "mensaje_id": None, "estado": "seleccion"}
    sent_message = bot.send_message(chat_id=chat_id, text="🔴 *Desactivar Solicitudes*\nSelecciona los grupos:", reply_markup=reply_markup, parse_mode='Markdown')
    grupos_seleccionados[chat_id]["mensaje_id"] = sent_message.message_id

def handle_grupos(update, context):
    if not update.message and not update.callback_query:
        return
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    grupos = get_grupos_estados()
    if not grupos:
        bot.send_message(chat_id=chat_id, text="ℹ️ *Sin datos*: No hay grupos registrados.", parse_mode='Markdown')
        return
    estado = "\n".join([f"🏠 {info['title']}: {'🟢 Activo' if info['activo'] else '🔴 Inactivo'} (ID: {gid})"
                       for gid, info in sorted(grupos.items(), key=lambda x: x[1]['title'])])
    keyboard = [[InlineKeyboardButton("🔙 Retroceder", callback_data="grupos_retroceder")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"📋 *Estado de los Grupos*\n{estado}"
    if update.message:
        bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        update.callback_query.message.delete()
        bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')

def handle_historial(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT ticket_number, username, message_text, chat_title, estado, fecha_gestion, admin_username "
                  "FROM historial_solicitudes ORDER BY ticket_number DESC LIMIT 10")
        solicitudes = c.fetchall()
    if not solicitudes:
        bot.send_message(chat_id=chat_id, text="ℹ️ *Sin datos*: No hay solicitudes gestionadas en el historial.", parse_mode='Markdown')
        return
    historial = []
    for row in solicitudes:
        ticket, username, message_text, chat_title, estado, fecha_gestion, admin_username = row
        estado_str = {
            "subido": "✅ Aceptada",
            "denegado": "❌ Denegada",
            "eliminado": "🗑️ Eliminada",
            "notificado": "📢 Respondida"
        }.get(estado, "🔄 Desconocido")
        historial.append(
            f"🎫 *Ticket #{ticket}*\n"
            f"👤 *Usuario*: {escape_markdown(username, True)}\n"
            f"📝 *Mensaje*: {escape_markdown(message_text)}\n"
            f"🏠 *Grupo*: {escape_markdown(chat_title)}\n"
            f"📅 *Gestionada*: {fecha_gestion.strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"👥 *Admin*: {admin_username}\n"
            f"📌 *Estado*: {estado_str}\n"
        )
    historial_message = "📜 *Historial de Solicitudes Gestionadas (Últimas 10)*\n\n" + "\n".join(historial)
    bot.send_message(chat_id=chat_id, text=historial_message, parse_mode='Markdown')

def handle_pendientes(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT ticket_number, username, chat_title FROM peticiones_registradas ORDER BY ticket_number")
        pendientes = c.fetchall()
    if not pendientes:
        bot.send_message(chat_id=chat_id, text="ℹ️ *Sin datos*: No hay solicitudes pendientes.", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"#{ticket} - {username} ({chat_title})",
                                    callback_data=f"pend_{ticket}")] for ticket, username, chat_title in pendientes]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id, text="📋 *Solicitudes Pendientes*\nSelecciona una solicitud:", reply_markup=reply_markup, parse_mode='Markdown')

def handle_eliminar(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT ticket_number, username FROM peticiones_registradas")
        pendientes = c.fetchall()
    if not pendientes:
        bot.send_message(chat_id=chat_id, text="ℹ️ *Sin datos*: No hay solicitudes pendientes para eliminar.", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"Ticket #{ticket} - {username}", callback_data=f"eliminar_{ticket}")] for ticket, username in pendientes]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id, text="🗑️ *Eliminar Solicitud*\nSelecciona el ticket:", reply_markup=reply_markup, parse_mode='Markdown')

def handle_ping(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    bot.send_message(chat_id=chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')

def handle_subido(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ *Uso*: /subido [ticket]", parse_mode='Markdown')
        return
    try:
        ticket = int(args[0])
        info = get_peticion_registrada(ticket)
        if not info:
            bot.send_message(chat_id=chat_id, text=f"❌ *Error*: Ticket #{ticket} no encontrado.", parse_mode='Markdown')
            return
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_subido_{ticket}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text=f"📋 *Confirmar Acción*\n¿Marcar el Ticket #{ticket} de {info['username']} como subido?", reply_markup=reply_markup, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ *Error*: El ticket debe ser un número.", parse_mode='Markdown')

def handle_denegado(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ *Uso*: /denegado [ticket]", parse_mode='Markdown')
        return
    try:
        ticket = int(args[0])
        info = get_peticion_registrada(ticket)
        if not info:
            bot.send_message(chat_id=chat_id, text=f"❌ *Error*: Ticket #{ticket} no encontrado.", parse_mode='Markdown')
            return
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_denegado_{ticket}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=chat_id, text=f"📋 *Confirmar Acción*\n¿Marcar el Ticket #{ticket} de {info['username']} como denegado?", reply_markup=reply_markup, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ *Error*: El ticket debe ser un número.", parse_mode='Markdown')

def handle_restar(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    args = context.args
    if len(args) != 2 or not args[0].startswith('@'):
        bot.send_message(chat_id=chat_id, text="❗ *Uso*: /restar @username [número]", parse_mode='Markdown')
        return
    username = args[0]
    try:
        amount = int(args[1])
        if amount <= 0:
            bot.send_message(chat_id=chat_id, text="❌ *Error*: El número debe ser positivo.", parse_mode='Markdown')
            return
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ *Error*: El segundo argumento debe ser un número.", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, count FROM peticiones_por_usuario WHERE username = %s", (username,))
        result = c.fetchone()
        if not result:
            bot.send_message(chat_id=chat_id, text=f"❌ *Error*: {username} no encontrado en las peticiones.", parse_mode='Markdown')
            return
        user_id, count = result
        new_count = max(0, count - amount)
        c.execute("UPDATE peticiones_por_usuario SET count = %s WHERE user_id = %s", (new_count, user_id))
        conn.commit()
    bot.send_message(chat_id=chat_id, text=f"✅ *Éxito*: Restadas {amount} peticiones a {username}. Nuevo conteo: {new_count}/2", parse_mode='Markdown')

def handle_sumar(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    args = context.args
    if len(args) != 2 or not args[0].startswith('@'):
        bot.send_message(chat_id=chat_id, text="❗ *Uso*: /sumar @username [número]", parse_mode='Markdown')
        return
    username = args[0]
    try:
        amount = int(args[1])
        if amount <= 0:
            bot.send_message(chat_id=chat_id, text="❌ *Error*: El número debe ser positivo.", parse_mode='Markdown')
            return
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ *Error*: El segundo argumento debe ser un número.", parse_mode='Markdown')
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, count FROM peticiones_por_usuario WHERE username = %s", (username,))
        result = c.fetchone()
        if not result:
            bot.send_message(chat_id=chat_id, text=f"❌ *Error*: {username} no encontrado en las peticiones.", parse_mode='Markdown')
            return
        user_id, count = result
        new_count = count + amount
        c.execute("UPDATE peticiones_por_usuario SET count = %s WHERE user_id = %s", (new_count, user_id))
        conn.commit()
    bot.send_message(chat_id=chat_id, text=f"✅ *Éxito*: Sumadas {amount} peticiones a {username}. Nuevo conteo: {new_count}/2", parse_mode='Markdown')

def handle_menu(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ *Acceso denegado*: Este comando solo está disponible en el grupo destino.", parse_mode='Markdown')
        return
    menu_message = (
        f"📋 *Menú de Comandos*\n"
        f"🔧 *Para usuarios:*\n"
        f"✅ {', '.join(VALID_REQUEST_COMMANDS)} - Enviar solicitud (máx. 2/día).\n"
        f"🔍 /estado [ticket] - Consultar estado.\n"
        f"📘 /ayuda - Ver guía rápida.\n"
        f"🔧 *Para administradores (en grupo destino):*\n"
        f"📋 /pendientes - Gestionar solicitudes.\n"
        f"➖ /restar @username [número] - Restar peticiones.\n"
        f"➕ /sumar @username [número] - Sumar peticiones.\n"
        f"🟢 /on - Activar solicitudes.\n"
        f"🔴 /off - Desactivar solicitudes.\n"
        f"🏠 /grupos - Ver estado de grupos.\n"
        f"📜 /historial - Ver solicitudes gestionadas.\n"
        f"📊 /estadistica - Ver estadísticas.\n"
        f"🏓 /ping - Verificar bot.\n"
        f"🤖 *Entreshijos Bot*"
    )
    bot.send_message(chat_id=chat_id, text=menu_message, parse_mode='Markdown')

def handle_ayuda(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    thread_id = update.message.message_thread_id if chat_id in CANALES_PETICIONES else None
    username = escape_markdown(f"@{update.message.from_user.username}", True) if update.message.from_user.username else "Usuario"
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})
    ayuda_message = (
        f"📘 *Ayuda del Bot*\n"
        f"Hola {username}, para enviar una solicitud usa:\n"
        f"📋 *Comandos válidos*: {', '.join(VALID_REQUEST_COMMANDS)}\n"
        f"🔍 Consulta el estado con: `/estado [ticket]`\n"
        f"📊 Límite: 2 solicitudes por día.\n"
        f"🤝 ¡Gracias por usar Entreshijos Bot!"
    )
    bot.send_message(chat_id=canal_info["chat_id"], text=ayuda_message, message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None, parse_mode='Markdown')

def handle_estado(update, context):
    if not update.message:
        return
    chat_id = update.message.chat_id
    thread_id = update.message.message_thread_id if chat_id in CANALES_PETICIONES else None
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})
    username = escape_markdown(f"@{update.message.from_user.username}", True) if update.message.from_user.username else "Usuario"
    args = context.args
    if not args:
        bot.send_message(chat_id=canal_info["chat_id"], text="❗ *Uso*: /estado [ticket]", message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None, parse_mode='Markdown')
        return
    try:
        ticket = int(args[0])
        info = get_peticion_registrada(ticket)
        if info:
            estado_message = (
                f"📋 *Estado del Ticket #{ticket}*\n"
                f"📝 *Mensaje*: {escape_markdown(info['message_text'])}\n"
                f"🏠 *Grupo*: {escape_markdown(info['chat_title'])}\n"
                f"📌 *Estado*: Pendiente ⏳\n"
                f"🕒 *Enviada*: {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}"
            )
        else:
            info = get_historial_solicitud(ticket)
            if info:
                estado_str = {
                    "subido": "✅ Aceptada",
                    "denegado": "❌ Denegada",
                    "eliminado": "🗑️ Eliminada",
                    "notificado": "📢 Respondida"
                }.get(info["estado"], "🔄 Desconocido")
                estado_message = (
                    f"📋 *Estado del Ticket #{ticket}*\n"
                    f"📝 *Mensaje*: {escape_markdown(info['message_text'])}\n"
                    f"🏠 *Grupo*: {escape_markdown(info['chat_title'])}\n"
                    f"📌 *Estado*: {estado_str}\n"
                    f"🕒 *Gestionada*: {info['fecha_gestion'].strftime('%d/%m/%Y %H:%M:%S')}\n"
                    f"👥 *Admin*: {info['admin_username']}"
                )
            else:
                estado_message = f"📋 *Estado del Ticket #{ticket}*\n❌ Ticket no encontrado."
        bot.send_message(chat_id=canal_info["chat_id"], text=estado_message, message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=canal_info["chat_id"], text="❗ *Error*: El ticket debe ser un número.", message_thread_id=canal_info["thread_id"] if thread_id == canal_info["thread_id"] else None, parse_mode='Markdown')

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
        query.edit_message_text(text="❌ *Acción cancelada.*", parse_mode='Markdown')
        return

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
                grupos_estados = get_grupos_estados()
                title = grupos_estados.get(grupo_id, {}).get("title", f"Grupo {grupo_id}")
                if grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                    grupos_seleccionados[chat_id]["grupos"].remove(grupo_id)
                    new_text = current_text.replace(f"\n{'🟢' if accion == 'on' else '🔴'} {title} seleccionado.", "")
                else:
                    grupos_seleccionados[chat_id]["grupos"].add(grupo_id)
                    new_text = current_text + f"\n{'🟢' if accion == 'on' else '🔴'} {title} seleccionado."

                if new_text != current_text:
                    keyboard = []
                    for gid, info in grupos_estados.items():
                        seleccionado = gid in grupos_seleccionados[chat_id]["grupos"]
                        callback = f"select_{accion}_{gid}"
                        keyboard.append([InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}{' ✅' if seleccionado else ''}",
                                                             callback_data=callback)])
                    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    query.edit_message_text(text=new_text, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if estado == "seleccion" and (data == "confirm_on" or data == "confirm_off"):
            accion = "on" if data == "confirm_on" else "off"
            if not grupos_seleccionados[chat_id]["grupos"]:
                query.edit_message_text(text=f"ℹ️ *Sin selección*: No se seleccionaron grupos para {'activar' if accion == 'on' else 'desactivar'}.", parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
                return

            grupos_seleccionados[chat_id]["estado"] = "confirmacion"
            grupos_estados = get_grupos_estados()
            grupos = "\n".join([grupos_estados[gid]["title"] for gid in grupos_seleccionados[chat_id]["grupos"]])
            texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'}*\n" \
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
                    "🎉 *¡Solicitudes reactivadas!*\nYa se pueden enviar solicitudes.\nMáximo 2 por día por usuario."
                ) if accion == "on" else (
                    "🚫 *Solicitudes desactivadas*\nNo se aceptan nuevas solicitudes hasta nuevo aviso.\nDisculpen las molestias."
                )
                for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                    canal_info = CANALES_PETICIONES.get(grupo_id, {"chat_id": grupo_id, "thread_id": None})
                    bot.send_message(chat_id=canal_info["chat_id"], text=mensaje, message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
                    set_grupo_estado(grupo_id, get_grupos_estados()[grupo_id]["title"], accion == "on")
                texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} y notificadas.*"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
            elif decision == "no":
                grupos_estados = get_grupos_estados()
                for grupo_id in grupos_seleccionados[chat_id]["grupos"]:
                    set_grupo_estado(grupo_id, grupos_estados[grupo_id]["title"], accion == "on")
                texto = f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'} sin notificación.*"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del grupos_seleccionados[chat_id]
            return

        if estado == "confirmacion" and data.startswith("back_"):
            accion = data.split("_")[1]
            grupos_seleccionados[chat_id]["estado"] = "seleccion"
            grupos_estados = get_grupos_estados()
            keyboard = []
            for gid, info in grupos_estados.items():
                seleccionado = gid in grupos_seleccionados[chat_id]["grupos"]
                callback = f"select_{accion}_{gid}"
                keyboard.append([InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}{' ✅' if seleccionado else ''}",
                                                     callback_data=callback)])
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"{'🟢' if accion == 'on' else '🔴'} *{'Activar' if accion == 'on' else 'Desactivar'} Solicitudes*\nSelecciona los grupos:"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

    if data.startswith("pend_"):
        if data == "pend_regresar":
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT ticket_number, username, chat_title FROM peticiones_registradas ORDER BY ticket_number")
                pendientes = c.fetchall()
            keyboard = [[InlineKeyboardButton(f"#{ticket} - {username} ({chat_title})",
                                             callback_data=f"pend_{ticket}")] for ticket, username, chat_title in pendientes]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = "📋 *Solicitudes Pendientes*\nSelecciona una solicitud:"
            if texto != current_text or str(reply_markup) != str(current_markup):
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar ticket en callback pend_: {data}")
            return

        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ *Error*: Ticket #{ticket} no encontrado.", parse_mode='Markdown')
            return

        if len(data.split("_")) == 2:
            keyboard = [
                [InlineKeyboardButton("✅ Subido", callback_data=f"pend_{ticket}_subido")],
                [InlineKeyboardButton("❌ Denegado", callback_data=f"pend_{ticket}_denegado")],
                [InlineKeyboardButton("🗑️ Eliminar", callback_data=f"pend_{ticket}_eliminar")],
                [InlineKeyboardButton("🔙 Regresar", callback_data="pend_regresar")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = (
                f"📋 *Solicitud #{ticket}*\n"
                f"👤 *Usuario*: {escape_markdown(info['username'], True)}\n"
                f"📝 *Mensaje*: {escape_markdown(info['message_text'])}\n"
                f"🏠 *Grupo*: {escape_markdown(info['chat_title'])}\n"
                f"🕒 *Fecha*: {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}\n"
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
            texto = f"📋 *Confirmar Acción*\n¿Marcar el Ticket #{ticket} de {info['username']} como {accion_str}?"
            query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        if len(data.split("_")) == 4 and data.endswith("confirm"):
            accion = data.split("_")[2]
            username_escaped = escape_markdown(info["username"], True)
            message_text_escaped = escape_markdown(info["message_text"])
            user_chat_id = info["chat_id"]
            message_id = info["message_id"]
            thread_id = info.get("thread_id")

            set_historial_solicitud(ticket, {
                "chat_id": user_chat_id,
                "username": info["username"],
                "message_text": info["message_text"],
                "chat_title": info["chat_title"],
                "estado": accion,
                "fecha_gestion": datetime.now(SPAIN_TZ),
                "admin_username": admin_username
            })

            if accion == "subido":
                notificacion = f"✅ *Éxito*: {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido subida."
                bot.send_message(chat_id=user_chat_id, text=notificacion, message_thread_id=thread_id, parse_mode='Markdown')
                texto = f"✅ *Ticket #{ticket} procesado como subido.*"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del_peticion_registrada(ticket)

            elif accion == "denegado":
                notificacion = f"❌ *Aviso*: {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada."
                bot.send_message(chat_id=user_chat_id, text=notificacion, message_thread_id=thread_id, parse_mode='Markdown')
                texto = f"✅ *Ticket #{ticket} procesado como denegado.*"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del_peticion_registrada(ticket)

            elif accion == "eliminar":
                try:
                    bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
                    bot.send_message(chat_id=chat_id, text=f"✅ *Éxito*: Ticket #{ticket} de {username_escaped} eliminado.", parse_mode='Markdown')
                except telegram.error.TelegramError as e:
                    bot.send_message(chat_id=chat_id, text=f"⚠️ *Advertencia*: No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos.", parse_mode='Markdown')
                notificacion = f"ℹ️ *Aviso*: {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada."
                bot.send_message(chat_id=user_chat_id, text=notificacion, message_thread_id=thread_id, parse_mode='Markdown')
                texto = f"✅ *Ticket #{ticket} procesado como eliminado.*"
                query.edit_message_text(text=texto, parse_mode='Markdown')
                del_peticion_registrada(ticket)

    if data.startswith("eliminar_"):
        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar eliminar_ callback: {data}")
            return

        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ *Error*: Ticket #{ticket} no encontrado.", parse_mode='Markdown')
            return

        if len(data.split("_")) == 2:
            keyboard = [
                [InlineKeyboardButton("✅ Aprobada", callback_data=f"eliminar_{ticket}_aprobada")],
                [InlineKeyboardButton("❌ Denegada", callback_data=f"eliminar_{ticket}_denegada")],
                [InlineKeyboardButton("🗑️ Eliminada", callback_data=f"eliminar_{ticket}_eliminada")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"🗑️ *Eliminar Ticket #{ticket}*\nSelecciona el estado:"
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

        set_historial_solicitud(ticket, {
            "chat_id": user_chat_id,
            "username": username,
            "message_text": message_text,
            "chat_title": info["chat_title"],
            "estado": "eliminado" if estado == "eliminada" else estado,
            "fecha_gestion": datetime.now(SPAIN_TZ),
            "admin_username": admin_username
        })

        try:
            bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
            bot.send_message(chat_id=chat_id, text=f"✅ *Éxito*: Ticket #{ticket} de {escape_markdown(username, True)} eliminado ({estado}).", parse_mode='Markdown')
        except telegram.error.TelegramError as e:
            bot.send_message(chat_id=chat_id, text=f"⚠️ *Advertencia*: No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos.", parse_mode='Markdown')

        username_escaped = escape_markdown(username, True)
        message_text_escaped = escape_markdown(message_text)

        if estado == "aprobada":
            notificacion = f"✅ *Éxito*: {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido aprobada."
            historial = get_historial_solicitud(ticket)
            historial["estado"] = "subido"
            set_historial_solicitud(ticket, historial)
        elif estado == "denegada":
            notificacion = f"❌ *Aviso*: {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada."
            historial = get_historial_solicitud(ticket)
            historial["estado"] = "denegado"
            set_historial_solicitud(ticket, historial)
        else:
            notificacion = f"ℹ️ *Aviso*: {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada."

        bot.send_message(chat_id=user_chat_id, text=notificacion, message_thread_id=thread_id, parse_mode='Markdown')
        texto = f"✅ *Ticket #{ticket} procesado como {estado}.*"
        query.edit_message_text(text=texto, parse_mode='Markdown')
        del_peticion_registrada(ticket)

    if data.startswith("confirm_subido_"):
        ticket = int(data.split("_")[2])
        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ *Error*: Ticket #{ticket} no encontrado.", parse_mode='Markdown')
            return
        set_historial_solicitud(ticket, {
            "chat_id": info["chat_id"],
            "username": info["username"],
            "message_text": info["message_text"],
            "chat_title": info["chat_title"],
            "estado": "subido",
            "fecha_gestion": datetime.now(SPAIN_TZ),
            "admin_username": admin_username
        })
        bot.send_message(chat_id=info["chat_id"], text=f"✅ *Éxito*: {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido subida.", message_thread_id=info.get("thread_id"), parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ *Éxito*: Ticket #{ticket} marcado como subido.", parse_mode='Markdown')
        query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como subido.*", parse_mode='Markdown')
        del_peticion_registrada(ticket)

    if data.startswith("confirm_denegado_"):
        ticket = int(data.split("_")[2])
        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ *Error*: Ticket #{ticket} no encontrado.", parse_mode='Markdown')
            return
        set_historial_solicitud(ticket, {
            "chat_id": info["chat_id"],
            "username": info["username"],
            "message_text": info["message_text"],
            "chat_title": info["chat_title"],
            "estado": "denegado",
            "fecha_gestion": datetime.now(SPAIN_TZ),
            "admin_username": admin_username
        })
        bot.send_message(chat_id=info["chat_id"], text=f"❌ *Aviso*: {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido denegada.", message_thread_id=info.get("thread_id"), parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ *Éxito*: Ticket #{ticket} marcado como denegado.", parse_mode='Markdown')
        query.edit_message_text(text=f"✅ *Ticket #{ticket} procesado como denegado.*", parse_mode='Markdown')
        del_peticion_registrada(ticket)

# Variable global para selección de grupos
grupos_seleccionados = {}

# Añadir handlers
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
dispatcher.add_handler(CommandHandler('estadistica', handle_estadistica))
dispatcher.add_handler(CommandHandler('on', handle_on))
dispatcher.add_handler(CommandHandler('off', handle_off))
dispatcher.add_handler(CommandHandler('grupos', handle_grupos))
dispatcher.add_handler(CommandHandler('historial', handle_historial))
dispatcher.add_handler(CommandHandler('pendientes', handle_pendientes))
dispatcher.add_handler(CommandHandler('eliminar', handle_eliminar))
dispatcher.add_handler(CommandHandler('ping', handle_ping))
dispatcher.add_handler(CommandHandler('subido', handle_subido))
dispatcher.add_handler(CommandHandler('denegado', handle_denegado))
dispatcher.add_handler(CommandHandler('restar', handle_restar))
dispatcher.add_handler(CommandHandler('sumar', handle_sumar))
dispatcher.add_handler(CommandHandler('menu', handle_menu))
dispatcher.add_handler(CommandHandler('ayuda', handle_ayuda))
dispatcher.add_handler(CommandHandler('estado', handle_estado))
dispatcher.add_handler(CallbackQueryHandler(button_handler))

# Rutas Flask
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = telegram.Update.de_json(request.get_json(force=True), bot)
        if not update:
            return 'Invalid update', 400
        dispatcher.process_update(update)
        return 'ok', 200
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return f'Error: {str(e)}', 500

@app.route('/')
def health_check():
    return "🤖 *Entreshijos Bot* está activo!", 200

if __name__ == '__main__':
    init_db()
    for chat_id, title in GRUPOS_PREDEFINIDOS.items():
        set_grupo_estado(chat_id, title)
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
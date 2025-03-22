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

# Configuración
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada en las variables de entorno.")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicialización
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=1)
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Base de datos
def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_por_usuario 
                     (user_id BIGINT PRIMARY KEY, count INTEGER DEFAULT 0, chat_id BIGINT, username TEXT, 
                      last_reset TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_registradas 
                     (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                      message_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_title TEXT, thread_id BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS historial_solicitudes 
                     (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                      chat_title TEXT, estado TEXT, fecha_gestion TIMESTAMP WITH TIME ZONE, admin_username TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS procesado 
                     (id BIGINT PRIMARY KEY, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS peticiones_incorrectas 
                     (id SERIAL PRIMARY KEY, user_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_id BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS grupos_estados 
                     (chat_id BIGINT PRIMARY KEY, title TEXT, activo BOOLEAN DEFAULT TRUE)''')
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
    now = datetime.now(SPAIN_TZ)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT count, chat_id, username, last_reset FROM peticiones_por_usuario WHERE user_id = %s", (user_id,))
        result = c.fetchone()
        if result:
            data = dict(result)
            last_reset = data['last_reset'].astimezone(SPAIN_TZ)
            if now.date() > last_reset.date():
                # Reiniciar conteo si ha pasado un día
                c.execute("UPDATE peticiones_por_usuario SET count = 0, last_reset = %s WHERE user_id = %s", (now, user_id))
                conn.commit()
                data['count'] = 0
                data['last_reset'] = now
            return data
        return None

def set_peticiones_por_usuario(user_id, count, chat_id, username):
    now = datetime.now(SPAIN_TZ)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO peticiones_por_usuario (user_id, count, chat_id, username, last_reset) 
                     VALUES (%s, %s, %s, %s, %s)
                     ON CONFLICT (user_id) DO UPDATE SET 
                     count = %s, chat_id = %s, username = %s, last_reset = %s""",
                  (user_id, count, chat_id, username, now, count, chat_id, username, now))
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

def is_procesado(update_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM procesado WHERE id = %s", (update_id,))
        return c.fetchone() is not None

def set_procesado(update_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO procesado (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (update_id,))
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
                     ON CONFLICT (chat_id) DO UPDATE SET title = %s, activo = %s""",
                  (chat_id, title, activo, title, activo))
        conn.commit()

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
ping_respuestas = [
    "🏓 *¡Pong!* Estoy listo para ayudar. 🌟",
    "🎾 *¡Pong!* Aquí estoy, funcionando al 100%. 💪",
    "🚀 *¡Pong!* Todo en orden, listo para despegar. 🌍",
    "🎉 *¡Pong!* Online y a tu servicio. 🥳"
]

# Funciones de utilidad
def escape_markdown(text, preserve_username=False):
    if not text:
        return text
    if preserve_username and text.startswith('@'):
        return text
    characters = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    return ''.join(f'\\{char}' if char in characters else char for char in text)

def update_grupos_estados(chat_id, title=None):
    grupos = get_grupos_estados()
    if chat_id not in grupos:
        set_grupo_estado(chat_id, title or f"Grupo {chat_id}")
    elif title and grupos[chat_id]["title"] == f"Grupo {chat_id}":
        set_grupo_estado(chat_id, title)

def get_spain_time():
    return datetime.now(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')

# Handlers
def handle_message(update, context):
    if not update.message:
        return
    update_id = update.update_id
    if is_procesado(update_id):
        return
    set_procesado(update_id)

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text or ''
    chat_title = message.chat.title or 'Chat privado'
    thread_id = message.message_thread_id
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})

    update_grupos_estados(chat_id, chat_title)
    grupos = get_grupos_estados()

    timestamp = datetime.now(SPAIN_TZ)
    username_escaped = escape_markdown(username, True)
    chat_title_escaped = escape_markdown(chat_title)
    message_text_escaped = escape_markdown(message_text)
    is_valid_request = any(cmd in message_text for cmd in VALID_REQUEST_COMMANDS)

    if is_valid_request:
        if chat_id not in CANALES_PETICIONES or thread_id != CANALES_PETICIONES[chat_id]["thread_id"]:
            bot.send_message(chat_id=canal_info["chat_id"], text=f"🚫 {username_escaped}, usa el canal correcto. 🌟",
                             message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            bot.send_message(chat_id=canal_info["chat_id"], text=f"/warn {username_escaped} Petición fuera de lugar",
                             message_thread_id=canal_info["thread_id"])
            return

        if not grupos.get(chat_id, {}).get("activo", True):
            bot.send_message(chat_id=canal_info["chat_id"], text=f"🚫 {username_escaped}, solicitudes desactivadas. 🌟",
                             message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            return

        user_data = get_peticiones_por_usuario(user_id) or {"count": 0, "chat_id": chat_id, "username": username}
        if user_data["count"] >= 2 and user_id not in admin_ids:
            bot.send_message(chat_id=canal_info["chat_id"], text=f"🚫 {username_escaped}, límite alcanzado. Intenta mañana. 🌟",
                             message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            bot.send_message(chat_id=canal_info["chat_id"], text=f"/warn {username_escaped} Límite excedido",
                             message_thread_id=canal_info["thread_id"])
            return

        user_data["count"] += 1
        set_peticiones_por_usuario(user_id, user_data["count"], chat_id, username)
        ticket_number = increment_ticket_counter()
        destino_message = (
            f"📬 *Nueva solicitud* 🌟\n"
            f"👤 *Usuario:* {username_escaped} (ID: {user_id})\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"📊 *Petición:* {user_data['count']}/2\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {get_spain_time()}"
        )
        sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
        set_peticion_registrada(ticket_number, {
            "chat_id": chat_id, "username": username, "message_text": message_text,
            "message_id": sent_message.message_id, "timestamp": timestamp, "chat_title": chat_title, "thread_id": thread_id
        })

    elif any(word in message_text.lower() for word in ['solicito', 'solícito', 'peticion', 'petición']) and chat_id in CANALES_PETICIONES:
        add_peticion_incorrecta(user_id, timestamp, chat_id)
        intentos = len([i for i in get_peticiones_incorrectas(user_id) if i["timestamp"] > timestamp - timedelta(hours=24)])
        bot.send_message(chat_id=canal_info["chat_id"], text=f"⚠️ {username_escaped}, usa: {', '.join(VALID_REQUEST_COMMANDS[:4])}. 🌟",
                         message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
        bot.send_message(chat_id=canal_info["chat_id"], text=f"/warn {username_escaped} {'Abuso' if intentos > 2 else 'Formato incorrecto'}",
                         message_thread_id=canal_info["thread_id"])

def handle_on(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    grupos = get_grupos_estados()
    if not grupos:
        bot.send_message(chat_id=update.message.chat_id, text="ℹ️ No hay grupos registrados. 🌟", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}", callback_data=f"select_on_{gid}")]
                for gid, info in grupos.items()]
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_on")])
    grupos_seleccionados[update.message.chat_id] = {"accion": "on", "grupos": set(), "mensaje_id": None}
    sent = bot.send_message(chat_id=update.message.chat_id, text="🟢 *Activar solicitudes* 🌟\nSelecciona grupos:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    grupos_seleccionados[update.message.chat_id]["mensaje_id"] = sent.message_id

def handle_off(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    grupos = get_grupos_estados()
    if not grupos:
        bot.send_message(chat_id=update.message.chat_id, text="ℹ️ No hay grupos registrados. 🌟", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}", callback_data=f"select_off_{gid}")]
                for gid, info in grupos.items()]
    keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data="confirm_off")])
    grupos_seleccionados[update.message.chat_id] = {"accion": "off", "grupos": set(), "mensaje_id": None}
    sent = bot.send_message(chat_id=update.message.chat_id, text="🔴 *Desactivar solicitudes* 🌟\nSelecciona grupos:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    grupos_seleccionados[update.message.chat_id]["mensaje_id"] = sent.message_id

def handle_grupos(update, context):
    chat_id = update.effective_chat.id
    if str(chat_id) != GROUP_DESTINO:
        return
    grupos = get_grupos_estados()
    if not grupos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados. 🌟", parse_mode='Markdown')
        return
    estado = "\n".join([f"🏠 {info['title']}: {'🟢 Activo' if info['activo'] else '🔴 Inactivo'} (ID: {gid})"
                        for gid, info in sorted(grupos.items())])
    bot.send_message(chat_id=chat_id, text=f"📋 *Estado de grupos* 🌟\n{estado}", parse_mode='Markdown')

def handle_historial(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT ticket_number, username, message_text, chat_title, estado, fecha_gestion, admin_username "
                  "FROM historial_solicitudes ORDER BY ticket_number DESC LIMIT 10")
        solicitudes = c.fetchall()
    if not solicitudes:
        bot.send_message(chat_id=update.message.chat_id, text="ℹ️ No hay historial. 🌟", parse_mode='Markdown')
        return
    historial = [f"🎫 *#{row[0]}*: {row[1]} - {row[4]} ({row[5].strftime('%d/%m/%Y')})" for row in solicitudes]
    bot.send_message(chat_id=update.message.chat_id, text="📜 *Historial* 🌟\n" + "\n".join(historial), parse_mode='Markdown')

def handle_pendientes(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT ticket_number, username, chat_title FROM peticiones_registradas ORDER BY ticket_number")
        pendientes = c.fetchall()
    if not pendientes:
        bot.send_message(chat_id=update.message.chat_id, text="ℹ️ No hay pendientes. 🌟", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"#{t} - {u} ({c})", callback_data=f"pend_{t}")] for t, u, c in pendientes]
    bot.send_message(chat_id=update.message.chat_id, text="📋 *Pendientes* 🌟\nSelecciona:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def handle_eliminar(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT ticket_number, username FROM peticiones_registradas")
        pendientes = c.fetchall()
    if not pendientes:
        bot.send_message(chat_id=update.message.chat_id, text="ℹ️ No hay pendientes para eliminar. 🌟", parse_mode='Markdown')
        return
    keyboard = [[InlineKeyboardButton(f"#{t} - {u}", callback_data=f"eliminar_{t}")] for t, u in pendientes]
    bot.send_message(chat_id=update.message.chat_id, text="🗑️ *Eliminar* 🌟\nSelecciona:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def handle_ping(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    bot.send_message(chat_id=update.message.chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')

def handle_subido(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO or len(context.args) != 1:
        return
    try:
        ticket = int(context.args[0])
        info = get_peticion_registrada(ticket)
        if info:
            keyboard = [[InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_subido_{ticket}"),
                         InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]]
            bot.send_message(chat_id=update.message.chat_id, text=f"📋 ¿Marcar #{ticket} como subido?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except ValueError:
        pass

def handle_denegado(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO or len(context.args) != 1:
        return
    try:
        ticket = int(context.args[0])
        info = get_peticion_registrada(ticket)
        if info:
            keyboard = [[InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_denegado_{ticket}"),
                         InlineKeyboardButton("❌ Cancelar", callback_data="cancel_action")]]
            bot.send_message(chat_id=update.message.chat_id, text=f"📋 ¿Marcar #{ticket} como denegado?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except ValueError:
        pass

def handle_restar(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO or len(context.args) != 2:
        return
    username, amount = context.args[0], int(context.args[1])
    if not username.startswith('@') or amount <= 0:
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, count FROM peticiones_por_usuario WHERE username = %s", (username,))
        result = c.fetchone()
        if result:
            user_id, count = result
            new_count = max(0, count - amount)
            c.execute("UPDATE peticiones_por_usuario SET count = %s WHERE user_id = %s", (new_count, user_id))
            conn.commit()
            bot.send_message(chat_id=update.message.chat_id, text=f"✅ {username}: {new_count}/2 🌟", parse_mode='Markdown')

def handle_sumar(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO or len(context.args) != 2:
        return
    username, amount = context.args[0], int(context.args[1])
    if not username.startswith('@') or amount <= 0:
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, count FROM peticiones_por_usuario WHERE username = %s", (username,))
        result = c.fetchone()
        if result:
            user_id, count = result
            new_count = count + amount
            c.execute("UPDATE peticiones_por_usuario SET count = %s WHERE user_id = %s", (new_count, user_id))
            conn.commit()
            bot.send_message(chat_id=update.message.chat_id, text=f"✅ {username}: {new_count}/2 🌟", parse_mode='Markdown')

def button_handler(update, context):
    query = update.callback_query
    if not query:
        return
    query.answer()
    data = query.data
    chat_id = query.message.chat_id
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin"

    if data.startswith("select_"):
        accion, gid = data.split("_")[1], int(data.split("_")[2])
        if chat_id in grupos_seleccionados and query.message.message_id == grupos_seleccionados[chat_id]["mensaje_id"]:
            grupos_seleccionados[chat_id]["grupos"].toggle(gid)
            grupos = get_grupos_estados()
            keyboard = [[InlineKeyboardButton(f"{info['title']} {'🟢' if info['activo'] else '🔴'}{' ✅' if gid in grupos_seleccionados[chat_id]['grupos'] else ''}", 
                                              callback_data=f"select_{accion}_{gid}")] for gid, info in grupos.items()]
            keyboard.append([InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{accion}")])
            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("confirm_on") or data.startswith("confirm_off"):
        accion = "on" if "on" in data else "off"
        if chat_id in grupos_seleccionados and grupos_seleccionados[chat_id]["grupos"]:
            for gid in grupos_seleccionados[chat_id]["grupos"]:
                set_grupo_estado(gid, get_grupos_estados()[gid]["title"], accion == "on")
            query.edit_message_text(text=f"{'🟢' if accion == 'on' else '🔴'} *Solicitudes {'activadas' if accion == 'on' else 'desactivadas'}* 🌟", parse_mode='Markdown')
            del grupos_seleccionados[chat_id]

    elif data.startswith("pend_"):
        ticket = int(data.split("_")[1])
        info = get_peticion_registrada(ticket)
        if info:
            keyboard = [[InlineKeyboardButton("✅ Subido", callback_data=f"confirm_subido_{ticket}"),
                         InlineKeyboardButton("❌ Denegado", callback_data=f"confirm_denegado_{ticket}"),
                         InlineKeyboardButton("🗑️ Eliminar", callback_data=f"eliminar_{ticket}")]]
            query.edit_message_text(text=f"📋 *#{ticket}* - {info['username']}: {info['message_text']}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("confirm_subido_") or data.startswith("confirm_denegado_"):
        ticket = int(data.split("_")[2])
        info = get_peticion_registrada(ticket)
        if info:
            estado = "subido" if "subido" in data else "denegado"
            set_historial_solicitud(ticket, {"chat_id": info["chat_id"], "username": info["username"], "message_text": info["message_text"],
                                             "chat_title": info["chat_title"], "estado": estado, "fecha_gestion": datetime.now(SPAIN_TZ), "admin_username": admin_username})
            bot.send_message(chat_id=info["chat_id"], text=f"{'✅' if estado == 'subido' else '❌'} Tu solicitud #{ticket} ha sido {estado}. 🌟",
                             message_thread_id=info["thread_id"], parse_mode='Markdown')
            query.edit_message_text(text=f"✅ *#{ticket} {estado}* 🌟", parse_mode='Markdown')
            del_peticion_registrada(ticket)

    elif data.startswith("eliminar_"):
        ticket = int(data.split("_")[1])
        info = get_peticion_registrada(ticket)
        if info:
            set_historial_solicitud(ticket, {"chat_id": info["chat_id"], "username": info["username"], "message_text": info["message_text"],
                                             "chat_title": info["chat_title"], "estado": "eliminado", "fecha_gestion": datetime.now(SPAIN_TZ), "admin_username": admin_username})
            bot.send_message(chat_id=info["chat_id"], text=f"ℹ️ Tu solicitud #{ticket} ha sido eliminada. 🌟",
                             message_thread_id=info["thread_id"], parse_mode='Markdown')
            query.edit_message_text(text=f"✅ *#{ticket} eliminado* 🌟", parse_mode='Markdown')
            del_peticion_registrada(ticket)

def handle_menu(update, context):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    bot.send_message(chat_id=update.message.chat_id, text="📋 *Menú* 🌟\n/pendientes /historial /on /off /grupos /ping /restar /sumar", parse_mode='Markdown')

def handle_ayuda(update, context):
    if not update.message:
        return
    bot.send_message(chat_id=update.message.chat_id, text=f"📖 *Ayuda* 🌟\nUsa {', '.join(VALID_REQUEST_COMMANDS[:4])} para solicitar (2/día).", parse_mode='Markdown')

def handle_estado(update, context):
    if not update.message or not context.args:
        return
    ticket = int(context.args[0])
    info = get_peticion_registrada(ticket) or get_historial_solicitud(ticket)
    if info:
        estado = info.get("estado", "Pendiente")
        bot.send_message(chat_id=update.message.chat_id, text=f"📋 *#{ticket}*: {estado} 🌟", parse_mode='Markdown')

# Configuración de handlers
grupos_seleccionados = {}
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
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
        if update:
            dispatcher.process_update(update)
        return 'ok', 200
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return 'Error', 500

@app.route('/')
def health_check():
    return "Bot activo 🌟", 200

# Inicialización
init_db()
for chat_id, title in GRUPOS_PREDEFINIDOS.items():
    set_grupo_estado(chat_id, title)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
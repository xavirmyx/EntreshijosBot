import os
import logging
import random
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import psycopg2
from psycopg2.pool import SimpleConnectionPool
import psycopg2.extras
import asyncio

# Configuración inicial
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada.")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Zona horaria
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Pool de conexiones a la base de datos
db_pool = SimpleConnectionPool(1, 10, dsn=DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

# Cache en memoria
grupos_estados_cache = {}
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
    '/solicito', '/solícito', '/SOLÍCITO', '/SOLICITO', '/Solicito', '/Solícito',
    '#solicito', '#solícito', '#SOLÍCITO', '#SOLICITO', '#Solícito', '#Solicito',
    '/petición', '/peticion', '/PETICIÓN', '/PETICION', '/Petición', '/Peticion',
    '#petición', '#peticion', '#PETICIÓN', '#PETICION', '#Petición', '#Peticion',
]
frases_agradecimiento = [
    "¡Eres un crack por esperar! 😎",
    "¡Gracias por confiar en nosotros! 🌟",
    "¡Tu paciencia es oro puro! 🏆",
    "¡Gracias por darle vida al bot! 🎉"
]
ping_respuestas = [
    "🎯 ¡Pong! Aquí estoy, más rápido que un rayo. ⚡",
    "🔔 ¡Pong! El bot está ON y listo para la acción. 💥",
    "🌍 ¡Pong! Conectado y girando como el mundo. 😄",
    "🚀 ¡Pong! Despegando con todo el power. ✨"
]

# Funciones de utilidad
def escape_markdown(text, preserve_username=False):
    if not text:
        return text
    if preserve_username and text.startswith('@'):
        return ''.join(['\\' + c if c in '_*[]()~`>#+-=|{}.!' else c for c in text])
    characters_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    return ''.join(['\\' + c if c in characters_to_escape else c for c in text])

def get_spain_time():
    return datetime.now(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')

# Funciones de base de datos
def init_db():
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS peticiones_por_usuario 
                         (user_id BIGINT PRIMARY KEY, count INTEGER, chat_id BIGINT, username TEXT, last_reset TIMESTAMP WITH TIME ZONE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS peticiones_registradas 
                         (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                          message_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_title TEXT, thread_id BIGINT, 
                          prioridad BOOLEAN DEFAULT FALSE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS historial_solicitudes 
                         (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                          chat_title TEXT, estado TEXT, fecha_gestion TIMESTAMP WITH TIME ZONE, admin_username TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS grupos_estados 
                         (chat_id BIGINT PRIMARY KEY, title TEXT, activo BOOLEAN DEFAULT TRUE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                         (user_id BIGINT PRIMARY KEY, username TEXT)''')
            conn.commit()
            logger.info("Base de datos inicializada.")
    finally:
        db_pool.putconn(conn)

async def get_ticket_counter():
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("SELECT COALESCE(MAX(ticket_number), 0) FROM peticiones_registradas")
            max_registradas = c.fetchone()[0]
            c.execute("SELECT COALESCE(MAX(ticket_number), 0) FROM historial_solicitudes")
            max_historial = c.fetchone()[0]
            return max(max_registradas, max_historial)
    finally:
        db_pool.putconn(conn)

async def increment_ticket_counter():
    return await get_ticket_counter() + 1

async def get_peticiones_por_usuario(user_id):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("SELECT count, chat_id, username, last_reset FROM peticiones_por_usuario WHERE user_id = %s", (user_id,))
            result = c.fetchone()
            if result:
                result_dict = dict(result)
                now = datetime.now(SPAIN_TZ)
                last_reset = result_dict['last_reset'].astimezone(SPAIN_TZ) if result_dict['last_reset'] else None
                if not last_reset or (now - last_reset).total_seconds() >= 86400:
                    result_dict['count'] = 0
                    result_dict['last_reset'] = now
                    await set_peticiones_por_usuario(user_id, 0, result_dict['chat_id'], result_dict['username'], now)
                return result_dict
            return None
    finally:
        db_pool.putconn(conn)

async def set_peticiones_por_usuario(user_id, count, chat_id, username, last_reset=None):
    if last_reset is None:
        last_reset = datetime.now(SPAIN_TZ)
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO peticiones_por_usuario (user_id, count, chat_id, username, last_reset) 
                         VALUES (%s, %s, %s, %s, %s)
                         ON CONFLICT (user_id) DO UPDATE SET count = EXCLUDED.count, chat_id = EXCLUDED.chat_id, 
                         username = EXCLUDED.username, last_reset = EXCLUDED.last_reset""",
                      (user_id, count, chat_id, username, last_reset))
            c.execute("""INSERT INTO usuarios (user_id, username) 
                         VALUES (%s, %s) 
                         ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                      (user_id, username))
            conn.commit()
    finally:
        db_pool.putconn(conn)

async def get_peticion_registrada(ticket_number):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("SELECT chat_id, username, message_text, message_id, timestamp, chat_title, thread_id, prioridad "
                      "FROM peticiones_registradas WHERE ticket_number = %s", (ticket_number,))
            result = c.fetchone()
            return dict(result) if result else None
    finally:
        db_pool.putconn(conn)

async def set_peticion_registrada(ticket_number, data):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO peticiones_registradas 
                         (ticket_number, chat_id, username, message_text, message_id, timestamp, chat_title, thread_id, prioridad) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (ticket_number) DO UPDATE SET chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, 
                         message_text = EXCLUDED.message_text, message_id = EXCLUDED.message_id, timestamp = EXCLUDED.timestamp, 
                         chat_title = EXCLUDED.chat_title, thread_id = EXCLUDED.thread_id, prioridad = EXCLUDED.prioridad""",
                      (ticket_number, data["chat_id"], data["username"], data["message_text"],
                       data["message_id"], data["timestamp"], data["chat_title"], data["thread_id"], 
                       data.get("prioridad", False)))
            conn.commit()
    finally:
        db_pool.putconn(conn)

async def del_peticion_registrada(ticket_number):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM peticiones_registradas WHERE ticket_number = %s", (ticket_number,))
            conn.commit()
    finally:
        db_pool.putconn(conn)

async def set_historial_solicitud(ticket_number, data):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO historial_solicitudes 
                         (ticket_number, chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (ticket_number) DO UPDATE SET chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, 
                         message_text = EXCLUDED.message_text, chat_title = EXCLUDED.chat_title, estado = EXCLUDED.estado, 
                         fecha_gestion = EXCLUDED.fecha_gestion, admin_username = EXCLUDED.admin_username""",
                      (ticket_number, data["chat_id"], data["username"], data["message_text"],
                       data["chat_title"], data["estado"], data["fecha_gestion"], data["admin_username"]))
            conn.commit()
    finally:
        db_pool.putconn(conn)

async def get_grupos_estados():
    if not grupos_estados_cache:
        conn = db_pool.getconn()
        try:
            with conn.cursor() as c:
                c.execute("SELECT chat_id, title, activo FROM grupos_estados")
                grupos_estados_cache.update({row['chat_id']: {'title': row['title'], 'activo': row['activo']} for row in c.fetchall()})
        finally:
            db_pool.putconn(conn)
    return grupos_estados_cache

async def set_grupo_estado(chat_id, title, activo=True):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO grupos_estados (chat_id, title, activo) 
                         VALUES (%s, %s, %s) 
                         ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, activo = EXCLUDED.activo""",
                      (chat_id, title, activo))
            conn.commit()
        grupos_estados_cache[chat_id] = {'title': title, 'activo': activo}
    finally:
        db_pool.putconn(conn)

async def update_grupos_estados(chat_id, title=None):
    if chat_id > 0 or str(chat_id) == GROUP_DESTINO:
        return
    grupos = await get_grupos_estados()
    if chat_id not in grupos:
        await set_grupo_estado(chat_id, title if title else f"Grupo {chat_id}")
    elif title and grupos[chat_id]["title"] == f"Grupo {chat_id}":
        await set_grupo_estado(chat_id, title)

# Manejadores
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    message_text = message.text
    chat_title = message.chat.title or 'Chat privado'
    thread_id = message.message_thread_id
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})

    await update_grupos_estados(chat_id, chat_title)
    timestamp = datetime.now(SPAIN_TZ)
    timestamp_str = get_spain_time()
    username_escaped = escape_markdown(username, preserve_username=True)
    chat_title_escaped = escape_markdown(chat_title)
    message_text_escaped = escape_markdown(message_text)
    is_valid_request = any(cmd in message_text for cmd in VALID_REQUEST_COMMANDS)
    grupos_estados = await get_grupos_estados()

    if is_valid_request:
        if chat_id not in CANALES_PETICIONES or thread_id != CANALES_PETICIONES[chat_id]["thread_id"]:
            await context.bot.send_message(chat_id=canal_info["chat_id"], text=f"⛔ Oops, {username_escaped}, parece que te equivocaste de canal. ¡Usa el canal de peticiones! 😉", 
                                           message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            return
        if not grupos_estados.get(chat_id, {}).get("activo", True):
            await context.bot.send_message(chat_id=canal_info["chat_id"], text=f"🚫 ¡Ey, {username_escaped}! Las solicitudes están pausadas aquí. Habla con un admin. 😊", 
                                           message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            return
        user_data = await get_peticiones_por_usuario(user_id) or {"count": 0, "chat_id": chat_id, "username": username}
        if user_data["count"] >= 2:
            await context.bot.send_message(chat_id=canal_info["chat_id"], text=f"⛔ ¡Ups, {username_escaped}! Has llegado al límite de 2 peticiones hoy. ¡Vuelve mañana! 😄", 
                                           message_thread_id=canal_info["thread_id"], parse_mode='Markdown')
            return

        ticket_number = await increment_ticket_counter()
        destino_message = (
            f"📬 *¡Nueva solicitud!* 🚀\n"
            f"👤 *Usuario:* {username_escaped} (ID: {user_id})\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp_str}\n"
            "✨ *Bot de Entreshijos*"
        )
        sent_message = await context.bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
        await set_peticion_registrada(ticket_number, {
            "chat_id": chat_id, "username": username, "message_text": message_text,
            "message_id": sent_message.message_id, "timestamp": timestamp, "chat_title": chat_title,
            "thread_id": thread_id
        })
        user_data["count"] += 1
        await set_peticiones_por_usuario(user_id, user_data["count"], chat_id, username)
        destino_message = (
            f"📬 *¡Nueva solicitud!* 🚀\n"
            f"👤 *Usuario:* {username_escaped} (ID: {user_id})\n"
            f"🎫 *Ticket:* #{ticket_number}\n"
            f"📊 *Petición:* {user_data['count']}/2\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp_str}\n"
            "✨ *Bot de Entreshijos*"
        )
        await context.bot.edit_message_text(chat_id=GROUP_DESTINO, message_id=sent_message.message_id, text=destino_message, parse_mode='Markdown')
        confirmacion_message = (
            f"🎉 *¡Solicitud en marcha!* 🚀\n"
            f"Hola {username_escaped}, tu pedido (Ticket #{ticket_number}) está en el sistema.\n"
            f"📌 *Detalles:*\n🆔 ID: {user_id}\n🏠 Grupo: {chat_title_escaped}\n📅 Fecha: {timestamp_str}\n"
            f"📝 Mensaje: {message_text_escaped}\n⏳ ¡Pronto estará listo! {random.choice(frases_agradecimiento)}"
        )
        await context.bot.send_message(chat_id=canal_info["chat_id"], text=confirmacion_message, parse_mode='Markdown', message_thread_id=canal_info["thread_id"])

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    admin_username = f"@{update.message.from_user.username}" if update.message.from_user.username else "Admin sin @"
    keyboard = [
        [InlineKeyboardButton("📋 Pendientes", callback_data="menu_pendientes")],
        [InlineKeyboardButton("📜 Historial", callback_data="menu_historial")],
        [InlineKeyboardButton("📊 Gráficas", callback_data="menu_graficas")],
        [InlineKeyboardButton("🏠 Grupos", callback_data="menu_grupos")],
        [InlineKeyboardButton("🟢 Activar", callback_data="menu_on"), InlineKeyboardButton("🔴 Desactivar", callback_data="menu_off")],
        [InlineKeyboardButton("➕ Sumar", callback_data="menu_sumar"), InlineKeyboardButton("➖ Restar", callback_data="menu_restar")],
        [InlineKeyboardButton("🧹 Limpiar", callback_data="menu_clean"), InlineKeyboardButton("🏓 Ping", callback_data="menu_ping")],
        [InlineKeyboardButton("📈 Stats", callback_data="menu_stats"), InlineKeyboardButton("🏆 Top Usuarios", callback_data="menu_topusuarios")],
        [InlineKeyboardButton("📢 Mensaje Global", callback_data="menu_broadcast")],
        [InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=update.message.chat_id, text=f"👤 {admin_username}\n📋 *¡Menú Principal!* ✨\nElige tu misión:", reply_markup=reply_markup, parse_mode='Markdown')

async def handle_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or str(update.message.chat_id) != GROUP_DESTINO:
        return
    await context.bot.send_message(chat_id=update.message.chat_id, text=random.choice(ping_respuestas), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        return

    if data == "menu_pendientes":
        conn = db_pool.getconn()
        try:
            with conn.cursor() as c:
                c.execute("SELECT ticket_number, username, chat_title, prioridad FROM peticiones_registradas ORDER BY prioridad DESC, ticket_number")
                pendientes = c.fetchall()
        finally:
            db_pool.putconn(conn)
        if not pendientes:
            await context.bot.send_message(chat_id=chat_id, text="🌟 ¡No hay nada pendiente! 😎", parse_mode='Markdown')
            await query.message.delete()
            return
        ITEMS_PER_PAGE = 5
        page = 1
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = pendientes[start_idx:end_idx]
        total_pages = (len(pendientes) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        keyboard = [[InlineKeyboardButton(f"{'⭐ ' if prioridad else ''}#{ticket} - {escape_markdown(username, True)} ({escape_markdown(chat_title)})",
                                        callback_data=f"pend_{ticket}")] for ticket, username, chat_title, prioridad in page_items]
        nav_buttons = [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal"), InlineKeyboardButton("❌ Cerrar", callback_data="menu_close")]
        if page > 1:
            nav_buttons.insert(1, InlineKeyboardButton("⬅️ Anterior", callback_data=f"pend_page_{page-1}"))
        if page < total_pages:
            nav_buttons.insert(-1, InlineKeyboardButton("Siguiente ➡️", callback_data=f"pend_page_{page+1}"))
        keyboard.append(nav_buttons)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=chat_id, text=f"📋 *Pendientes (Página {page}/{total_pages})* 🚀\n¡Elige una solicitud!", reply_markup=reply_markup, parse_mode='Markdown')
        await query.message.delete()

# Configuración de la aplicación
application = Application.builder().token(TOKEN).build()

# Añadir manejadores
application.add_handler(MessageHandler(~filters.COMMAND, handle_message))
application.add_handler(CommandHandler('menu', handle_menu))
application.add_handler(CommandHandler('ping', handle_ping))
application.add_handler(CallbackQueryHandler(button_handler))

# Inicialización y ejecución
async def main():
    init_db()
    for chat_id, title in GRUPOS_PREDEFINIDOS.items():
        await set_grupo_estado(chat_id, title)
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook configurado en {WEBHOOK_URL}")
    port = int(os.getenv('PORT', 5000))
    # No usamos asyncio.run aquí, dejamos que run_webhook gestione el bucle
    await application.run_webhook(listen='0.0.0.0', port=port, webhook_url=WEBHOOK_URL)

if __name__ == '__main__':
    # Crear un bucle de eventos explícitamente y ejecutar la coroutine main
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
        loop.run_forever()  # Mantener el bucle corriendo para manejar webhooks
    except KeyboardInterrupt:
        logger.info("Bot detenido manualmente.")
    finally:
        loop.close()
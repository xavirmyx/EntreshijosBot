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
from psycopg2 import OperationalError
import time

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

# Conexión a Supabase con reintentos y forzando IPv4
def get_db_connection():
    max_retries = 3
    retry_delay = 5  # segundos
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                dbname="postgres",
                user="postgres",
                password="-RAPX-U2Y.iUvLq",
                host="34.77.162.2",  # IP fija de db.fwvhrbfoiogtkmgzddhk.supabase.co para forzar IPv4
                port="5432",
                connect_timeout=10  # Timeout de 10 segundos
            )
            return conn
        except OperationalError as e:
            logger.error(f"Intento {attempt + 1}/{max_retries} - Error al conectar a Supabase: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error("No se pudo conectar a Supabase tras varios intentos.")
                return None

# Contador inicial para tickets
ticket_counter = 150
procesado = {}  # Flag para evitar duplicación de mensajes (update_id: True)
admin_ids = set([12345678])  # Lista de IDs de administradores

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

# Funciones para Supabase
def save_peticion_registrada(ticket, chat_id, username, message_text, message_id, timestamp, chat_title):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO peticiones_registradas (ticket, chat_id, username, message_text, message_id, timestamp, chat_title)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticket) DO NOTHING
            """, (ticket, chat_id, username, message_text, message_id, timestamp.strftime('%d/%m/%Y %H:%M:%S'), chat_title))
            conn.commit()
        except Exception as e:
            logger.error(f"Error al guardar petición registrada: {str(e)}")
        finally:
            conn.close()

def save_historial_solicitud(ticket, chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO historial_solicitudes (ticket, chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticket) DO NOTHING
            """, (ticket, chat_id, username, message_text, chat_title, estado, fecha_gestion.strftime('%d/%m/%Y %H:%M:%S'), admin_username))
            conn.commit()
        except Exception as e:
            logger.error(f"Error al guardar historial: {str(e)}")
        finally:
            conn.close()

def update_peticiones_usuario(user_id, count, chat_id, username):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO peticiones_por_usuario (user_id, count, chat_id, username)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET count = %s, chat_id = %s, username = %s
            """, (user_id, count, chat_id, username, count, chat_id, username))
            conn.commit()
        except Exception as e:
            logger.error(f"Error al actualizar peticiones por usuario: {str(e)}")
        finally:
            conn.close()

def save_peticion_incorrecta(user_id, timestamp, chat_id):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO peticiones_incorrectas (user_id, timestamp, chat_id)
                VALUES (%s, %s, %s)
            """, (user_id, timestamp.strftime('%d/%m/%Y %H:%M:%S'), chat_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Error al guardar petición incorrecta: {str(e)}")
        finally:
            conn.close()

def get_peticiones_usuario(user_id):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT count, chat_id, username FROM peticiones_por_usuario WHERE user_id = %s", (user_id,))
            result = c.fetchone()
            return {"count": result[0], "chat_id": result[1], "username": result[2]} if result else None
        except Exception as e:
            logger.error(f"Error al obtener peticiones por usuario: {str(e)}")
            return None
        finally:
            conn.close()
    return None

def get_peticiones_incorrectas(user_id, cutoff_time):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("""
                SELECT timestamp, chat_id FROM peticiones_incorrectas
                WHERE user_id = %s AND timestamp > %s
            """, (user_id, cutoff_time.strftime('%d/%m/%Y %H:%M:%S')))
            results = c.fetchall()
            return [{"timestamp": r[0], "chat_id": r[1]} for r in results]
        except Exception as e:
            logger.error(f"Error al obtener peticiones incorrectas: {str(e)}")
            return []
        finally:
            conn.close()
    return []

def get_peticion_registrada(ticket):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM peticiones_registradas WHERE ticket = %s", (ticket,))
            result = c.fetchone()
            if result:
                return {
                    "chat_id": result[1],
                    "username": result[2],
                    "message_text": result[3],
                    "message_id": result[4],
                    "timestamp": datetime.strptime(result[5], '%d/%m/%Y %H:%M:%S').replace(tzinfo=pytz.UTC),
                    "chat_title": result[6]
                }
            return None
        except Exception as e:
            logger.error(f"Error al obtener petición registrada: {str(e)}")
            return None
        finally:
            conn.close()
    return None

def get_historial_solicitud(ticket):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM historial_solicitudes WHERE ticket = %s", (ticket,))
            result = c.fetchone()
            if result:
                return {
                    "chat_id": result[1],
                    "username": result[2],
                    "message_text": result[3],
                    "chat_title": result[4],
                    "estado": result[5],
                    "fecha_gestion": datetime.strptime(result[6], '%d/%m/%Y %H:%M:%S').replace(tzinfo=pytz.UTC),
                    "admin_username": result[7]
                }
            return None
        except Exception as e:
            logger.error(f"Error al obtener historial solicitud: {str(e)}")
            return None
        finally:
            conn.close()
    return None

def delete_peticion_registrada(ticket):
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("DELETE FROM peticiones_registradas WHERE ticket = %s", (ticket,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error al eliminar petición registrada: {str(e)}")
        finally:
            conn.close()

# Función para manejar mensajes
def handle_message(update, context):
    if not update.message:
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
    canal_info = CANALES_PETICIONES.get(chat_id, {"chat_id": chat_id, "thread_id": None})

    update_grupos_estados(chat_id, chat_title)

    timestamp = datetime.now(pytz.timezone('UTC'))
    timestamp_str = timestamp.strftime('%d/%m/%Y %H:%M:%S')
    username_escaped = escape_markdown(username, preserve_username=True)
    chat_title_escaped = escape_markdown(chat_title)
    message_text_escaped = escape_markdown(message_text)

    if any(cmd in message_text.lower() for cmd in ['#solicito', '/solicito', '#peticion', '/peticion']):
        logger.info(f"Solicitud recibida de {username} en {chat_title}: {message_text}")
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

        user_data = get_peticiones_usuario(user_id)
        if user_data is None:
            update_peticiones_usuario(user_id, 0, chat_id, username)
            user_data = {"count": 0, "chat_id": chat_id, "username": username}
        user_data["count"] += 1
        update_peticiones_usuario(user_id, user_data["count"], chat_id, username)

        if user_data["count"] > 2 and user_id not in admin_ids:
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
            f"📊 *Petición:* {user_data['count']}/2\n"
            f"📝 *Mensaje:* {message_text_escaped}\n"
            f"🏠 *Grupo:* {chat_title_escaped}\n"
            f"🕒 *Fecha:* {timestamp_str}\n"
            "🌟 *Bot de Entreshijos*"
        )
        try:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message, parse_mode='Markdown')
            save_peticion_registrada(ticket_number, chat_id, username, message_text, sent_message.message_id, timestamp, chat_title)
            logger.info(f"Solicitud #{ticket_number} enviada al grupo destino")
        except telegram.error.BadRequest as e:
            sent_message = bot.send_message(chat_id=GROUP_DESTINO, text=destino_message.replace('*', ''))
            save_peticion_registrada(ticket_number, chat_id, username, message_text, sent_message.message_id, timestamp, chat_title)
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

    elif any(word in message_text.lower() for word in ['solicito', 'peticion']) and chat_id in CANALES_PETICIONES:
        save_peticion_incorrecta(user_id, timestamp, chat_id)
        cutoff_time = timestamp - timedelta(hours=24)
        intentos_recientes = get_peticiones_incorrectas(user_id, cutoff_time)

        notificacion_incorrecta = (
            f"⚠️ {username_escaped}, tu petición no está formulada correctamente. "
            "Por favor, usa los comandos correctos: */solicito*, *#solicito*, */peticion* o *#peticion*. "
            "Consulta /ayuda para más detalles. 🌟\n"
            "📋 *Equipo de Administración EnTresHijos*"
        )

        if len(intentos_recientes) > 2:
            notificacion_incorrecta = (
                f"🚨 /warn {username_escaped} Abuso de peticiones incorrectas detectado. "
                "Por favor, usa los comandos correctos: */solicito*, *#solicito*, */peticion* o *#peticion*. "
                "Consulta /ayuda para más información. 🌟\n"
                "📋 *Equipo de Administración EnTresHijos*"
            )

        try:
            bot.send_message(
                chat_id=canal_info["chat_id"],
                text=notificacion_incorrecta,
                parse_mode='Markdown',
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
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
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
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not grupos_activos:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
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
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    if not grupos_estados:
        bot.send_message(chat_id=chat_id, text="ℹ️ No hay grupos registrados aún. 🌟")
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
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM historial_solicitudes ORDER BY ticket DESC")
            results = c.fetchall()
            if not results:
                bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes gestionadas en el historial. 🌟")
                return
            historial = []
            for r in results:
                estado_str = {"subido": "✅ Aceptada", "denegado": "❌ Denegada", "eliminado": "🗑️ Eliminada", "notificado": "📢 Respondida"}.get(r[5], "🔄 Desconocido")
                historial.append(
                    f"🎫 *Ticket #{r[0]}* 🌟\n"
                    f"👤 *Usuario:* {escape_markdown(r[2], True)}\n"
                    f"📝 *Mensaje:* {escape_markdown(r[3])}\n"
                    f"🏠 *Grupo:* {escape_markdown(r[4])}\n"
                    f"📅 *Gestionada:* {r[6]}\n"
                    f"👥 *Admin:* {r[7]}\n"
                    f"📌 *Estado:* {estado_str}\n"
                )
            historial_message = "📜 *Historial de Solicitudes Gestionadas* 🌟\n\n" + "\n".join(historial)
            bot.send_message(chat_id=chat_id, text=historial_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error al obtener historial: {str(e)}")
            bot.send_message(chat_id=chat_id, text="⚠️ Error al cargar el historial. 🌟")
        finally:
            conn.close()

# Comando /pendientes con botones
def handle_pendientes(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT ticket, username, chat_title FROM peticiones_registradas ORDER BY ticket")
            results = c.fetchall()
            if not results:
                bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes. 🌟")
                return
            keyboard = []
            for ticket, username, chat_title in results:
                keyboard.append([InlineKeyboardButton(f"#{ticket} - {username} ({chat_title})",
                                                     callback_data=f"pend_{ticket}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            bot.send_message(chat_id=chat_id,
                             text="📋 *Solicitudes pendientes* 🌟\nSelecciona una solicitud para gestionarla:",
                             reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error al obtener pendientes: {str(e)}")
            bot.send_message(chat_id=chat_id, text="⚠️ Error al cargar pendientes. 🌟")
        finally:
            conn.close()

# Comando /eliminar con botones
def handle_eliminar(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return

    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT ticket, username FROM peticiones_registradas")
            results = c.fetchall()
            if not results:
                bot.send_message(chat_id=chat_id, text="ℹ️ No hay solicitudes pendientes para eliminar. 🌟")
                return
            keyboard = []
            for ticket, username in results:
                keyboard.append([InlineKeyboardButton(f"Ticket #{ticket} - {username}",
                                                     callback_data=f"eliminar_{ticket}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            bot.send_message(chat_id=chat_id,
                             text="🗑️ *Eliminar solicitud* 🌟\nSelecciona el ticket a eliminar:",
                             reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error al obtener solicitudes para eliminar: {str(e)}")
            bot.send_message(chat_id=chat_id, text="⚠️ Error al cargar solicitudes. 🌟")
        finally:
            conn.close()

# Comando /ping
def handle_ping(update, context):
    if not update.message:
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
        return
    query.answer()
    data = query.data
    chat_id = query.message.chat_id
    mensaje_id = query.message.message_id
    current_text = query.message.text
    current_markup = query.message.reply_markup

    if data == "grupos_retroceder":
        handle_grupos(update, context)
        return

    if not data.startswith("select_") and not data.startswith("confirm_") and not data.startswith("notify_") and not data.startswith("back_"):
        pass
    else:
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

    if data.startswith("pend_"):
        admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"
        if data == "pend_regresar":
            conn = get_db_connection()
            if conn:
                try:
                    c = conn.cursor()
                    c.execute("SELECT ticket, username, chat_title FROM peticiones_registradas ORDER BY ticket")
                    results = c.fetchall()
                    keyboard = []
                    for ticket, username, chat_title in results:
                        keyboard.append([InlineKeyboardButton(f"#{ticket} - {username} ({chat_title})",
                                                             callback_data=f"pend_{ticket}")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    texto = "📋 *Solicitudes pendientes* 🌟\nSelecciona una solicitud para gestionarla:"
                    if texto != current_text or str(reply_markup) != str(current_markup):
                        query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"Error al regresar a pendientes: {str(e)}")
                finally:
                    conn.close()
            return

        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar ticket en callback pend_: {data}")
            return

        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

        if len(data.split("_")) == 2:
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
            if texto != current_text or str(reply_markup) != str(current_markup):
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            return

        try:
            accion = data.split("_")[2]
        except IndexError:
            logger.error(f"Error al procesar acción en callback pend_: {data}")
            return

        username_escaped = escape_markdown(info["username"], True)
        message_text_escaped = escape_markdown(info["message_text"])
        user_chat_id = info["chat_id"]
        message_id = info["message_id"]

        save_historial_solicitud(ticket, user_chat_id, info["username"], info["message_text"], info["chat_title"],
                                 accion, datetime.now(pytz.timezone('UTC')), admin_username)

        if accion == "subido":
            notificacion = f"✅ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido subida. 🎉"
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
            texto = f"✅ *Ticket #{ticket} procesado como subido.* 🌟"
            delete_peticion_registrada(ticket)
            query.edit_message_text(text=texto, parse_mode='Markdown')

        elif accion == "denegado":
            notificacion = f"❌ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido denegada. 🌟"
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
            texto = f"✅ *Ticket #{ticket} procesado como denegado.* 🌟"
            delete_peticion_registrada(ticket)
            query.edit_message_text(text=texto, parse_mode='Markdown')

        elif accion == "eliminar":
            try:
                bot.delete_message(chat_id=GROUP_DESTINO, message_id=message_id)
                bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} de {username_escaped} eliminado. 🌟")
            except telegram.error.TelegramError as e:
                bot.send_message(chat_id=chat_id, text=f"⚠️ No se pudo eliminar el mensaje: {str(e)}. Notificando de todos modos. 🌟")
            notificacion = f"ℹ️ {username_escaped}, tu solicitud (Ticket #{ticket}) \"{message_text_escaped}\" ha sido eliminada. 🌟"
            bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
            texto = f"✅ *Ticket #{ticket} procesado como eliminado.* 🌟"
            delete_peticion_registrada(ticket)
            query.edit_message_text(text=texto, parse_mode='Markdown')

        elif accion == "notificar":
            keyboard = [
                [InlineKeyboardButton("🔙 Regresar", callback_data=f"pend_{ticket}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            texto = f"📢 *Notificar Ticket #{ticket}* 🌟\nEscribe el mensaje a enviar a {username_escaped} (responde a este mensaje):"
            if texto != current_text or str(reply_markup) != str(current_markup):
                query.edit_message_text(text=texto, reply_markup=reply_markup, parse_mode='Markdown')
            context.user_data["notificar_ticket"] = ticket
            return

    if data.startswith("eliminar_"):
        admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"
        try:
            ticket = int(data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error al procesar eliminar_ callback: {data}")
            return

        info = get_peticion_registrada(ticket)
        if not info:
            query.edit_message_text(text=f"❌ Ticket #{ticket} no encontrado. 🌟", parse_mode='Markdown')
            return

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

        username_escaped = escape_markdown(username, preserve_username=True)
        message_text_escaped = escape_markdown(message_text)

        save_historial_solicitud(ticket, user_chat_id, username, message_text, info["chat_title"],
                                 "eliminado" if estado == "eliminada" else estado, datetime.now(pytz.timezone('UTC')), admin_username)

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

        bot.send_message(chat_id=user_chat_id, text=notificacion, parse_mode='Markdown')
        texto = f"✅ *Ticket #{ticket} procesado como {estado}.* 🌟"
        delete_peticion_registrada(ticket)
        query.edit_message_text(text=texto, parse_mode='Markdown')

# Comando /subido
def handle_subido(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /subido [ticket] 🌟")
        return
    try:
        ticket = int(args[0])
        info = get_peticion_registrada(ticket)
        if not info:
            bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟")
            return
        save_historial_solicitud(ticket, info["chat_id"], info["username"], info["message_text"],
                                 info["chat_title"], "subido", datetime.now(pytz.timezone('UTC')), admin_username)
        bot.send_message(chat_id=info["chat_id"],
                         text=f"✅ {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido subida. 🎉",
                         parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como subido. 🌟")
        delete_peticion_registrada(ticket)
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

# Comando /denegado
def handle_denegado(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    args = context.args
    if len(args) != 1:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /denegado [ticket] 🌟")
        return
    try:
        ticket = int(args[0])
        info = get_peticion_registrada(ticket)
        if not info:
            bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟")
            return
        save_historial_solicitud(ticket, info["chat_id"], info["username"], info["message_text"],
                                 info["chat_title"], "denegado", datetime.now(pytz.timezone('UTC')), admin_username)
        bot.send_message(chat_id=info["chat_id"],
                         text=f"❌ {escape_markdown(info['username'], True)}, tu solicitud (Ticket #{ticket}) ha sido denegada. 🌟",
                         parse_mode='Markdown')
        bot.send_message(chat_id=chat_id, text=f"✅ Ticket #{ticket} marcado como denegado. 🌟")
        delete_peticion_registrada(ticket)
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

# Comando /notificar (manual)
def handle_notificar(update, context):
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"

    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino (-1002641818457). 🌟")
        return
    args = context.args
    if len(args) < 2:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /notificar [username] [mensaje] 🌟")
        return
    username = args[0]
    msg = " ".join(args[1:])
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("SELECT chat_id FROM peticiones_registradas WHERE username = %s LIMIT 1", (username,))
            result = c.fetchone()
            user_chat_id = result[0] if result else None
            if user_chat_id:
                bot.send_message(chat_id=user_chat_id, text=f"📢 *Notificación* 🌟\n{msg}", parse_mode='Markdown')
                bot.send_message(chat_id=chat_id, text=f"✅ Enviada notificación a {username}. 🌟")
            else:
                bot.send_message(chat_id=chat_id, text=f"❌ {username} no encontrado. 🌟")
        except Exception as e:
            logger.error(f"Error al notificar: {str(e)}")
            bot.send_message(chat_id=chat_id, text="⚠️ Error al enviar notificación. 🌟")
        finally:
            conn.close()

# Manejo de respuestas para notificaciones desde /pendientes
def handle_notificar_respuesta(update, context):
    if not update.message or "notificar_ticket" not in context.user_data:
        return

    message = update.message
    chat_id = message.chat_id
    admin_username = f"@{update.effective_user.username}" if update.effective_user.username else "Admin sin @"

    if str(chat_id) != GROUP_DESTINO:
        return

    ticket = context.user_data["notificar_ticket"]
    info = get_peticion_registrada(ticket)
    if not info:
        bot.send_message(chat_id=chat_id, text=f"❌ Ticket #{ticket} no encontrado. 🌟")
        del context.user_data["notificar_ticket"]
        return

    username_escaped = escape_markdown(info["username"], True)
    mensaje = message.text

    save_historial_solicitud(ticket, info["chat_id"], info["username"], info["message_text"],
                             info["chat_title"], "notificado", datetime.now(pytz.timezone('UTC')), admin_username)

    bot.send_message(chat_id=info["chat_id"],
                     text=f"📢 *Notificación* 🌟\n{mensaje}",
                     parse_mode='Markdown')
    bot.send_message(chat_id=chat_id,
                     text=f"✅ Enviada notificación a {username_escaped} para Ticket #{ticket}. 🌟")
    del context.user_data["notificar_ticket"]

# Comando /menu
def handle_menu(update, context):
    if not update.message:
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
    if not update.message:
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
        info = get_peticion_registrada(ticket)
        if info:
            estado_message = (
                f"📋 *Estado* 🌟\n"
                f"Ticket #{ticket}: {escape_markdown(info['message_text'])}\n"
                f"Estado: Pendiente ⏳\n"
                f"🕒 Enviada: {info['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}"
            )
        else:
            hist_info = get_historial_solicitud(ticket)
            if hist_info:
                estado_str = {"subido": "✅ Aceptada", "denegado": "❌ Denegada", "eliminado": "🗑️ Eliminada", "notificado": "📢 Respondida"}.get(hist_info["estado"], "🔄 Desconocido")
                estado_message = (
                    f"📋 *Estado* 🌟\n"
                    f"Ticket #{ticket}: {escape_markdown(hist_info['message_text'])}\n"
                    f"Estado: {estado_str}\n"
                    f"🕒 Gestionada: {hist_info['fecha_gestion'].strftime('%d/%m/%Y %H:%M:%S')}\n"
                    f"👥 Admin: {hist_info['admin_username']}"
                )
            else:
                estado_message = f"📋 *Estado* 🌟\nTicket #{ticket}: No encontrado. 🔍"
        bot.send_message(chat_id=chat_id, text=estado_message, parse_mode='Markdown')
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número. 🌟")

# Añadir handlers
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
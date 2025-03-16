from telegram.ext import CommandHandler
import telegram  # Importamos el módulo telegram para manejar excepciones
import logging
import random
from datetime import datetime
import pytz
from config import bot, admin_ids, GROUP_DESTINO, grupos_activos, procesado, peticiones_registradas, peticiones_por_usuario

logger = logging.getLogger(__name__)

# Lista de frases de agradecimiento para /random (15 frases originales)
frases_random = [
    "¡Tu apoyo nos hace brillar! ✨",
    "¡Gracias por ser parte de esto! 🌈",
    "¡Eres un tesoro para nosotros! 💎",
    "¡Tu paciencia es oro puro! 🏅",
    "¡Agradecemos cada segundo contigo! ⏳",
    "¡Eres la chispa que nos motiva! 🔥",
    "¡Gracias por confiar en el equipo! 🤝",
    "¡Tu presencia alegra el día! ☀️",
    "¡Un aplauso para ti por estar aquí! 👏",
    "¡Gracias por hacer esto especial! 🎈",
    "¡Tu entusiasmo nos impulsa! 🚀",
    "¡Apreciamos cada solicitud tuya! 📬",
    "¡Eres el corazón de Entreshijos! ❤️",
    "¡Gracias por tu increíble vibra! 🌟",
    "¡Tu espera vale la pena, lo prometemos! 🙌"
]

# Lista de chistes para /joke (20 chistes originales y divertidos)
chistes = [
    "¿Qué hace un perro con un coche? ¡Lo convierte en un *perro-movil*! 🐶🚗",
    "¿Por qué el limón estaba triste? ¡Porque lo exprimieron demasiado! 🍋",
    "¿Qué le dijo la impresora al papel? ¡Esa hoja es mi tipo! 🖨️📄",
    "¿Por qué el café fue a terapia? ¡Tenía demasiada presión! ☕",
    "¿Qué hace un gato en un examen? ¡Copia con las *patas*! 🐱📝",
    "¿Por qué la naranja se enfadó? ¡Porque la pelaron sin permiso! 🍊",
    "¿Qué dijo el Wi-Fi al router? ¡No me dejes desconectado! 📶",
    "¿Por qué el pollo cruzó el grupo? ¡Para pedir una solicitud! 🐔",
    "¿Qué le dijo el reloj al calendario? ¡Nos vemos en la próxima hora! ⏰📅",
    "¿Por qué el tomate se sonrojó? ¡Lo pillaron en salsa! 🍅",
    "¿Qué hace un pájaro en Telegram? ¡Envía *tweets*! 🐦",
    "¿Por qué el lápiz no hablaba? ¡Porque estaba afilado de nervios! ✏️",
    "¿Qué le dijo la luna al sol? ¡Tú brillas, pero yo inspiro! 🌙☀️",
    "¿Por qué la zanahoria fue al gimnasio? ¡Quería estar más *crujiente*! 🥕",
    "¿Qué hace un fantasma en el chat? ¡Envía mensajes *boo-rrosos*! 👻",
    "¿Por qué el helado se derritió? ¡Porque no soportó la presión! 🍦",
    "¿Qué le dijo el pan al queso? ¡Fúndete conmigo! 🥖🧀",
    "¿Por qué el semáforo estaba rojo? ¡Se avergonzó del tráfico! 🚦",
    "¿Qué hace un elefante en un grupo? ¡Trompea las normas! 🐘",
    "¿Por qué el huevo se rompió? ¡Porque no aguantó las yemas! 🥚"
]

# Comando /mensaje - Mensaje Masivo (Solo Administradores)
def handle_mensaje(update, context):
    if not update.message:
        logger.warning("Mensaje /mensaje recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    args = context.args

    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Este comando es solo para administradores. 🌟")
        return
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /mensaje fuera del grupo destino: {chat_id}")
        return
    if not args:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /mensaje [texto]. Ejemplo: /mensaje Hola a todos 🌟")
        return

    mensaje = " ".join(args)
    for grupo in grupos_activos:
        try:
            bot.send_message(chat_id=grupo, text=f"📢 *Anuncio del Equipo* 🌟\n{mensaje}")
            logger.info(f"Mensaje masivo enviado a {grupo}")
        except telegram.error.TelegramError as e:
            logger.error(f"Error al enviar mensaje masivo a {grupo}: {str(e)}")
    bot.send_message(chat_id=chat_id, text="✅ Mensaje enviado a todos los grupos activos. 🌟")
    logger.info(f"Mensaje masivo enviado por {user_id}")

# Comando /clear - Limpiar Procesados (Solo Administradores)
def handle_clear(update, context):
    if not update.message:
        logger.warning("Mensaje /clear recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Este comando es solo para administradores. 🌟")
        return
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /clear fuera del grupo destino: {chat_id}")
        return

    procesado.clear()
    bot.send_message(chat_id=chat_id, text="✅ Diccionario de mensajes procesados limpiado. 🌟")
    logger.info(f"Diccionario procesado limpiado por {user_id}")

# Comando /stats - Estadísticas Básicas (Solo Administradores)
def handle_stats(update, context):
    if not update.message:
        logger.warning("Mensaje /stats recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Este comando es solo para administradores. 🌟")
        return
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /stats fuera del grupo destino: {chat_id}")
        return

    stats_message = (
        "📊 *Estadísticas Básicas del Bot* 🌟\n"
        f"🔹 Grupos activos: {len(grupos_activos)}\n"
        f"🔹 Solicitudes pendientes: {len(peticiones_registradas)}\n"
        f"🔹 Mensajes procesados: {len(procesado)}\n"
        "🌟 Bot de Entreshijos"
    )
    try:
        bot.send_message(chat_id=chat_id, text=stats_message, parse_mode='Markdown')
        logger.info(f"Estadísticas enviadas a {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=stats_message.replace('*', '').replace('**', ''))
        logger.error(f"Error al enviar estadísticas: {str(e)}")

# Comando /ping - Verificar Estado del Bot (Solo Administradores)
def handle_ping(update, context):
    if not update.message:
        logger.warning("Mensaje /ping recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Este comando es solo para administradores. 🌟")
        return
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /ping fuera del grupo destino: {chat_id}")
        return

    ping_message = "🏓 *¡Pong!* 🌟\nEl bot está activo y funcionando correctamente."
    try:
        bot.send_message(chat_id=chat_id, text=ping_message, parse_mode='Markdown')
        logger.info(f"Ping respondido a {user_id} en {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=ping_message.replace('*', '').replace('**', ''))
        logger.error(f"Error al responder ping: {str(e)}")

# Comando /random - Frase Aleatoria de Agradecimiento
def handle_random(update, context):
    if not update.message:
        logger.warning("Mensaje /random recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario"

    random_message = random.choice(frases_random)
    try:
        bot.send_message(chat_id=chat_id, text=f"🎉 *Frase Aleatoria* 🌟\n{random_message}\n¡Gracias por estar aquí, {username}! 🙌", parse_mode='Markdown')
        logger.info(f"Frase aleatoria enviada a {username} en {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"Frase Aleatoria: {random_message}\n¡Gracias por estar aquí, {username}!")
        logger.error(f"Error al enviar frase aleatoria: {str(e)}")

# Comando /groups - Listar Grupos Activos (Solo Administradores)
def handle_groups(update, context):
    if not update.message:
        logger.warning("Mensaje /groups recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Este comando es solo para administradores. 🌟")
        return
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /groups fuera del grupo destino: {chat_id}")
        return

    groups_message = (
        "🏠 *Lista de Grupos Activos* 🌟\n"
        "El bot está activo en los siguientes grupos (IDs):\n"
    )
    for group_id in grupos_activos:
        groups_message += f"🔹 ID: {group_id}\n"
    groups_message += f"Total: {len(grupos_activos)} grupos activos."

    try:
        bot.send_message(chat_id=chat_id, text=groups_message, parse_mode='Markdown')
        logger.info(f"Lista de grupos activos enviada a {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=groups_message.replace('*', '').replace('**', ''))
        logger.error(f"Error al enviar lista de grupos: {str(e)}")

# Comando /joke - Chiste Aleatorio
def handle_joke(update, context):
    if not update.message:
        logger.warning("Mensaje /joke recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario"

    joke = random.choice(chistes)
    joke_message = (
        "😂 *¡Un chiste para ti!* 🌟\n"
        f"{joke}\n"
        f"¡Ríe un poco, {username}! 🙌"
    )
    try:
        bot.send_message(chat_id=chat_id, text=joke_message, parse_mode='Markdown')
        logger.info(f"Chiste enviado a {username} en {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"¡Un chiste para ti! {joke}\n¡Ríe un poco, {username}!")
        logger.error(f"Error al enviar chiste: {str(e)}")

# Comando /count - Contar Usuarios Activos (Solo Administradores)
def handle_count(update, context):
    if not update.message:
        logger.warning("Mensaje /count recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    if user_id not in admin_ids:
        bot.send_message(chat_id=chat_id, text="❌ Este comando es solo para administradores. 🌟")
        return
    if str(chat_id) != GROUP_DESTINO:
        bot.send_message(chat_id=chat_id, text="❌ Este comando solo puede usarse en el grupo destino. 🌟")
        logger.info(f"Intento de /count fuera del grupo destino: {chat_id}")
        return

    user_count = len(peticiones_por_usuario)
    count_message = (
        "👥 *Conteo de Usuarios Activos* 🌟\n"
        f"Usuarios únicos que han enviado solicitudes: {user_count}\n"
        "🌟 Bot de Entreshijos"
    )
    try:
        bot.send_message(chat_id=chat_id, text=count_message, parse_mode='Markdown')
        logger.info(f"Conteo de usuarios enviado a {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=count_message.replace('*', '').replace('**', ''))
        logger.error(f"Error al enviar conteo de usuarios: {str(e)}")

# Comando /cancel - Cancelar una Solicitud (Usuarios)
def handle_cancel(update, context):
    if not update.message:
        logger.warning("Mensaje /cancel recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"
    args = context.args

    if not args:
        bot.send_message(chat_id=chat_id, text="❗ Uso: /cancel [ticket]. Ejemplo: /cancel 150 🌟")
        return
    try:
        ticket_number = int(args[0])
    except ValueError:
        bot.send_message(chat_id=chat_id, text="❗ Ticket debe ser un número válido. Ejemplo: /cancel 150 🌟")
        return
    if ticket_number not in peticiones_registradas or peticiones_registradas[ticket_number]["username"] != username:
        bot.send_message(chat_id=chat_id, text=f"❌ No tienes una solicitud con ticket #{ticket_number}. 🌟")
        return

    request_info = peticiones_registradas[ticket_number]
    cancel_message = (
        "🗑️ *Solicitud Cancelada* 🌟\n"
        f"Ticket #{ticket_number} cancelado por {username}.\n"
        f"Mensaje original: {request_info['message_text']}\n"
        "🌟 Bot de Entreshijos"
    )
    try:
        bot.send_message(chat_id=GROUP_DESTINO, text=cancel_message, parse_mode='Markdown')
        del peticiones_registradas[ticket_number]
        bot.send_message(chat_id=chat_id, text=f"✅ Solicitud #{ticket_number} cancelada con éxito. 🌟")
        logger.info(f"Solicitud #{ticket_number} cancelada por {username}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=f"⚠️ Error al cancelar solicitud #{ticket_number}: {str(e)}. 🌟")
        logger.error(f"Error al cancelar solicitud #{ticket_number}: {str(e)}")

# Comando /check - Verificar Límite Diario (Usuarios)
def handle_check(update, context):
    if not update.message:
        logger.warning("Mensaje /check recibido es None")
        return
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Usuario sin @"

    if user_id in admin_ids:
        check_message = (
            "📊 *Tu Límite Diario* 🌟\n"
            f"Hola {username}, como administrador no tienes límite de solicitudes. ¡Sigue ayudando! 🙌"
        )
    else:
        count = peticiones_por_usuario.get(user_id, {}).get("count", 0)
        remaining = max(0, 2 - count)
        check_message = (
            "📊 *Tu Límite Diario* 🌟\n"
            f"Solicitudes enviadas hoy: {count}/2\n"
            f"Solicitudes restantes: {remaining}\n"
            f"¡Planifica tus solicitudes, {username}! 🙌"
        )
    try:
        bot.send_message(chat_id=chat_id, text=check_message, parse_mode='Markdown')
        logger.info(f"Límite diario enviado a {username} en {chat_id}")
    except telegram.error.TelegramError as e:
        bot.send_message(chat_id=chat_id, text=check_message.replace('*', '').replace('**', ''))
        logger.error(f"Error al enviar límite diario: {str(e)}")

# Añadir manejadores
def add_extra_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler('mensaje', handle_mensaje))
    dispatcher.add_handler(CommandHandler('clear', handle_clear))
    dispatcher.add_handler(CommandHandler('stats', handle_stats))
    dispatcher.add_handler(CommandHandler('ping', handle_ping))
    dispatcher.add_handler(CommandHandler('random', handle_random))
    dispatcher.add_handler(CommandHandler('groups', handle_groups))
    dispatcher.add_handler(CommandHandler('joke', handle_joke))
    dispatcher.add_handler(CommandHandler('count', handle_count))
    dispatcher.add_handler(CommandHandler('cancel', handle_cancel))
    dispatcher.add_handler(CommandHandler('check', handle_check))
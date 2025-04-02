# utils.py
import pytz
from datetime import datetime, timedelta
import random
import threading
import time
import logging
from database import clean_database, get_advanced_stats
from config import GROUP_DESTINO
from telegram import Bot

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración de zona horaria
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Variables globales
grupos_seleccionados = {}
menu_activos = {}

def escape_markdown(text, preserve_username=False):
    if not text:
        return text
    if preserve_username and text.startswith('@'):
        return ''.join(['\\' + c if c in '_*[]()~`>#+-=|{}.!' else c for c in text])
    characters_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in characters_to_escape:
        text = text.replace(char, f'\\{char}')
    return text

def update_grupos_estados(chat_id, chat_type, title, set_grupo_estado, get_grupos_estados, GROUP_DESTINO):
    # No registrar chats privados ni el grupo de administración
    if chat_type == "private" or str(chat_id) == GROUP_DESTINO:
        return
    grupos = get_grupos_estados()
    if chat_id not in grupos:
        set_grupo_estado(chat_id, title if title else f"Grupo {chat_id}")
    elif title and grupos[chat_id]["title"] == f"Grupo {chat_id}":
        set_grupo_estado(chat_id, title)
    logger.info(f"Grupo registrado/actualizado: {chat_id} - {title or grupos.get(chat_id, {}).get('title')}")

def get_spain_time():
    return datetime.now(SPAIN_TZ).strftime('%d/%m/%Y %H:%M:%S')

# Limpieza automática
def auto_clean_database():
    while True:
        try:
            clean_database()
        except Exception as e:
            logger.error(f"Error en limpieza automática: {str(e)}")
        time.sleep(86400)  # Cada 24 horas

def clean_globals():
    while True:
        now = datetime.now(SPAIN_TZ)
        for key in list(menu_activos.keys()):
            if (now - menu_activos[key]).total_seconds() > 3600:
                del menu_activos[key]
        for chat_id in list(grupos_seleccionados.keys()):
            if grupos_seleccionados[chat_id].get("estado") == "seleccion" and \
               (now - menu_activos.get((chat_id, grupos_seleccionados[chat_id]["mensaje_id"]), now)).total_seconds() > 3600:
                del grupos_seleccionados[chat_id]
        time.sleep(3600)

# Recordatorio diario
def daily_reminder(bot):
    while True:
        try:
            stats = get_advanced_stats()
            if stats["pendientes"] > 0:
                bot.send_message(chat_id=GROUP_DESTINO,
                                 text=f"⏰ *Recordatorio diario* 🌟\nHay {stats['pendientes']} solicitudes pendientes.",
                                 parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error en recordatorio diario: {str(e)}")
        time.sleep(86400)
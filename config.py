import telegram
import os

# Configura tu token, grupo y URL del webhook usando variables de entorno
TOKEN = os.getenv('TOKEN', '7629869990:AAGxdlWLX6n7i844QgxNFhTygSCo4S8ZqkY')
GROUP_DESTINO = os.getenv('GROUP_DESTINO', '-1002641818457')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://entreshijosbot.onrender.com/webhook')

# Inicializa el bot
bot = telegram.Bot(token=TOKEN)

# Diccionarios para almacenamiento en memoria
ticket_counter = 150  # Comienza en 150
peticiones_por_usuario = {}  # {user_id: {"count": X, "chat_id": Y, "username": Z}}
peticiones_registradas = {}  # {ticket_number: {"chat_id": X, "username": Y, "message_text": Z, "message_id": W, "timestamp": T}}
procesado = {}  # Flag para evitar duplicación de mensajes (update_id: True)
admin_ids = set([12345678])  # Lista de IDs de administradores
aceptar_solicitudes = True  # Controla si se aceptan solicitudes
grupos_activos = set()  # Almacena los chat_ids de los grupos donde está el bot
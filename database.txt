# database.py
import logging
import psycopg2
from psycopg2.extras import DictCursor
from psycopg2.pool import SimpleConnectionPool
from datetime import datetime, timedelta
import pytz
from config import DATABASE_URL

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración de zona horaria
SPAIN_TZ = pytz.timezone('Europe/Madrid')

# Pool de conexiones a la base de datos
db_pool = SimpleConnectionPool(1, 5, dsn=DATABASE_URL, cursor_factory=DictCursor)

# Funciones de conexión a la base de datos con reintentos
def get_db_connection(retries=3, delay=1):
    for attempt in range(retries):
        try:
            return db_pool.getconn()
        except psycopg2.Error as e:
            logger.error(f"Intento {attempt + 1} fallido al obtener conexión: {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

def release_db_connection(conn):
    try:
        db_pool.putconn(conn)
    except psycopg2.Error as e:
        logger.error(f"Error al liberar conexión: {str(e)}")

# Inicialización de la base de datos
def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS peticiones_por_usuario 
                         (user_id BIGINT PRIMARY KEY, count INTEGER, chat_id BIGINT, username TEXT, last_reset TIMESTAMP WITH TIME ZONE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS peticiones_registradas 
                         (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                          message_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_title TEXT, thread_id BIGINT, priority INTEGER DEFAULT 0)''')
            c.execute('''CREATE TABLE IF NOT EXISTS historial_solicitudes 
                         (ticket_number BIGINT PRIMARY KEY, chat_id BIGINT, username TEXT, message_text TEXT, 
                          chat_title TEXT, estado TEXT, fecha_gestion TIMESTAMP WITH TIME ZONE, admin_username TEXT, url TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS grupos_estados 
                         (chat_id BIGINT PRIMARY KEY, title TEXT, activo BOOLEAN DEFAULT TRUE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS peticiones_incorrectas 
                         (id SERIAL PRIMARY KEY, user_id BIGINT, timestamp TIMESTAMP WITH TIME ZONE, chat_id BIGINT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                         (user_id BIGINT PRIMARY KEY, username TEXT)''')
            conn.commit()
            logger.info("Base de datos inicializada correctamente.")
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {str(e)}")
        raise
    finally:
        release_db_connection(conn)

# Funciones de utilidad para la base de datos
def get_ticket_counter():
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT GREATEST(COALESCE(MAX(ticket_number), 0)) FROM ("
                      "SELECT ticket_number FROM peticiones_registradas "
                      "UNION SELECT ticket_number FROM historial_solicitudes) AS combined")
            return c.fetchone()[0]
    finally:
        release_db_connection(conn)

def increment_ticket_counter():
    return get_ticket_counter() + 1

def get_peticiones_por_usuario(user_id):
    conn = get_db_connection()
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
                    set_peticiones_por_usuario(user_id, 0, result_dict['chat_id'], result_dict['username'], now)
                return result_dict
            return None
    finally:
        release_db_connection(conn)

def set_peticiones_por_usuario(user_id, count, chat_id, username, last_reset=None):
    if last_reset is None:
        last_reset = datetime.now(SPAIN_TZ)
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO peticiones_por_usuario (user_id, count, chat_id, username, last_reset) 
                         VALUES (%s, %s, %s, %s, %s)
                         ON CONFLICT (user_id) DO UPDATE SET 
                         count = EXCLUDED.count, chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, last_reset = EXCLUDED.last_reset""",
                      (user_id, count, chat_id, username, last_reset))
            c.execute("""INSERT INTO usuarios (user_id, username) 
                         VALUES (%s, %s) 
                         ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
                      (user_id, username))
            conn.commit()
    finally:
        release_db_connection(conn)

def get_user_id_by_username(username):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT user_id FROM usuarios WHERE username = %s", (username,))
            result = c.fetchone()
            return result[0] if result else None
    finally:
        release_db_connection(conn)

def get_peticion_registrada(ticket_number):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT chat_id, username, message_text, message_id, timestamp, chat_title, thread_id, priority "
                      "FROM peticiones_registradas WHERE ticket_number = %s", (ticket_number,))
            result = c.fetchone()
            return dict(result) if result else None
    finally:
        release_db_connection(conn)

def set_peticion_registrada(ticket_number, data):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO peticiones_registradas 
                         (ticket_number, chat_id, username, message_text, message_id, timestamp, chat_title, thread_id, priority) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (ticket_number) DO UPDATE SET 
                         chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, message_text = EXCLUDED.message_text, 
                         message_id = EXCLUDED.message_id, timestamp = EXCLUDED.timestamp, chat_title = EXCLUDED.chat_title, 
                         thread_id = EXCLUDED.thread_id, priority = EXCLUDED.priority""",
                      (ticket_number, data["chat_id"], data["username"], data["message_text"],
                       data["message_id"], data["timestamp"], data["chat_title"], data["thread_id"], data.get("priority", 0)))
            conn.commit()
    finally:
        release_db_connection(conn)

def del_peticion_registrada(ticket_number):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM peticiones_registradas WHERE ticket_number = %s", (ticket_number,))
            conn.commit()
    finally:
        release_db_connection(conn)

def get_historial_solicitud(ticket_number):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username, url "
                      "FROM historial_solicitudes WHERE ticket_number = %s", (ticket_number,))
            result = c.fetchone()
            return dict(result) if result else None
    finally:
        release_db_connection(conn)

def set_historial_solicitud(ticket_number, data):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO historial_solicitudes 
                         (ticket_number, chat_id, username, message_text, chat_title, estado, fecha_gestion, admin_username, url) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (ticket_number) DO UPDATE SET 
                         chat_id = EXCLUDED.chat_id, username = EXCLUDED.username, message_text = EXCLUDED.message_text, 
                         chat_title = EXCLUDED.chat_title, estado = EXCLUDED.estado, fecha_gestion = EXCLUDED.fecha_gestion, 
                         admin_username = EXCLUDED.admin_username, url = EXCLUDED.url""",
                      (ticket_number, data["chat_id"], data["username"], data["message_text"],
                       data["chat_title"], data["estado"], data["fecha_gestion"], data["admin_username"], data.get("url")))
            conn.commit()
    finally:
        release_db_connection(conn)

def get_grupos_estados():
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT chat_id, title, activo FROM grupos_estados")
            return {row['chat_id']: {'title': row['title'], 'activo': row['activo']} for row in c.fetchall()}
    finally:
        release_db_connection(conn)

def set_grupo_estado(chat_id, title, activo=True):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO grupos_estados (chat_id, title, activo) 
                         VALUES (%s, %s, %s) 
                         ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, activo = EXCLUDED.activo""",
                      (chat_id, title, activo))
            conn.commit()
    finally:
        release_db_connection(conn)

def remove_grupo_estado(chat_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM grupos_estados WHERE chat_id = %s", (chat_id,))
            conn.commit()
    finally:
        release_db_connection(conn)

def get_peticiones_incorrectas(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT timestamp, chat_id FROM peticiones_incorrectas WHERE user_id = %s", (user_id,))
            return [dict(row) for row in c.fetchall()]
    finally:
        release_db_connection(conn)

def add_peticion_incorrecta(user_id, timestamp, chat_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO peticiones_incorrectas (user_id, timestamp, chat_id) VALUES (%s, %s, %s)",
                      (user_id, timestamp, chat_id))
            conn.commit()
    finally:
        release_db_connection(conn)

def clean_database():
    conn = get_db_connection()
    stats = {"peticiones_registradas_eliminadas": 0, "peticiones_incorrectas_eliminadas": 0}
    try:
        with conn.cursor() as c:
            # Contar y eliminar peticiones registradas marcadas como eliminadas
            c.execute("SELECT COUNT(*) FROM peticiones_registradas WHERE ticket_number IN (SELECT ticket_number FROM historial_solicitudes WHERE estado = 'eliminado')")
            stats["peticiones_registradas_eliminadas"] = c.fetchone()[0]
            c.execute("DELETE FROM peticiones_registradas WHERE ticket_number IN (SELECT ticket_number FROM historial_solicitudes WHERE estado = 'eliminado')")

            # Contar y eliminar peticiones incorrectas antiguas
            c.execute("SELECT COUNT(*) FROM peticiones_incorrectas WHERE timestamp < %s", (datetime.now(SPAIN_TZ) - timedelta(days=30),))
            stats["peticiones_incorrectas_eliminadas"] = c.fetchone()[0]
            c.execute("DELETE FROM peticiones_incorrectas WHERE timestamp < %s", (datetime.now(SPAIN_TZ) - timedelta(days=30),))

            conn.commit()
        logger.info("Base de datos limpiada de registros obsoletos.")
        return stats
    except psycopg2.Error as e:
        logger.error(f"Error al limpiar la base de datos: {str(e)}")
        raise
    finally:
        release_db_connection(conn)

def get_advanced_stats():
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM peticiones_registradas")
            pendientes = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM historial_solicitudes")
            gestionadas = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM usuarios")
            usuarios = c.fetchone()[0]
            # Estadísticas para gráficas
            c.execute("SELECT estado, COUNT(*) as count FROM historial_solicitudes GROUP BY estado")
            estado_counts = dict(c.fetchall())
            return {
                "pendientes": pendientes,
                "gestionadas": gestionadas,
                "usuarios": usuarios,
                "estado_counts": estado_counts
            }
    except psycopg2.Error as e:
        logger.error(f"Error al obtener estadísticas avanzadas: {str(e)}")
        raise
    finally:
        release_db_connection(conn)

def update_priority(ticket_number, priority):
    conn = get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("UPDATE peticiones_registradas SET priority = %s WHERE ticket_number = %s", (priority, ticket_number))
            conn.commit()
    finally:
        release_db_connection(conn)
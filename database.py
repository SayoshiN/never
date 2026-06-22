import psycopg2
import psycopg2.extras
from contextlib import contextmanager

import config

# ─── Подключение к Supabase ─────────────────────────────

def get_conn():
    """Подключение к PostgreSQL (Supabase)"""
    config.validate_config()
    return psycopg2.connect(config.SUPABASE_URI)

@contextmanager
def get_db():
    conn = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

# ─── Создание таблиц (выполнить один раз) ─────────────

def init_db():
    with get_db() as cur:
        # Пользователи
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_bot BOOLEAN DEFAULT FALSE,
                first_seen TIMESTAMP DEFAULT NOW(),
                last_seen TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Чаты
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id BIGINT PRIMARY KEY,
                chat_type TEXT NOT NULL,
                chat_title TEXT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                added_at TIMESTAMP DEFAULT NOW(),
                last_activity TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Сообщения
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                message_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                text TEXT,
                content_type TEXT DEFAULT 'text',
                reply_to_message_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(chat_id, message_id)
            )
        """)
        
        # Репутация
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reputation (
                rep_id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                rep_score INTEGER DEFAULT 0,
                rep_received INTEGER DEFAULT 0,
                rep_given INTEGER DEFAULT 0,
                rep_dis_received INTEGER DEFAULT 0,
                rep_dis_given INTEGER DEFAULT 0,
                UNIQUE(chat_id, user_id)
            )
        """)
        
        # История репутации (КТО КОМУ дал — для проверки "только 1 раз")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rep_votes (
                vote_id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                from_user_id BIGINT NOT NULL,
                to_user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL CHECK(amount IN (-1, 1)),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(chat_id, from_user_id, to_user_id)
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_created
            ON messages(chat_id, created_at DESC)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reputation_chat_score
            ON reputation(chat_id, rep_score DESC)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rep_votes_chat_from_to
            ON rep_votes(chat_id, from_user_id, to_user_id)
        """)
        
        print("✅ Таблицы созданы в Supabase!")

# ─── CRUD функции ───────────────────────────────────────

def save_user(user_id, username=None, first_name=None, last_name=None, language_code=None, is_bot=False):
    with get_db() as cur:
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language_code, is_bot, last_seen)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                language_code = EXCLUDED.language_code,
                is_bot = EXCLUDED.is_bot,
                last_seen = NOW()
        """, (user_id, username, first_name, last_name, language_code, is_bot))

def save_chat(chat_id, chat_type, chat_title=None, username=None, first_name=None, last_name=None):
    with get_db() as cur:
        cur.execute("""
            INSERT INTO chats (chat_id, chat_type, chat_title, username, first_name, last_name, last_activity)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (chat_id) DO UPDATE SET
                chat_type = EXCLUDED.chat_type,
                chat_title = EXCLUDED.chat_title,
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                last_activity = NOW(),
                is_active = TRUE
        """, (chat_id, chat_type, chat_title, username, first_name, last_name))

def save_message(chat_id, message_id, user_id=None, text=None, content_type='text', reply_to=None):
    with get_db() as cur:
        cur.execute("""
            INSERT INTO messages (message_id, chat_id, user_id, text, content_type, reply_to_message_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id, message_id) DO NOTHING
        """, (message_id, chat_id, user_id, text, content_type, reply_to))

def get_chat_messages(chat_id, limit=50):
    with get_db() as cur:
        cur.execute("""
            SELECT m.*, u.username, u.first_name
            FROM messages m
            LEFT JOIN users u ON m.user_id = u.user_id
            WHERE m.chat_id = %s
            ORDER BY m.created_at DESC
            LIMIT %s
        """, (chat_id, limit))
        return cur.fetchall()

# ─── РЕПУТАЦИЯ (только 1 голос на пользователя) ───────

def has_voted(chat_id, from_user_id, to_user_id):
    """Проверяет, давал ли from_user уже голос to_user"""
    with get_db() as cur:
        cur.execute("""
            SELECT amount FROM rep_votes
            WHERE chat_id = %s AND from_user_id = %s AND to_user_id = %s
        """, (chat_id, from_user_id, to_user_id))
        row = cur.fetchone()
        return row['amount'] if row else None

def give_rep(chat_id, from_user_id, to_user_id, amount=1):
    """Выдаёт репутацию (только если ещё не голосовал)"""
    if amount not in (-1, 1):
        return False, "Некорректное значение репутации."

    with get_db() as cur:
        cur.execute("""
            INSERT INTO rep_votes (chat_id, from_user_id, to_user_id, amount)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chat_id, from_user_id, to_user_id) DO NOTHING
            RETURNING vote_id
        """, (chat_id, from_user_id, to_user_id, amount))
        if not cur.fetchone():
            return False, "Вы уже голосовали за этого пользователя!"
        
        # Обновляем репутацию получателя
        if amount > 0:
            cur.execute("""
                INSERT INTO reputation (chat_id, user_id, rep_score, rep_received)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET
                    rep_score = reputation.rep_score + %s,
                    rep_received = reputation.rep_received + %s
            """, (chat_id, to_user_id, amount, amount, amount, amount))
            
            # Обновляем отправителя
            cur.execute("""
                INSERT INTO reputation (chat_id, user_id, rep_given)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET
                    rep_given = reputation.rep_given + %s
            """, (chat_id, from_user_id, amount, amount))
        else:
            cur.execute("""
                INSERT INTO reputation (chat_id, user_id, rep_score, rep_dis_received)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET
                    rep_score = reputation.rep_score + %s,
                    rep_dis_received = reputation.rep_dis_received + %s
            """, (chat_id, to_user_id, amount, abs(amount), amount, abs(amount)))
            
            cur.execute("""
                INSERT INTO reputation (chat_id, user_id, rep_dis_given)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET
                    rep_dis_given = reputation.rep_dis_given + %s
            """, (chat_id, from_user_id, abs(amount), abs(amount)))
        
        return True, "OK"

def get_user_rep(chat_id, user_id):
    with get_db() as cur:
        cur.execute("""
            SELECT r.*, u.username, u.first_name, u.last_name
            FROM reputation r
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.chat_id = %s AND r.user_id = %s
        """, (chat_id, user_id))
        row = cur.fetchone()
        
        if not row:
            return {'rep_score': 0, 'rep_received': 0, 'rep_given': 0, 
                   'rep_dis_received': 0, 'rep_dis_given': 0, 'username': None, 'first_name': None}
        return dict(row)

def get_top_rep(chat_id, limit=10):
    with get_db() as cur:
        cur.execute("""
            SELECT r.*, u.username, u.first_name
            FROM reputation r
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.chat_id = %s
            ORDER BY r.rep_score DESC
            LIMIT %s
        """, (chat_id, limit))
        return cur.fetchall()

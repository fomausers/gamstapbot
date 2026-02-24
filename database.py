import aiosqlite
import json
from datetime import datetime

DB_PATH = 'game_base.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица пользователей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance INTEGER DEFAULT 0,
                reg_date TEXT,
                is_banned INTEGER DEFAULT 0,
                last_bonus TEXT DEFAULT '0'
            )
        ''')

        # Таблица переводов
        await db.execute('''
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                from_user_name TEXT,
                to_user_id INTEGER,
                to_user_name TEXT,
                amount INTEGER,
                timestamp TEXT
            )
        ''')

        # НОВОЕ: Таблица логов рулетки
        await db.execute('''
            CREATE TABLE IF NOT EXISTS game_logs (
                chat_id INTEGER,
                win_number INTEGER,
                win_color TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # НОВОЕ: Таблица последних ставок (для кнопок Повторить/Удвоить)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS last_bets (
                user_id INTEGER PRIMARY KEY,
                bets_data TEXT
            )
        ''')

        # НОВОЕ: Настройки чатов (включены ли игры)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                games_enabled INTEGER DEFAULT 1
            )
        ''')

        # НОВОЕ: Дневная статистика выигрышей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                user_id INTEGER PRIMARY KEY,
                win_amount INTEGER DEFAULT 0
            )
        ''')

        await db.commit()


async def patch_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Список запросов для обновления базы без потери данных
        patches = [
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_bonus TEXT DEFAULT '0'"
        ]
        for query in patches:
            try:
                await db.execute(query)
            except:
                pass  # Если колонка уже есть
        await db.commit()

# --- ФУНКЦИИ ПОЛЬЗОВАТЕЛЕЙ ---

async def check_user(user_id, username, full_name):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            if not user:
                await db.execute(
                    "INSERT INTO users (user_id, username, full_name, reg_date) VALUES (?, ?, ?, ?)",
                    (user_id, username, full_name, datetime.now().strftime("%d.%m.%Y"))
                )
                await db.commit()

async def get_user_data(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# Функция-обертка для рулетки
async def get_balance(user_id):
    user = await get_user_data(user_id)
    return user['balance'] if user else 0

# --- РАЗДЕЛ БОНУСОВ ---

async def get_last_bonus(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else '0'

async def update_bonus_time(user_id, time_str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_bonus = ?, balance = balance + 2500 WHERE user_id = ?", (time_str, user_id))
        await db.commit()

# --- ФУНКЦИИ ПЕРЕВОДОВ ---

async def make_transfer(from_id, to_id, from_name, to_name, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (from_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < amount:
                return False

        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_id))
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_id))

        dt_string = datetime.now().strftime("%d.%m.%Y %H:%M")
        await db.execute(
            "INSERT INTO transfers (from_user_id, from_user_name, to_user_id, to_user_name, amount, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (from_id, from_name, to_id, to_name, amount, dt_string)
        )
        await db.commit()
        return True

async def get_history(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM transfers 
            WHERE from_user_id = ? OR to_user_id = ? 
            ORDER BY id DESC LIMIT 10
        """, (user_id, user_id)) as cursor:
            return await cursor.fetchall()



# --- ФУНКЦИИ РУЛЕТКИ ---

async def save_last_bet(user_id, bets):
    async with aiosqlite.connect(DB_PATH) as db:
        data = json.dumps(bets)
        await db.execute("INSERT OR REPLACE INTO last_bets (user_id, bets_data) VALUES (?, ?)", (user_id, data))
        await db.commit()

async def get_last_bet(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT bets_data FROM last_bets WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else None

async def add_game_log(chat_id, win_num, win_color):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO game_logs (chat_id, win_number, win_color) VALUES (?, ?, ?)",
                         (chat_id, win_num, win_color))
        await db.commit()

async def get_game_logs(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT win_number, win_color FROM game_logs WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 10", (chat_id,)) as cursor:
            return await cursor.fetchall()

async def is_games_enabled(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT games_enabled FROM chat_settings WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] == 1 if row else True

async def add_daily_win(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO daily_stats (user_id, win_amount) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET win_amount = win_amount + ?
        ''', (user_id, amount, amount))
        await db.commit()

def get_currency_icon():
    return "cron"

# Обертка для рулетки (чтобы не переписывать логику списания)
async def add_balance(user_id, amount):
    await set_balance(user_id, amount, mode="add")

# --- АДМИН-ФУНКЦИИ ---

async def set_balance(user_id: int, amount: int, mode="add"):
    async with aiosqlite.connect(DB_PATH) as db:
        if mode == "add":
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        elif mode == "set":
            await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def set_ban_status(user_id: int, status: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id))
        await db.commit()



async def add_donation(user_id, charge_id, cron_amount, stars_amount):
    async with aiosqlite.connect(DB_PATH) as db:
        # Создаем таблицу донатов, если её нет
        await db.execute('''
            CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                charge_id TEXT,
                cron_amount INTEGER,
                stars_amount INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute(
            "INSERT INTO donations (user_id, charge_id, cron_amount, stars_amount) VALUES (?, ?, ?, ?)",
            (user_id, charge_id, cron_amount, stars_amount)
        )
        await db.commit()


async def set_custom_currency(symbol: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings 
            (key TEXT PRIMARY KEY, value TEXT)
        ''')
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('currency_symbol', ?)",
            (symbol,)
        )
        await db.commit()

async def get_currency_symbol():
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT value FROM settings WHERE key = 'currency_symbol'") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "cron" # По умолчанию
        except:
            return "cron"



async def set_tap_emoji(symbol: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('tap_emoji', ?)",
            (symbol,)
        )
        await db.commit()

async def get_tap_emoji():
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT value FROM settings WHERE key = 'tap_emoji'") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "🔘" # Смайл по умолчанию
        except:
            return "🔘"



async def save_custom_emoji(emoji_str: str, slot_number: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS custom_emojis 
            (slot INTEGER PRIMARY KEY, emoji_text TEXT)
        ''')
        await db.execute(
            "INSERT OR REPLACE INTO custom_emojis (slot, emoji_text) VALUES (?, ?)",
            (slot_number, emoji_str)
        )
        await db.commit()

async def get_all_custom_emojis():
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT slot, emoji_text FROM custom_emojis ORDER BY slot ASC") as cursor:
                return await cursor.fetchall()
        except:
            return []




async def get_emoji_by_slot(slot_number: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT emoji_text FROM custom_emojis WHERE slot = ?", (slot_number,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "👋" # Если слот пустой, вернет обычную руку
        except:
            return "👋"



# В файле database.py

async def get_currency_symbol():
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # Создаем таблицу настроек, если её вдруг нет
            await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            async with db.execute("SELECT value FROM settings WHERE key = 'currency_symbol'") as cursor:
                row = await cursor.fetchone()
                # Если в базе что-то есть — возвращаем, если нет — возвращаем стандарт (Луну)
                return row[0] if row else "🌕"
        except Exception:
            return "🌕"
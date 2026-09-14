# =====================================================================
#   بوت إدارة الكوفينغات — aiogram 3 + aiosqlite + Telethon
#   الإصدار: 23 (StringSession + Environment Variables)
# =====================================================================

import os, re, sys, asyncio, logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

# ====================== الإعدادات ======================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8979319753:AAEnlYOahd7TkvET9a9BE4A4khkWtjmNmaE")
OWNER_ID = int(os.getenv("OWNER_ID", "8633059017"))
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME", "YourDevUsername")
DB_PATH = os.getenv("DB_PATH", "bot_database.db")
USERS_PER_PAGE = 5
DEFAULT_REQUIRED_REACTIONS = 100

# ---------- Telethon ----------
API_ID = int(os.getenv("API_ID", "39053073"))
API_HASH = os.getenv("API_HASH", "9a2522d03990c82545df5d5df257eb6f")
USERBOT_SESSION_STR = os.getenv("USERBOT_SESSION", "")
# ========================================================

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("config_bot")

try:
    import aiosqlite
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    from aiogram import Bot, Dispatcher, Router, F
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
    from aiogram.filters import CommandStart, Command, BaseFilter
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import Message, CallbackQuery, BotCommand
    from aiogram.utils.keyboard import InlineKeyboardBuilder
except ImportError as e:
    print("❌ مكتبة ناقصة:", e); sys.exit(1)


# =====================================================================
#                    حالة الإجراءات المعلّقة (Global)
# =====================================================================
_pending_actions: Dict[int, str] = {}


class PendingAdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return _pending_actions.get(message.from_user.id) == "add_admin"


# =====================================================================
#                          Database
# =====================================================================
class Database:
    def __init__(self, path=DB_PATH):
        self.path = path

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                    is_banned INTEGER DEFAULT 0, created_at TEXT, last_active TEXT
                );
                CREATE TABLE IF NOT EXISTS configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT,
                    config_text TEXT, file_id TEXT, file_type TEXT, file_name TEXT,
                    previous_config_id INTEGER, required_reactions INTEGER DEFAULT 100,
                    current_reactions INTEGER DEFAULT 0, watch_chat_id INTEGER,
                    watch_message_id INTEGER, watch_url TEXT, posted_chat_id INTEGER,
                    posted_message_id INTEGER, is_active INTEGER DEFAULT 1,
                    is_unlocked INTEGER DEFAULT 0, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS config_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, config_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL, username TEXT, claimed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS required_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                    username TEXT, title TEXT, type TEXT, invite_link TEXT
                );
                CREATE TABLE IF NOT EXISTS publish_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                    username TEXT, title TEXT, invite_link TEXT
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT,
                    sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS reactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    config_id INTEGER NOT NULL, reacted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY, username TEXT, name TEXT,
                    added_by INTEGER, added_at TEXT
                );
            """)
            await self._ensure_columns(db, "configs", {
                "file_id": "TEXT", "file_type": "TEXT", "file_name": "TEXT",
                "watch_chat_id": "INTEGER", "watch_message_id": "INTEGER", "watch_url": "TEXT",
                "posted_chat_id": "INTEGER", "posted_message_id": "INTEGER",
                "is_unlocked": "INTEGER DEFAULT 0", "is_active": "INTEGER DEFAULT 1",
                "required_reactions": "INTEGER DEFAULT 100",
                "current_reactions": "INTEGER DEFAULT 0", "created_at": "TEXT",
            })
            await self._ensure_columns(db, "config_claims", {
                "username": "TEXT", "claimed_at": "TEXT"})
            await self._ensure_columns(db, "admins", {
                "username": "TEXT", "name": "TEXT",
                "added_by": "INTEGER", "added_at": "TEXT",
            })
            await db.executescript("""
                CREATE INDEX IF NOT EXISTS idx_claims_config ON config_claims(config_id);
                CREATE INDEX IF NOT EXISTS idx_claims_user ON config_claims(user_id);
            """)
            await db.commit()
        logger.info("✅ DB ready.")

    async def _ensure_columns(self, db, table, columns):
        try:
            async with db.execute(f"PRAGMA table_info({table})") as cur:
                existing = {r[1] for r in await cur.fetchall()}
        except Exception:
            return
        if not existing:
            return
        for col, ctype in columns.items():
            if col not in existing:
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
                    logger.info(f"🔧 added {col} to {table}")
                except Exception as e:
                    logger.warning(f"add col {col} to {table}: {e}")

    # ---------- Users ----------
    async def add_or_update_user(self, uid, username, first_name):
        now = self._now()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)) as cur:
                exists = await cur.fetchone()
            if exists:
                await db.execute("UPDATE users SET username=?, first_name=?, last_active=? WHERE user_id=?",
                                 (username, first_name, now, uid))
            else:
                await db.execute("INSERT INTO users (user_id, username, first_name, created_at, last_active) "
                                 "VALUES (?, ?, ?, ?, ?)", (uid, username, first_name, now, now))
            await db.commit()

    async def is_banned(self, uid):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,)) as cur:
                r = await cur.fetchone()
                return bool(r and r[0])

    async def set_ban(self, uid, banned):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET is_banned=? WHERE user_id=?",
                             (1 if banned else 0, uid))
            await db.commit()

    async def all_user_ids(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT user_id FROM users WHERE is_banned=0") as cur:
                return [r[0] for r in await cur.fetchall()]

    async def search_users(self, q, limit=20):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE CAST(user_id AS TEXT) LIKE ? "
                                  "OR IFNULL(username,'') LIKE ? LIMIT ?",
                                  (f"%{q}%", f"%{q}%", limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def list_users(self, offset=0, limit=5):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY user_id LIMIT ? OFFSET ?",
                                  (limit, offset)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def count_users(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                return (await cur.fetchone())[0]

    async def get_user(self, uid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id=?", (uid,)) as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    # ---------- Admins ----------
    async def is_admin(self, uid):
        if uid == OWNER_ID:
            return True
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)) as cur:
                return await cur.fetchone() is not None

    async def add_admin(self, uid, username, name, added_by):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""INSERT INTO admins (user_id, username, name, added_by, added_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, name=excluded.name""",
                (uid, username, name, added_by, self._now()))
            await db.commit()

    async def remove_admin(self, uid):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM admins WHERE user_id=?", (uid,))
            await db.commit()

    async def list_admins(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM admins ORDER BY added_at") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def admin_ids(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT user_id FROM admins") as cur:
                return [r[0] for r in await cur.fetchall()]

    # ---------- Configs ----------
    async def count_configs(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM configs") as cur:
                return (await cur.fetchone())[0]

    async def create_config(self, title, description, config_text, previous_config_id,
                            required_reactions=100, file_id=None, file_type="text", file_name=None,
                            watch_chat_id=None, watch_message_id=None, watch_url=None,
                            posted_chat_id=None, posted_message_id=None):
        now = self._now()
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("""INSERT INTO configs (title, description, config_text, file_id,
                file_type, file_name, previous_config_id, required_reactions, is_unlocked, is_active,
                created_at, watch_chat_id, watch_message_id, watch_url, posted_chat_id, posted_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?, ?)""",
                (title, description, config_text, file_id, file_type, file_name, previous_config_id,
                 required_reactions, now, watch_chat_id, watch_message_id, watch_url,
                 posted_chat_id, posted_message_id))
            await db.commit()
            return cur.lastrowid

    async def get_config(self, cid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM configs WHERE id=?", (cid,)) as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    async def get_current_config(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM configs WHERE is_active=1 ORDER BY id DESC LIMIT 1") as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    async def get_previous_config(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM configs WHERE is_active=1 ORDER BY id DESC LIMIT 1 OFFSET 1") as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    async def get_all_configs(self, limit=50):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM configs ORDER BY id DESC LIMIT ?", (limit,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def find_config_by_watch(self, chat_id, msg_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM configs WHERE watch_chat_id=? AND watch_message_id=? LIMIT 1",
                                  (chat_id, msg_id)) as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    async def set_reaction_count(self, cid, count):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE configs SET current_reactions=? WHERE id=?", (count, cid))
            await db.commit()

    async def set_watch(self, cid, chat_id, msg_id, url=None):
        if chat_id > 0:
            chat_id = int(f"-100{chat_id}")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE configs SET watch_chat_id=?, watch_message_id=?, watch_url=? WHERE id=?",
                             (chat_id, msg_id, url, cid))
            await db.commit()

    async def set_posted(self, cid, chat_id, msg_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE configs SET posted_chat_id=?, posted_message_id=? WHERE id=?",
                             (chat_id, msg_id, cid))
            await db.commit()

    async def unlock_config(self, cid):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE configs SET is_unlocked=1 WHERE id=?", (cid,))
            await db.commit()

    async def delete_config(self, cid):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM configs WHERE id=?", (cid,))
            await db.execute("DELETE FROM config_claims WHERE config_id=?", (cid,))
            await db.commit()

    async def reset_all_configs(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM configs")
            await db.execute("DELETE FROM config_claims")
            await db.execute("DELETE FROM reactions")
            await db.execute("DELETE FROM sqlite_sequence WHERE name IN ('configs','config_claims','reactions')")
            await db.commit()

    async def update_locked_required_reactions(self, value):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("UPDATE configs SET required_reactions=? WHERE is_unlocked=0 AND is_active=1",
                                   (value,))
            await db.commit()
            return cur.rowcount

    # ---------- Claims ----------
    async def has_claimed(self, cid, uid):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT 1 FROM config_claims WHERE config_id=? AND user_id=?",
                                  (cid, uid)) as cur:
                return await cur.fetchone() is not None

    async def add_claim(self, cid, uid, username):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT 1 FROM config_claims WHERE config_id=? AND user_id=?",
                                  (cid, uid)) as cur:
                if await cur.fetchone():
                    return
            await db.execute("INSERT INTO config_claims (config_id, user_id, username, claimed_at) "
                             "VALUES (?, ?, ?, ?)", (cid, uid, username, self._now()))
            await db.commit()

    async def count_claims(self, cid):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM config_claims WHERE config_id=?", (cid,)) as cur:
                return (await cur.fetchone())[0]

    async def claims_by_config(self, cid, offset, limit):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM config_claims WHERE config_id=? "
                                  "ORDER BY claimed_at DESC LIMIT ? OFFSET ?",
                                  (cid, limit, offset)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def user_claimed_configs(self, uid, limit=30):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""SELECT c.id AS id, c.title AS title, cc.claimed_at AS claimed_at
                FROM config_claims cc JOIN configs c ON c.id = cc.config_id
                WHERE cc.user_id=? ORDER BY cc.claimed_at DESC LIMIT ?""", (uid, limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def all_claims(self, offset, limit):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT cc.id, cc.user_id, cc.username, cc.claimed_at,
                       c.id AS config_id, c.title AS config_title,
                       u.first_name AS user_name, u.username AS user_username
                FROM config_claims cc
                LEFT JOIN configs c ON c.id = cc.config_id
                LEFT JOIN users u ON u.user_id = cc.user_id
                ORDER BY cc.claimed_at DESC LIMIT ? OFFSET ?
            """, (limit, offset)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def count_all_claims(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM config_claims") as cur:
                return (await cur.fetchone())[0]

    async def delete_old_claims(self, keep_config_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM config_claims WHERE config_id != ?",
                (keep_config_id,))
            await db.commit()
            return cur.rowcount

    # ---------- Required / Publish ----------
    async def add_required(self, chat_id, username, title, kind, invite_link):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO required_channels (chat_id, username, title, type, invite_link) "
                             "VALUES (?, ?, ?, ?, ?)", (chat_id, username, title, kind, invite_link))
            await db.commit()

    async def list_required(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM required_channels ORDER BY id") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def delete_required(self, rid):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM required_channels WHERE id=?", (rid,))
            await db.commit()

    async def add_publish(self, chat_id, username, title, invite_link):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO publish_channels (chat_id, username, title, invite_link) "
                             "VALUES (?, ?, ?, ?)", (chat_id, username, title, invite_link))
            await db.commit()

    async def list_publish(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM publish_channels ORDER BY id") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def delete_publish(self, pid):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM publish_channels WHERE id=?", (pid,))
            await db.commit()

    async def get_setting(self, key, default=None):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
                r = await cur.fetchone()
                return r[0] if r else default

    async def set_setting(self, key, value):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, value))
            await db.commit()

    async def stats(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.path) as db:
            async def sc(q, *a):
                async with db.execute(q, a) as c:
                    return (await c.fetchone())[0]
            return {
                "users": await sc("SELECT COUNT(*) FROM users"),
                "active_users": await sc("SELECT COUNT(*) FROM users WHERE is_banned=0"),
                "banned": await sc("SELECT COUNT(*) FROM users WHERE is_banned=1"),
                "claims": await sc("SELECT COUNT(*) FROM config_claims"),
                "configs": await sc("SELECT COUNT(*) FROM configs"),
                "reactions": await sc("SELECT COUNT(*) FROM reactions"),
                "today": await sc("SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=?", today),
                "week": await sc("SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)>=?", week),
            }

    async def save_broadcast(self, message, sent, failed):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO broadcasts (message, sent, failed, created_at) VALUES (?, ?, ?, ?)",
                             (message[:500], sent, failed, self._now()))
            await db.commit()


db = Database()


# =====================================================================
#                          Userbot (StringSession)
# =====================================================================
class ReactionWatcher:
    def __init__(self):
        self.client = None
        self._started = False
        self.on_unlock = None

    async def start(self):
        if self._started:
            return
        if not USERBOT_SESSION_STR:
            logger.warning("⚠️ USERBOT_SESSION غير موجود — لن يعمل رصد التفاعلات!")
            return
        try:
            self.client = TelegramClient(
                StringSession(USERBOT_SESSION_STR), API_ID, API_HASH)

            @self.client.on(events.Raw())
            async def _on_raw(u):
                try:
                    await self._handle_update(u)
                except Exception as e:
                    logger.debug(f"raw ignored: {e}")

            await self.client.start()
            me = await self.client.get_me()
            self._started = True
            logger.info(f"✅ Userbot: @{me.username or me.id}")
        except Exception as e:
            logger.exception(f"⚠️ فشل تشغيل Userbot: {e}")
            self._started = False

    async def stop(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self._started = False

    async def fetch_count(self, chat_id, msg_id):
        if not self._started:
            return None
        try:
            m = await self.client.get_messages(chat_id, ids=msg_id)
            if not m or not m.reactions:
                return 0
            return sum(r.count for r in m.reactions.results)
        except Exception as e:
            logger.warning(f"fetch_count: {e}")
            return None

    async def sync_all(self):
        if not self._started:
            return
        configs = await db.get_all_configs(100)
        for cfg in configs:
            if cfg.get("is_unlocked"):
                continue
            if not cfg.get("watch_chat_id") or not cfg.get("watch_message_id"):
                continue
            count = await self.fetch_count(cfg["watch_chat_id"], cfg["watch_message_id"])
            if count is not None and count > (cfg["current_reactions"] or 0):
                await db.set_reaction_count(cfg["id"], count)
                logger.info(f"🔄 sync #{cfg['id']}: {cfg['current_reactions']}→{count}")
                if count >= (cfg["required_reactions"] or 100) and not cfg["is_unlocked"]:
                    await db.unlock_config(cfg["id"])
                    if self.on_unlock:
                        try:
                            await self.on_unlock(cfg["id"])
                        except Exception as e:
                            logger.warning(f"on_unlock sync: {e}")

    async def _handle_update(self, update):
        if not self._started:
            return
        cn = update.__class__.__name__
        if cn not in ("UpdateMessageReactions", "UpdateBotMessageReaction"):
            return
        msg_id = getattr(update, "msg_id", None)
        reactions = getattr(update, "reactions", None)
        peer = getattr(update, "peer", None)
        if not msg_id or not reactions or not peer:
            return
        try:
            entity = await self.client.get_entity(peer)
            chat_id = entity.id
            if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
                chat_id = int(f"-100{entity.id}")
        except Exception as e:
            logger.debug(f"get_entity: {e}")
            return
        total = sum(r.count for r in reactions.results)
        cfg = await db.find_config_by_watch(chat_id, msg_id)
        if not cfg:
            return
        old = cfg["current_reactions"] or 0
        if total <= old:
            return
        await db.set_reaction_count(cfg["id"], total)
        logger.info(f"❤️ #{cfg['id']}: {old}→{total}")
        if total >= (cfg["required_reactions"] or 100) and not cfg["is_unlocked"]:
            await db.unlock_config(cfg["id"])
            if self.on_unlock:
                try:
                    await self.on_unlock(cfg["id"])
                except Exception as e:
                    logger.warning(f"on_unlock: {e}")


watcher = ReactionWatcher()


# =====================================================================
#                          Keyboards
# =====================================================================
def is_owner(uid):
    return uid == OWNER_ID


async def safe_edit(call, text, reply_markup=None, disable_web_page_preview=False):
    try:
        await call.message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest:
        try:
            await call.message.delete()
        except Exception:
            pass
        try:
            await call.message.answer(
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception as e:
            logger.warning(f"safe_edit fallback failed: {e}")


def main_menu(owner=False):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 الكوفينغ الحالي", callback_data="user:current")
    kb.button(text="👤 حسابي", callback_data="user:profile")
    kb.button(text="📋 كوفينغاتي", callback_data="user:my")
    kb.button(text="ℹ️ معلومات البوت", callback_data="user:about")
    kb.button(text="👨‍💻 تواصل مع المطور", callback_data="user:dev")
    kb.button(text="🔄 تحديث", callback_data="user:refresh")
    if owner:
        kb.button(text="👑 لوحة المالك", callback_data="admin:panel")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def back_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 القائمة الرئيسية", callback_data="user:menu")
    return kb.as_markup()


def build_subscribe_kb(channels, config_id=None):
    kb = InlineKeyboardBuilder()
    for ch in channels:
        url = ch.get("invite_link")
        if not url and ch.get("username"):
            url = f"https://t.me/{ch['username'].lstrip('@')}"
        if not url:
            url = f"https://t.me/c/{str(ch['chat_id']).replace('-100', '')}"
        title = ch.get("title") or ch.get("username") or ch.get("chat_id")
        icon = "📢" if ch.get("type") == "channel" else "💬"
        kb.button(text=f"{icon} {title}", url=url)
    cb = f"user:check_sub:{config_id}" if config_id else "user:check_sub"
    kb.button(text="🔄 تحقق من الاشتراك", callback_data=cb)
    kb.adjust(1)
    return kb.as_markup()


def build_subscribe_text(channels):
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines = ["📢 <b>يجب عليك الاشتراك في القنوات التالية أولاً:</b>\n"]
    for idx, ch in enumerate(channels, 1):
        n = nums[idx-1] if idx <= 10 else f"{idx}."
        title = ch.get("title") or ch.get("chat_id") or "—"
        uname = ch.get("username")
        lines.append(f"{n} <b>{title}</b>" + (f" (@{uname})" if uname else ""))
    lines.append("\n<b>بعد الاشتراك اضغط:</b>\n🔄 <b>تحقق من الاشتراك</b>")
    return "\n".join(lines)


def claim_config_kb(cid, bot_username):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 استلام الكوفينغ", url=f"https://t.me/{bot_username}?start=config_{cid}")
    return kb.as_markup()


def dev_contact_kb(dev):
    kb = InlineKeyboardBuilder()
    kb.button(text="👨‍💻 مراسلة المطور", url=f"https://t.me/{dev}")
    kb.button(text="🔙 القائمة الرئيسية", callback_data="user:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_panel():
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 إدارة الكوفينغات", callback_data="admin:configs")
    kb.button(text="🔐 الاشتراك الإجباري", callback_data="admin:subs")
    kb.button(text="📢 قنوات النشر", callback_data="admin:pubchannels")
    kb.button(text="👥 إدارة المستخدمين", callback_data="admin:users")
    kb.button(text="🎁 التسليمات", callback_data="admin:deliveries")
    kb.button(text="👮 إدارة الأدمن", callback_data="admin:admins")
    kb.button(text="📊 الإحصائيات", callback_data="admin:stats")
    kb.button(text="📢 إذاعة", callback_data="admin:broadcast")
    kb.button(text="⚙️ إعدادات", callback_data="admin:settings")
    kb.button(text="🗑 إعادة تعيين", callback_data="admin:reset:confirm")
    kb.button(text="🔙 الرئيسية", callback_data="user:menu")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def admin_configs_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ إضافة كوفينغ", callback_data="admin:cfg:add")
    kb.button(text="📋 الكوفينغات", callback_data="admin:cfg:list")
    kb.button(text="🔗 تعديل رابط المراقبة", callback_data="admin:cfg:watch")
    kb.button(text="🗑 حذف كوفينغ", callback_data="admin:cfg:delete")
    kb.button(text="👥 المستلمون", callback_data="admin:cfg:claims")
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def admin_subs_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 إضافة قناة", callback_data="admin:sub:add_channel")
    kb.button(text="💬 إضافة مجموعة", callback_data="admin:sub:add_group")
    kb.button(text="📋 القائمة", callback_data="admin:sub:list")
    kb.button(text="🗑 حذف اشتراك", callback_data="admin:sub:delete")
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def admin_pubchannels_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ إضافة قناة نشر", callback_data="admin:pub:add")
    kb.button(text="📋 القائمة", callback_data="admin:pub:list")
    kb.button(text="🗑 حذف قناة", callback_data="admin:pub:delete")
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def admin_users_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 عدد المستخدمين", callback_data="admin:user:count")
    kb.button(text="🚫 حظر مستخدم", callback_data="admin:user:ban")
    kb.button(text="✅ فك الحظر", callback_data="admin:user:unban")
    kb.button(text="🔎 البحث عن مستخدم", callback_data="admin:user:search")
    kb.button(text="📋 القائمة", callback_data="admin:user:list")
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def admin_admins_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ إضافة أدمن", callback_data="admin:adm:add")
    kb.button(text="🗑 حذف أدمن", callback_data="admin:adm:del")
    kb.button(text="📋 قائمة الأدمن", callback_data="admin:adm:list")
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def broadcast_confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تأكيد", callback_data="admin:bc:confirm")
    kb.button(text="❌ إلغاء", callback_data="admin:bc:cancel")
    kb.adjust(2)
    return kb.as_markup()


def reset_confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ نعم، احذف الكل", callback_data="admin:reset:do")
    kb.button(text="❌ إلغاء", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def configs_list_kb(configs, prefix):
    kb = InlineKeyboardBuilder()
    for c in configs:
        status = "🟢" if c["is_unlocked"] else "🔒"
        kb.button(text=f"{status} #{c['id']} — {c['title'] or 'بدون عنوان'}",
                  callback_data=f"{prefix}:{c['id']}")
    kb.button(text="🔙 رجوع", callback_data="admin:configs")
    kb.adjust(1)
    return kb.as_markup()


def required_list_kb(items):
    kb = InlineKeyboardBuilder()
    for it in items:
        icon = "📢" if it["type"] == "channel" else "💬"
        kb.button(text=f"{icon} {it['title'] or it['chat_id']}",
                  callback_data=f"admin:sub:del:{it['id']}")
    kb.button(text="🔙 رجوع", callback_data="admin:subs")
    kb.adjust(1)
    return kb.as_markup()


def publish_list_kb(items):
    kb = InlineKeyboardBuilder()
    for it in items:
        kb.button(text=f"📢 {it['title'] or it['chat_id']}",
                  callback_data=f"admin:pub:del:{it['id']}")
    kb.button(text="🔙 رجوع", callback_data="admin:pubchannels")
    kb.adjust(1)
    return kb.as_markup()


def admins_list_kb(items):
    kb = InlineKeyboardBuilder()
    for it in items:
        uname = f"@{it['username']}" if it.get('username') else it['user_id']
        kb.button(text=f"🗑 {uname}", callback_data=f"admin:adm:del:{it['user_id']}")
    kb.button(text="🔙 رجوع", callback_data="admin:admins")
    kb.adjust(1)
    return kb.as_markup()


def cancel_kb(cb="admin:panel"):
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ إلغاء", callback_data=cb)
    return kb.as_markup()


def settings_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 عدد التفاعلات المطلوب", callback_data="admin:set:reactions")
    kb.button(text="✏️ تغيير اسم المطور", callback_data="admin:set:dev")
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def deliveries_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    return kb.as_markup()


# =====================================================================
#                          FSM
# =====================================================================
class ConfigFSM(StatesGroup):
    config_content = State()
    description = State()
    watch_link = State()


class WatchFSM(StatesGroup):
    select_config = State()
    link = State()


class SubFSM(StatesGroup):
    chat_ref = State()
    title = State()
    invite_link = State()


class PubFSM(StatesGroup):
    chat_ref = State()


class BroadcastFSM(StatesGroup):
    waiting = State()


class UserFSM(StatesGroup):
    search = State()
    ban = State()
    unban = State()


class SettingsFSM(StatesGroup):
    dev_username = State()
    required_reactions = State()


class AdminFSM(StatesGroup):
    add = State()
    remove = State()


user_router = Router(name="user")
admin_router = Router(name="admin")


# =====================================================================
#                          Helpers
# =====================================================================
def parse_tme_link(text):
    text = text.strip()
    m = re.search(r"t\.me/c/(\d+)/(\d+)", text)
    if m:
        return {"chat_id": int(f"-100{m.group(1)}"), "message_id": int(m.group(2))}
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", text)
    if m:
        return {"username": m.group(1), "message_id": int(m.group(2))}
    return None


async def resolve_username_to_id(bot, username):
    try:
        chat = await bot.get_chat(f"@{username.lstrip('@')}")
        return chat.id
    except Exception as e:
        logger.warning(f"resolve: {e}")
        return None


async def check_subscriptions(bot, uid):
    required = await db.list_required()
    missing = []
    for ch in required:
        try:
            m = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=uid)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            logger.warning(f"sub check: {e}")
            missing.append(ch)
    return missing


async def show_subscription_gate(event, bot, config_id=None):
    uid = event.from_user.id
    missing = await check_subscriptions(bot, uid)
    if not missing:
        return False
    text = build_subscribe_text(missing)
    markup = build_subscribe_kb(missing, config_id)
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)
    return True


async def send_config_content(target, cfg, edit=False):
    title = cfg.get("title") or f"الكوفينغ #{cfg.get('id')}"
    file_id = cfg.get("file_id")
    ftype = cfg.get("file_type") or "text"
    ctext = cfg.get("config_text") or ""
    cap = f"🎁 <b>{title}</b>"
    if file_id and ftype in ("document", "photo", "video", "audio"):
        try:
            if ftype == "document":
                await target.answer_document(file_id, caption=cap, reply_markup=back_menu())
            elif ftype == "photo":
                await target.answer_photo(file_id, caption=cap, reply_markup=back_menu())
            elif ftype == "video":
                await target.answer_video(file_id, caption=cap, reply_markup=back_menu())
            elif ftype == "audio":
                await target.answer_audio(file_id, caption=cap, reply_markup=back_menu())
            return
        except Exception as e:
            logger.warning(f"send file: {e}")
    text = f"🎁 <b>{title}</b>\n\n<code>{ctext or 'لا يوجد محتوى'}</code>"
    if edit:
        try:
            await target.edit_text(text, reply_markup=back_menu())
            return
        except TelegramBadRequest:
            pass
    await target.answer(text, reply_markup=back_menu())


_bot_ref = None


async def on_config_unlocked(cid):
    cfg = await db.get_config(cid)
    if not cfg:
        return
    try:
        bot_username = (await _bot_ref.get_me()).username
    except Exception:
        return
    text = (f"🔄 <b>{cfg['title'] or ('#' + str(cid))}</b>\n\n"
            f"🎉 <b>تم فتح الكوفينغ!</b>\n\n"
            f"📝 {cfg['description'] or '—'}\n\n"
            f"❤️ وصل التفاعل إلى <b>{cfg['required_reactions']}</b>.\n\n"
            f"👇 اضغط للاستلام:")
    kb = claim_config_kb(cid, bot_username)
    if cfg.get("posted_chat_id") and cfg.get("posted_message_id"):
        try:
            await _bot_ref.edit_message_text(chat_id=cfg["posted_chat_id"],
                message_id=cfg["posted_message_id"], text=text, reply_markup=kb)
            logger.info(f"✅ edited post #{cid}")
            return
        except Exception as e:
            logger.warning(f"edit fail #{cid}: {e}")
    channels = await db.list_publish()
    for ch in channels:
        try:
            await _bot_ref.send_message(chat_id=ch["chat_id"], text=text,
                reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"unlock post: {e}")


# =====================================================================
#                    User Handlers
# =====================================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    _pending_actions.pop(message.from_user.id, None)
    user = message.from_user
    await db.add_or_update_user(user.id, user.username, user.full_name)
    if await db.is_banned(user.id):
        await message.answer("🚫 أنت محظور."); return
    if await show_subscription_gate(message, bot):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("config_"):
        try:
            cid = int(parts[1].split("_", 1)[1])
        except ValueError:
            await message.answer("❌ رابط غير صالح."); return
        await handle_claim_flow(message, bot, cid)
        return
    is_own = is_owner(user.id) or await db.is_admin(user.id)
    await message.answer(
        f"👋 أهلاً <b>{user.full_name}</b>\n\n🎁 بوت توزيع كوفينغات القناة.\nاختر:",
        reply_markup=main_menu(is_own))


@user_router.callback_query(F.data == "user:menu")
async def cb_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    _pending_actions.pop(call.from_user.id, None)
    if await show_subscription_gate(call, bot):
        await call.answer(); return
    is_own = is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)
    await safe_edit(call, "🏠 <b>الرئيسية</b>", reply_markup=main_menu(is_own))
    await call.answer()


@user_router.callback_query(F.data == "user:refresh")
async def cb_refresh(call: CallbackQuery, bot: Bot):
    await call.answer("🔄")
    if await show_subscription_gate(call, bot):
        return
    is_own = is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)
    await safe_edit(call, "🏠 <b>الرئيسية</b>", reply_markup=main_menu(is_own))


@user_router.callback_query(F.data == "user:profile")
async def cb_profile(call: CallbackQuery, bot: Bot):
    if await show_subscription_gate(call, bot):
        await call.answer(); return
    u = call.from_user
    my = await db.user_claimed_configs(u.id, limit=100)
    uname_line = f"🔗 @{u.username}" if u.username else "🔗 لا يوجد Username"
    text = (f"👤 <b>حسابك</b>\n\n🆔 <code>{u.id}</code>\n📛 {u.full_name}\n"
            f"{uname_line}\n\n🎁 كوفينغاتك: <b>{len(my)}</b>")
    await safe_edit(call, text, reply_markup=back_menu())
    await call.answer()


@user_router.callback_query(F.data == "user:current")
async def cb_current(call: CallbackQuery, bot: Bot):
    if await show_subscription_gate(call, bot):
        await call.answer(); return
    cfg = await db.get_current_config()
    if not cfg:
        await safe_edit(call, "📭 لا يوجد كوفينغ.", reply_markup=back_menu())
        await call.answer(); return
    status = "🟢 مفتوح" if cfg["is_unlocked"] else "🔒 مغلق"
    watch_url = cfg.get("watch_url") or ""
    text = (f"🎁 <b>{cfg['title'] or ('#' + str(cfg['id']))}</b>\n\n"
            f"📝 {cfg['description'] or '—'}\n📊 {status}\n"
            f"❤️ {cfg['current_reactions']} / {cfg['required_reactions']}")
    if not cfg["is_unlocked"]:
        text += f"\n\n❌ <b>لم يصل {cfg['required_reactions']} تفاعل بعد.</b>"
        if watch_url:
            text += f"\n\n👇 <b>ضع ❤️ على المنشور التالي:</b>\n<a href='{watch_url}'>🔗 اضغط هنا للتفاعل</a>"
        await safe_edit(call, text, reply_markup=back_menu(), disable_web_page_preview=False)
        await call.answer(); return
    if await db.has_claimed(cfg["id"], call.from_user.id):
        text += "\n\n✅ استلمته مسبقاً."
        await safe_edit(call, text, reply_markup=back_menu())
        await call.answer(); return
    await send_config_content(call.message, cfg)
    await call.answer()


@user_router.callback_query(F.data == "user:my")
async def cb_my(call: CallbackQuery, bot: Bot):
    if await show_subscription_gate(call, bot):
        await call.answer(); return
    items = await db.user_claimed_configs(call.from_user.id, limit=50)
    if not items:
        await safe_edit(call, "📭 لم تستلم.", reply_markup=back_menu())
        await call.answer(); return
    lines = ["📋 <b>كوفينغاتي</b>\n"]
    for c in items:
        lines.append(f"• #{c['id']} — {c['title'] or '—'}")
    await safe_edit(call, "\n".join(lines), reply_markup=back_menu())
    await call.answer()


@user_router.callback_query(F.data == "user:about")
async def cb_about(call: CallbackQuery, bot: Bot):
    if await show_subscription_gate(call, bot):
        await call.answer(); return
    text = ("ℹ️ <b>معلومات</b>\n\n• كل كوفينغ يُفتح عند وصول تفاعلاته للعدد المطلوب.\n"
            "• الاشتراك الإجباري.")
    await safe_edit(call, text, reply_markup=back_menu())
    await call.answer()


@user_router.callback_query(F.data == "user:dev")
async def cb_dev(call: CallbackQuery, bot: Bot):
    if await show_subscription_gate(call, bot):
        await call.answer(); return
    dev = await db.get_setting("developer_username", DEVELOPER_USERNAME)
    await safe_edit(call, f"👨‍💻 @{dev}", reply_markup=dev_contact_kb(dev))
    await call.answer()


async def handle_claim_flow(message, bot, cid):
    user = message.from_user
    cfg = await db.get_config(cid)
    if not cfg:
        await message.answer("❌ غير موجود.", reply_markup=back_menu()); return
    if await db.is_banned(user.id):
        await message.answer("🚫 محظور."); return
    if await show_subscription_gate(message, bot, cid):
        return
    if not cfg["is_unlocked"]:
        watch_url = cfg.get("watch_url") or ""
        txt = (f"❌ <b>لم يصل الكوفينغ السابق إلى {cfg['required_reactions']} تفاعل بعد.</b>\n\n"
               f"❤️ التفاعل الحالي:\n<b>{cfg['current_reactions']} / {cfg['required_reactions']}</b>\n\n")
        if watch_url:
            txt += f"👇 <b>ضع ❤️ على المنشور التالي:</b>\n<a href='{watch_url}'>🔗 اضغط هنا للتفاعل</a>\n\n"
        txt += f"⏳ يجب أن يصل الكوفينغ السابق إلى {cfg['required_reactions']} تفاعل حتى تستطيع استلام الكوفينغ الجديد."
        await message.answer(txt, reply_markup=back_menu(), disable_web_page_preview=False)
        return
    if await db.has_claimed(cfg["id"], user.id):
        await message.answer("❌ استلمته مسبقاً.", reply_markup=back_menu()); return
    await db.add_claim(cfg["id"], user.id, user.username)
    await send_config_content(message, cfg)


@user_router.callback_query(F.data.startswith("user:check_sub"))
async def cb_check_sub(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    cid = int(parts[2]) if len(parts) > 2 else None
    missing = await check_subscriptions(bot, call.from_user.id)
    if missing:
        await call.answer("❌ لم تشترك.", show_alert=True)
        try:
            await call.message.edit_text(build_subscribe_text(missing),
                reply_markup=build_subscribe_kb(missing, cid))
        except TelegramBadRequest:
            pass
        return
    await call.answer("✅ تم التحقق.", show_alert=True)
    if cid:
        cfg = await db.get_config(cid)
        if cfg and cfg["is_unlocked"] and not await db.has_claimed(cid, call.from_user.id):
            await db.add_claim(cid, call.from_user.id, call.from_user.username)
            await send_config_content(call.message, cfg)
            return
    is_own = is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)
    await safe_edit(call, "🏠 <b>الرئيسية</b>", reply_markup=main_menu(is_own))


@user_router.message(F.chat.type == "private", F.text & ~F.text.startswith("/"))
async def user_general_message(message: Message, state: FSMContext, bot: Bot):
    return


# =====================================================================
#                    Admin Handlers
# =====================================================================
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        await message.answer("⛔"); return
    await state.clear()
    _pending_actions.pop(message.from_user.id, None)
    await message.answer("👑 <b>لوحة المالك</b>", reply_markup=admin_panel())


@admin_router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    _pending_actions.pop(call.from_user.id, None)
    await safe_edit(call, "👑 <b>لوحة المالك</b>", reply_markup=admin_panel())
    await call.answer()


@admin_router.callback_query(F.data == "admin:reset:confirm")
async def cb_reset_confirm(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("⛔", show_alert=True); return
    await safe_edit(call, "⚠️ سيتم حذف كل الكوفينغات.", reply_markup=reset_confirm_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:reset:do")
async def cb_reset_do(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("⛔", show_alert=True); return
    await db.reset_all_configs()
    await safe_edit(call, "✅ تم الحذف.", reply_markup=admin_panel())
    await call.answer("✅", show_alert=True)


@admin_router.callback_query(F.data == "admin:stats")
async def cb_stats(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    s = await db.stats()
    text = (f"📊 <b>الإحصائيات</b>\n\n👥 المستخدمون: <b>{s['users']}</b>\n"
            f"🟢 النشطون: <b>{s['active_users']}</b>\n🚫 المحظورون: <b>{s['banned']}</b>\n"
            f"🎁 الاستلامات: <b>{s['claims']}</b>\n📦 الكوفينغات: <b>{s['configs']}</b>\n"
            f"📅 اليوم: <b>{s['today']}</b> | الأسبوع: <b>{s['week']}</b>")
    await safe_edit(call, text, reply_markup=cancel_kb("admin:panel"))
    await call.answer()


# ----- Admins Management -----
@admin_router.callback_query(F.data == "admin:admins")
async def cb_admins(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("⛔ خاص بالمالك فقط", show_alert=True); return
    _pending_actions.pop(call.from_user.id, None)
    await state.clear()
    await safe_edit(call, "👮 <b>إدارة الأدمن</b>\n\nاختر من الخيارات أدناه:",
                    reply_markup=admin_admins_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:adm:add")
async def cb_adm_add(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("⛔", show_alert=True); return
    _pending_actions[call.from_user.id] = "add_admin"
    await state.set_state(AdminFSM.add)
    await safe_edit(call,
        "➕ <b>إضافة أدمن جديد</b>\n\n"
        "أرسل الآن:\n"
        "• <b>ID المستخدم</b> (رقم) — مثال: <code>8201255057</code>\n"
        "• أو <b>@username</b> — مثال: <code>@R_Souhaib</code>",
        reply_markup=cancel_kb("admin:admins"))
    await call.answer()


async def _do_add_admin(message: Message, bot: Bot):
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ أرسل ID أو @username.",
                             reply_markup=admin_admins_kb())
        return
    user_id = None
    username = None
    name = None

    cleaned = raw.replace(" ", "")
    if cleaned.lstrip("-").isdigit():
        try:
            user_id = int(cleaned)
        except ValueError:
            user_id = None
        if user_id:
            try:
                chat = await bot.get_chat(user_id)
                username = chat.username
                name = chat.full_name or chat.title or str(user_id)
            except Exception:
                name = str(user_id)
    else:
        uname = raw.lstrip("@").strip()
        if not uname:
            await message.answer("❌ صيغة غير صحيحة.",
                                 reply_markup=admin_admins_kb())
            return
        try:
            chat = await bot.get_chat(f"@{uname}")
            user_id = chat.id
            username = chat.username
            name = chat.full_name or chat.title or str(user_id)
        except Exception as e:
            await message.answer(
                f"❌ تعذّر إيجاد <code>@{uname}</code>\n"
                f"السبب: <code>{e}</code>\n\n"
                f"💡 جرّب إرسال الـ <b>ID الرقمي</b> مباشرة.",
                reply_markup=admin_admins_kb())
            return

    if not user_id:
        await message.answer("❌ صيغة غير صحيحة. أرسل ID رقمي أو @username.",
                             reply_markup=admin_admins_kb())
        return

    if user_id == OWNER_ID:
        await message.answer("ℹ️ المالك يمتلك كل الصلاحيات تلقائياً.",
                             reply_markup=admin_admins_kb())
        return

    await db.add_admin(user_id, username, name or str(user_id), message.from_user.id)

    await message.answer(
        f"✅ <b>تمت إضافة الأدمن بنجاح!</b>\n\n"
        f"👤 <b>الاسم:</b> {name or '—'}\n"
        f"🔗 <b>Username:</b> {'@' + username if username else 'لا يوجد'}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n\n"
        f"✅ لديه الآن كل صلاحيات اللوحة (ما عدا إدارة الأدمن).",
        reply_markup=admin_admins_kb())


@admin_router.message(F.text, PendingAdminFilter())
async def process_adm_add(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return
    _pending_actions.pop(message.from_user.id, None)
    await state.clear()
    try:
        await _do_add_admin(message, bot)
    except Exception as e:
        logger.exception("process_adm_add failed")
        try:
            await message.answer(f"❌ خطأ غير متوقع: <code>{e}</code>",
                                 reply_markup=admin_admins_kb())
        except Exception:
            pass


@admin_router.callback_query(F.data == "admin:adm:list")
async def cb_adm_list(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("⛔", show_alert=True); return
    items = await db.list_admins()
    if not items:
        await safe_edit(call, "📭 لا يوجد أدمن مضافون بعد.", reply_markup=admin_admins_kb())
        await call.answer(); return
    lines = [f"📋 <b>قائمة الأدمن</b> (العدد: <b>{len(items)}</b>)\n"]
    for i, it in enumerate(items, 1):
        uname = f"@{it['username']}" if it.get("username") else "—"
        lines.append(f"{i}. 👤 <b>{it['name'] or '—'}</b>\n"
                     f"   🔗 {uname}\n"
                     f"   🆔 <code>{it['user_id']}</code>")
    await safe_edit(call, "\n".join(lines), reply_markup=admin_admins_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:adm:del")
async def cb_adm_del(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("⛔", show_alert=True); return
    items = await db.list_admins()
    if not items:
        await safe_edit(call, "📭 لا يوجد أدمن.", reply_markup=admin_admins_kb())
        await call.answer(); return
    await safe_edit(call, "🗑 اختر الأدمن للحذف:", reply_markup=admins_list_kb(items))
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin:adm:del:"))
async def cb_adm_del_do(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("⛔", show_alert=True); return
    uid = int(call.data.split(":")[3])
    await db.remove_admin(uid)
    await call.answer("✅ تم الحذف", show_alert=True)
    await safe_edit(call, "👮 <b>إدارة الأدمن</b>", reply_markup=admin_admins_kb())


# ----- Deliveries -----
@admin_router.callback_query(F.data == "admin:deliveries")
async def cb_deliveries(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await show_deliveries_page(call, 0)
    await call.answer()


@admin_router.callback_query(F.data.startswith("deliv:page:"))
async def cb_deliv_page(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await show_deliveries_page(call, int(call.data.split(":")[2]))
    await call.answer()


async def show_deliveries_page(call, index):
    total = await db.count_all_claims()
    if total == 0:
        await safe_edit(call, "📭 لا توجد تسليمات حتى الآن.", reply_markup=deliveries_kb())
        return
    index = max(0, min(index, total - 1))
    items = await db.all_claims(index, 1)
    if not items:
        return
    it = items[0]
    user_name = it.get("user_name") or "—"
    username = it.get("user_username") or it.get("username")
    user_id = it.get("user_id")
    config_title = it.get("config_title") or f"#{it.get('config_id')}"
    claimed_at = it.get("claimed_at") or "—"
    uname_line = f"🔗 <b>Username:</b> @{username}" if username else "🔗 <b>Username:</b> لا يوجد"
    id_line = f"🆔 <b>ID:</b> <code>{user_id}</code>"
    profile_link = f"\n👤 <a href='tg://user?id={user_id}'>فتح حساب المستخدم</a>"
    text = (
        f"🎁 <b>بطاقة تسليم</b> — {index + 1} / {total}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📛 <b>الاسم:</b> {user_name}\n"
        f"{uname_line}\n"
        f"{id_line}\n\n"
        f"📦 <b>الكوفينغ المستلَم:</b> {config_title}\n"
        f"🕐 <b>التاريخ:</b> <code>{claimed_at}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━"
        f"{profile_link}"
    )
    kb = InlineKeyboardBuilder()
    nav_count = 0
    if index > 0:
        kb.button(text="⬅️ السابق", callback_data=f"deliv:page:{index - 1}")
        nav_count += 1
    if index < total - 1:
        kb.button(text="➡️ التالي", callback_data=f"deliv:page:{index + 1}")
        nav_count += 1
    kb.button(text="🔙 رجوع", callback_data="admin:panel")
    if nav_count == 2:
        kb.adjust(2, 1)
    else:
        kb.adjust(1, 1)
    await safe_edit(call, text, reply_markup=kb.as_markup(), disable_web_page_preview=True)


# ----- Broadcast -----
@admin_router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(BroadcastFSM.waiting)
    await safe_edit(call, "📢 أرسل الرسالة:", reply_markup=cancel_kb("admin:panel"))
    await call.answer()


@admin_router.message(BroadcastFSM.waiting)
async def process_broadcast(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await message.answer("📢 تأكيد؟", reply_markup=broadcast_confirm_kb())


@admin_router.callback_query(F.data == "admin:bc:cancel")
async def cb_bc_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(call, "❌", reply_markup=admin_panel())
    await call.answer()


@admin_router.callback_query(F.data == "admin:bc:confirm")
async def cb_bc_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    data = await state.get_data()
    await state.clear()
    src_chat = data.get("chat_id")
    src_msg = data.get("message_id")
    if not src_chat or not src_msg:
        await call.answer("❌", show_alert=True); return
    await safe_edit(call, "⏳ إرسال...")
    uids = await db.all_user_ids()
    sent, failed = 0, 0
    for uid in uids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=src_chat, message_id=src_msg)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=src_chat, message_id=src_msg)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await db.save_broadcast("broadcast", sent, failed)
    await safe_edit(call, f"✅ نجح: <b>{sent}</b>\n❌ فشل: <b>{failed}</b>",
                    reply_markup=admin_panel())
    await call.answer()


# ----- Configs -----
@admin_router.callback_query(F.data == "admin:configs")
async def cb_configs(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await safe_edit(call, "📦 <b>إدارة الكوفينغات</b>", reply_markup=admin_configs_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:cfg:add")
async def cb_cfg_add(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(ConfigFSM.config_content)
    await safe_edit(call, "📦 أرسل الآن <b>ملف الكوفينغ</b> أو <b>نصه</b>:",
                    reply_markup=cancel_kb("admin:configs"))
    await call.answer()


@admin_router.message(ConfigFSM.config_content)
async def cfg_content(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    file_id = None; ftype = "text"; fname = None; ctext = ""
    if message.document:
        file_id = message.document.file_id; ftype = "document"
        fname = message.document.file_name or "config_file"
    elif message.photo:
        file_id = message.photo[-1].file_id; ftype = "photo"; fname = "photo.jpg"
    elif message.video:
        file_id = message.video.file_id; ftype = "video"
        fname = message.video.file_name or "video.mp4"
    elif message.audio:
        file_id = message.audio.file_id; ftype = "audio"
        fname = message.audio.file_name or "audio.mp3"
    elif message.text:
        ctext = message.text.strip()
    else:
        await message.answer("❌ نوع غير مدعوم."); return
    await state.update_data(file_id=file_id, file_type=ftype, file_name=fname, config_text=ctext)
    await state.set_state(ConfigFSM.description)
    await message.answer("✅ تم الاستلام.\n\n📝 أرسل الوصف للقناة:")


@admin_router.message(ConfigFSM.description)
async def cfg_desc(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    desc = message.text.strip() if message.text else ""
    await state.update_data(description=desc)
    await state.set_state(ConfigFSM.watch_link)
    await message.answer("🔗 أرسل الآن <b>رابط منشور القناة</b> الذي سيراقبه البوت.\n\n"
                         "مثال:\n<code>https://t.me/RabihElite/72</code>\n"
                         "أو: <code>https://t.me/c/1234567890/123</code>")


@admin_router.message(ConfigFSM.watch_link)
async def cfg_watch_link(message: Message, state: FSMContext, bot: Bot):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    data = await state.get_data()
    watch_text = (message.text or "").strip()
    parsed = parse_tme_link(watch_text)
    if not parsed:
        await message.answer("❌ رابط غير صالح. أعد الإرسال."); return
    if "username" in parsed:
        chat_id = await resolve_username_to_id(bot, parsed["username"])
        if chat_id is None:
            await message.answer("⚠️ تعذّر قراءة القناة.\nتأكد البوت مشرف فيها."); return
    else:
        chat_id = parsed["chat_id"]
    message_id = parsed["message_id"]
    await state.clear()
    total = await db.count_configs()
    title = f"كوفينغ رقم {(total % 100) + 1}"
    prev = await db.get_previous_config()
    prev_id = prev["id"] if prev else None
    try:
        required = int(await db.get_setting("required_reactions",
                       str(DEFAULT_REQUIRED_REACTIONS)) or DEFAULT_REQUIRED_REACTIONS)
    except (TypeError, ValueError):
        required = DEFAULT_REQUIRED_REACTIONS
    current = 0
    try:
        fetched = await watcher.fetch_count(chat_id, message_id)
        if fetched is not None:
            current = fetched
    except Exception as e:
        logger.warning(f"initial fetch: {e}")

    cfg_id = await db.create_config(title=title, description=data.get("description", ""),
        config_text=data.get("config_text", ""), previous_config_id=prev_id,
        required_reactions=required, file_id=data.get("file_id"),
        file_type=data.get("file_type", "text"), file_name=data.get("file_name"),
        watch_chat_id=chat_id, watch_message_id=message_id, watch_url=watch_text)
    await db.set_reaction_count(cfg_id, current)

    deleted_count = await db.delete_old_claims(cfg_id)
    if deleted_count:
        logger.info(f"🗑 حُذفت {deleted_count} تسليمة قديمة.")

    if current >= required:
        await db.unlock_config(cfg_id)
        await on_config_unlocked(cfg_id)

    bot_username = (await bot.get_me()).username
    text = (f"🔄 <b>{title}</b>\n\n🎁 كوفينغ جديد متوفر للأعضاء\n\n"
            f"📝 {data.get('description', '')}\n\n"
            f"📌 للحصول على الكوفينغ الجديد، يجب أن يصل "
            f"<a href='{watch_text}'>هذا المنشور</a> إلى {required} تفاعل ❤️.\n\n"
            f"❤️ الحالي: <b>{current} / {required}</b>\n\n👇 اضغط على الزر:")
    kb = claim_config_kb(cfg_id, bot_username)
    sent_count = 0
    for ch in await db.list_publish():
        try:
            m = await bot.send_message(chat_id=ch["chat_id"], text=text,
                reply_markup=kb, disable_web_page_preview=False)
            await db.set_posted(cfg_id, m.chat.id, m.message_id)
            sent_count += 1
        except Exception as e:
            logger.warning(f"post: {e}")

    await message.answer(
        f"✅ تم إنشاء <b>{title}</b> (المعرّف #{cfg_id}).\n\n"
        f"🔗 المراقبة: <code>{chat_id}/{message_id}</code>\n"
        f"❤️ التفاعلات الحالية: <b>{current} / {required}</b>\n"
        f"📢 تم النشر في <b>{sent_count}</b> قناة.\n"
        f"🗑 تم حذف <b>{deleted_count}</b> تسليمة قديمة.")


@admin_router.callback_query(F.data == "admin:cfg:watch")
async def cb_cfg_watch(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    configs = await db.get_all_configs(50)
    if not configs:
        await safe_edit(call, "📭", reply_markup=admin_configs_kb())
        await call.answer(); return
    await state.set_state(WatchFSM.select_config)
    await safe_edit(call, "🔗 اختر الكوفينغ:",
        reply_markup=configs_list_kb(configs, "admin:cfg:watch_sel"))
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin:cfg:watch_sel:"))
async def cb_cfg_watch_sel(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    cid = int(call.data.split(":")[3])
    await state.update_data(edit_watch_id=cid)
    await state.set_state(WatchFSM.link)
    await safe_edit(call, f"🔗 أرسل رابط المنشور الجديد للكوفينغ #{cid}:",
        reply_markup=cancel_kb("admin:configs"))
    await call.answer()


@admin_router.message(WatchFSM.link)
async def watch_link_update(message: Message, state: FSMContext, bot: Bot):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    data = await state.get_data()
    cid = data.get("edit_watch_id")
    await state.clear()
    if not cid:
        return
    parsed = parse_tme_link(message.text.strip())
    if not parsed:
        await message.answer("❌ رابط غير صالح."); return
    if "username" in parsed:
        chat_id = await resolve_username_to_id(bot, parsed["username"])
        if chat_id is None:
            await message.answer("⚠️ تعذّر قراءة القناة."); return
    else:
        chat_id = parsed["chat_id"]
    message_id = parsed["message_id"]
    await db.set_watch(cid, chat_id, message_id, message.text.strip())
    fetched = await watcher.fetch_count(chat_id, message_id)
    if fetched is not None:
        await db.set_reaction_count(cid, fetched)
        cfg = await db.get_config(cid)
        req = (cfg or {}).get("required_reactions") or DEFAULT_REQUIRED_REACTIONS
        if fetched >= req:
            await db.unlock_config(cid)
            await on_config_unlocked(cid)
    await message.answer(f"✅ تم التحديث للكوفينغ #{cid}.\n"
        f"🔗 <code>{chat_id}/{message_id}</code>\n"
        f"❤️ الحالي: <b>{fetched if fetched is not None else '؟'}</b>",
        reply_markup=admin_configs_kb())


@admin_router.callback_query(F.data == "admin:cfg:list")
async def cb_cfg_list(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    configs = await db.get_all_configs(50)
    if not configs:
        await safe_edit(call, "📭", reply_markup=admin_configs_kb())
        await call.answer(); return
    lines = ["📋 <b>الكوفينغات</b>\n"]
    for c in configs:
        s = "🟢" if c["is_unlocked"] else "🔒"
        w = "🔗" if c.get("watch_message_id") else "❌"
        lines.append(f"{s} #{c['id']} — {c['title'] or '—'} "
                     f"({c['current_reactions']}/{c['required_reactions']}) {w}")
    await safe_edit(call, "\n".join(lines), reply_markup=admin_configs_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:cfg:delete")
async def cb_cfg_delete(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    configs = await db.get_all_configs(50)
    if not configs:
        await safe_edit(call, "📭", reply_markup=admin_configs_kb())
        await call.answer(); return
    await safe_edit(call, "🗑 اختر:", reply_markup=configs_list_kb(configs, "admin:cfg:del"))
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin:cfg:del:"))
async def cb_cfg_del_do(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    try:
        cid = int(call.data.split(":")[3])
    except Exception:
        await call.answer("❌", show_alert=True); return
    await db.delete_config(cid)
    await call.answer("✅", show_alert=True)
    await safe_edit(call, "📦", reply_markup=admin_configs_kb())


@admin_router.callback_query(F.data == "admin:cfg:claims")
async def cb_cfg_claims(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    configs = await db.get_all_configs(50)
    if not configs:
        await safe_edit(call, "📭", reply_markup=admin_configs_kb())
        await call.answer(); return
    await safe_edit(call, "👥 اختر:",
        reply_markup=configs_list_kb(configs, "admin:cfg:claims_sel"))
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin:cfg:claims_sel:"))
async def cb_cfg_claims_show(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    cid = int(call.data.split(":")[3])
    await show_claims_page(call, cid, 0)
    await call.answer()


@admin_router.callback_query(F.data.startswith("claims:page:"))
async def cb_claims_page(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    _, _, cid, page = call.data.split(":")
    await show_claims_page(call, int(cid), int(page))
    await call.answer()


async def show_claims_page(call, cid, page):
    total = await db.count_claims(cid)
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    items = await db.claims_by_config(cid, page * USERS_PER_PAGE, USERS_PER_PAGE)
    lines = [f"📋 <b>المستلمون - {page + 1}/{total_pages}</b>\n",
             f"🎁 #{cid}\n👥 <b>{total}</b>\n"]
    for i, it in enumerate(items, start=page * USERS_PER_PAGE + 1):
        if it.get("username"):
            lines.append(f"{i}. @{it['username']}")
        else:
            lines.append(f"{i}. <a href='tg://user?id={it['user_id']}'>مستخدم</a> "
                         f"(<code>{it['user_id']}</code>)")
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"claims:page:{cid}:{page - 1}")
    if page < total_pages - 1:
        kb.button(text="➡️", callback_data=f"claims:page:{cid}:{page + 1}")
    kb.button(text="🔙", callback_data="admin:configs")
    kb.adjust(2, 1)
    await safe_edit(call, "\n".join(lines), reply_markup=kb.as_markup())


# ----- Subscriptions -----
@admin_router.callback_query(F.data == "admin:subs")
async def cb_subs(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await safe_edit(call, "🔐 <b>الاشتراك الإجباري</b>", reply_markup=admin_subs_kb())
    await call.answer()


@admin_router.callback_query(F.data.in_({"admin:sub:add_channel", "admin:sub:add_group"}))
async def cb_sub_add(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    kind = "channel" if "channel" in call.data else "group"
    await state.update_data(kind=kind)
    await state.set_state(SubFSM.chat_ref)
    await safe_edit(call, "📢 أرسل معرّف أو رابط القناة/المجموعة:",
                    reply_markup=cancel_kb("admin:subs"))
    await call.answer()


@admin_router.message(SubFSM.chat_ref)
async def sub_chat_ref(message: Message, state: FSMContext, bot: Bot):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    raw = message.text.strip()
    candidate = raw
    if "t.me/" in raw:
        try:
            candidate = raw.split("t.me/")[1].split("/")[0]
        except Exception:
            pass
    chat = None
    try:
        if candidate.startswith("-") and candidate[1:].isdigit():
            chat = await bot.get_chat(int(candidate))
        else:
            uname = candidate if candidate.startswith("@") else f"@{candidate}"
            chat = await bot.get_chat(uname)
    except Exception as e:
        logger.warning(f"get_chat: {e}")
    if chat is None:
        await message.answer("❌ غير صحيح.", reply_markup=cancel_kb("admin:subs")); return
    await state.update_data(chat_id=chat.id, chat_username=chat.username,
        chat_title=chat.title or str(chat.id), chat_invite=chat.invite_link)
    await state.set_state(SubFSM.title)
    await message.answer(f"✅ {chat.title or chat.id}\n\n📝 عنوان (أو /skip):")


@admin_router.message(SubFSM.title)
async def sub_title(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    data = await state.get_data()
    title = (data.get("chat_title") or str(data.get("chat_id"))
             if message.text == "/skip" else message.text.strip())
    await state.update_data(title=title)
    await state.set_state(SubFSM.invite_link)
    await message.answer("🔗 رابط دعوة (أو /skip):")


@admin_router.message(SubFSM.invite_link)
async def sub_link(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    data = await state.get_data()
    await state.clear()
    chat_id = data.get("chat_id")
    chat_username = data.get("chat_username")
    chat_invite = data.get("chat_invite")
    title = data.get("title") or str(chat_id)
    kind = data.get("kind", "channel")
    link = (chat_invite or (f"https://t.me/{chat_username}" if chat_username else None)
            if message.text == "/skip" else message.text.strip())
    await db.add_required(chat_id, chat_username, title, kind, link)
    icon = "📢" if kind == "channel" else "💬"
    await message.answer(f"✅ تمت الإضافة {icon}.\n📢 {title}\n🆔 <code>{chat_id}</code>",
                         reply_markup=admin_subs_kb())


@admin_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    _pending_actions.pop(message.from_user.id, None)
    await state.clear()
    await message.answer("❌ تم الإلغاء.", reply_markup=admin_panel())


@admin_router.callback_query(F.data == "admin:sub:list")
async def cb_sub_list(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    items = await db.list_required()
    if not items:
        await safe_edit(call, "📭", reply_markup=admin_subs_kb())
        await call.answer(); return
    lines = ["📋 <b>الاشتراكات</b>\n"]
    for i, it in enumerate(items, 1):
        icon = "📢" if it["type"] == "channel" else "💬"
        uname = f"@{it['username']}" if it.get("username") else "—"
        lines.append(f"{i}. {icon} <b>{it['title'] or it['chat_id']}</b>\n"
                     f"   🆔 <code>{it['chat_id']}</code>\n   👤 {uname}")
    await safe_edit(call, "\n".join(lines), reply_markup=admin_subs_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:sub:delete")
async def cb_sub_delete(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    items = await db.list_required()
    if not items:
        await safe_edit(call, "📭", reply_markup=admin_subs_kb())
        await call.answer(); return
    await safe_edit(call, "🗑 اختر:", reply_markup=required_list_kb(items))
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin:sub:del:"))
async def cb_sub_del_do(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await db.delete_required(int(call.data.split(":")[3]))
    await call.answer("✅", show_alert=True)
    await safe_edit(call, "🔐", reply_markup=admin_subs_kb())


# ----- Publish -----
@admin_router.callback_query(F.data == "admin:pubchannels")
async def cb_pubchannels(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await safe_edit(call, "📢 <b>قنوات النشر</b>\n\nالبوت ينشر فيها إعلانات الكوفينغات.",
                    reply_markup=admin_pubchannels_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:pub:add")
async def cb_pub_add(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(PubFSM.chat_ref)
    await safe_edit(call, "📢 أرسل معرّف أو رابط القناة:",
                    reply_markup=cancel_kb("admin:pubchannels"))
    await call.answer()


@admin_router.message(PubFSM.chat_ref)
async def pub_chat_ref(message: Message, state: FSMContext, bot: Bot):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    raw = message.text.strip()
    candidate = raw
    if "t.me/" in raw:
        try:
            candidate = raw.split("t.me/")[1].split("/")[0]
        except Exception:
            pass
    chat = None
    try:
        if candidate.startswith("-") and candidate[1:].isdigit():
            chat = await bot.get_chat(int(candidate))
        else:
            uname = candidate if candidate.startswith("@") else f"@{candidate}"
            chat = await bot.get_chat(uname)
    except Exception as e:
        logger.warning(f"get_chat: {e}")
    if chat is None:
        await message.answer("❌", reply_markup=cancel_kb("admin:pubchannels")); return
    await db.add_publish(chat.id, chat.username, chat.title or str(chat.id), chat.invite_link)
    await state.clear()
    await message.answer(f"✅ قناة نشر: <b>{chat.title or chat.id}</b>\n🆔 <code>{chat.id}</code>",
                         reply_markup=admin_pubchannels_kb())


@admin_router.callback_query(F.data == "admin:pub:list")
async def cb_pub_list(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    items = await db.list_publish()
    if not items:
        await safe_edit(call, "📭", reply_markup=admin_pubchannels_kb())
        await call.answer(); return
    lines = ["📋 <b>قنوات النشر</b>\n"]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. 📢 <b>{it['title'] or it['chat_id']}</b>\n"
                     f"   🆔 <code>{it['chat_id']}</code>")
    await safe_edit(call, "\n".join(lines), reply_markup=admin_pubchannels_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:pub:delete")
async def cb_pub_delete(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    items = await db.list_publish()
    if not items:
        await safe_edit(call, "📭", reply_markup=admin_pubchannels_kb())
        await call.answer(); return
    await safe_edit(call, "🗑", reply_markup=publish_list_kb(items))
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin:pub:del:"))
async def cb_pub_del_do(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await db.delete_publish(int(call.data.split(":")[3]))
    await call.answer("✅", show_alert=True)
    await safe_edit(call, "📢", reply_markup=admin_pubchannels_kb())


# ----- Users -----
@admin_router.callback_query(F.data == "admin:users")
async def cb_users(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    await safe_edit(call, "👥 <b>إدارة المستخدمين</b>\n\nاختر من الخيارات أدناه:",
                    reply_markup=admin_users_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:user:count")
async def cb_user_count(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    total = await db.count_users()
    s = await db.stats()
    text = (f"📊 <b>إحصائيات المستخدمين</b>\n\n"
            f"👥 الإجمالي: <b>{total}</b>\n"
            f"🟢 النشطون: <b>{s['active_users']}</b>\n"
            f"🚫 المحظورون: <b>{s['banned']}</b>\n"
            f"📅 اليوم: <b>{s['today']}</b>\n"
            f"📆 الأسبوع: <b>{s['week']}</b>")
    await safe_edit(call, text, reply_markup=admin_users_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:user:search")
async def cb_user_search(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(UserFSM.search)
    await safe_edit(call, "🔎 أرسل ID أو جزء من الـ Username:",
                    reply_markup=cancel_kb("admin:users"))
    await call.answer()


@admin_router.message(UserFSM.search)
async def user_search(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    await state.clear()
    results = await db.search_users(message.text.strip(), 20)
    if not results:
        await message.answer("❌ لا نتائج.", reply_markup=admin_users_kb()); return
    lines = [f"🔎 <b>النتائج ({len(results)})</b>\n"]
    for u in results:
        banned = "🚫" if u["is_banned"] else "🟢"
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(f"{banned} <code>{u['user_id']}</code> — {uname}")
    await message.answer("\n".join(lines), reply_markup=admin_users_kb())


@admin_router.callback_query(F.data == "admin:user:ban")
async def cb_user_ban(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(UserFSM.ban)
    await safe_edit(call, "🚫 أرسل ID المستخدم للحظر:",
                    reply_markup=cancel_kb("admin:users"))
    await call.answer()


@admin_router.message(UserFSM.ban)
async def user_ban(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    await state.clear()
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌", reply_markup=admin_users_kb()); return
    await db.set_ban(uid, True)
    await message.answer(f"✅ تم حظر <code>{uid}</code>", reply_markup=admin_users_kb())


@admin_router.callback_query(F.data == "admin:user:unban")
async def cb_user_unban(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(UserFSM.unban)
    await safe_edit(call, "✅ أرسل ID المستخدم لفك الحظر:",
                    reply_markup=cancel_kb("admin:users"))
    await call.answer()


@admin_router.message(UserFSM.unban)
async def user_unban(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    await state.clear()
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌", reply_markup=admin_users_kb()); return
    await db.set_ban(uid, False)
    await message.answer(f"✅ تم فك الحظر عن <code>{uid}</code>", reply_markup=admin_users_kb())


@admin_router.callback_query(F.data == "admin:user:list")
async def cb_user_list(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await show_users_page(call, 0)
    await call.answer()


@admin_router.callback_query(F.data.startswith("users:page:"))
async def cb_users_page(call: CallbackQuery):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await show_users_page(call, int(call.data.split(":")[2]))
    await call.answer()


async def show_users_page(call, page):
    total = await db.count_users()
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    items = await db.list_users(page * USERS_PER_PAGE, USERS_PER_PAGE)
    lines = [f"📋 <b>المستخدمون - {page + 1}/{total_pages}</b>\n"]
    for i, u in enumerate(items, start=page * USERS_PER_PAGE + 1):
        banned = "🚫" if u["is_banned"] else "🟢"
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(f"{i}. {banned} <code>{u['user_id']}</code> — {uname}")
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"users:page:{page - 1}")
    if page < total_pages - 1:
        kb.button(text="➡️", callback_data=f"users:page:{page + 1}")
    kb.button(text="🔙", callback_data="admin:users")
    kb.adjust(2, 1)
    await safe_edit(call, "\n".join(lines), reply_markup=kb.as_markup())


# ----- Settings -----
@admin_router.callback_query(F.data == "admin:settings")
async def cb_settings(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.clear()
    dev = await db.get_setting("developer_username", DEVELOPER_USERNAME)
    req = await db.get_setting("required_reactions", str(DEFAULT_REQUIRED_REACTIONS))
    await safe_edit(call,
        f"⚙️ <b>الإعدادات</b>\n\n"
        f"🎯 عدد التفاعلات المطلوب: <b>{req}</b>\n"
        f"👨‍💻 المطور: @{dev}",
        reply_markup=settings_kb())
    await call.answer()


@admin_router.callback_query(F.data == "admin:set:reactions")
async def cb_set_reactions(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    current = await db.get_setting("required_reactions", str(DEFAULT_REQUIRED_REACTIONS))
    await state.set_state(SettingsFSM.required_reactions)
    await safe_edit(call,
        f"🎯 <b>عدد التفاعلات المطلوب حالياً:</b> <code>{current}</code>\n\n"
        "📝 أرسل الآن العدد الجديد (رقم صحيح موجب، مثال: <code>50</code>).\n\n"
        "ℹ️ سيُطبّق على:\n• الكوفينغات الجديدة\n• الكوفينغات الحالية <b>غير المفتوحة</b> فقط",
        reply_markup=cancel_kb("admin:settings"))
    await call.answer()


@admin_router.message(SettingsFSM.required_reactions)
async def set_required_reactions(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    raw = (message.text or "").strip()
    try:
        val = int(raw)
        if val < 1 or val > 1_000_000:
            raise ValueError
    except ValueError:
        await message.answer("❌ أرسل رقماً صحيحاً موجباً (1 على الأقل).",
                             reply_markup=admin_panel()); return
    await state.clear()
    await db.set_setting("required_reactions", str(val))
    updated = await db.update_locked_required_reactions(val)
    await message.answer(
        f"✅ <b>تم التعيين بنجاح!</b>\n\n🎯 العدد الجديد: <b>{val}</b>\n"
        f"🔄 تم تحديث <b>{updated}</b> كوفينغ حالياً غير مفتوح.\n"
        f"📌 سيُطبّق تلقائياً على الكوفينغات القادمة.",
        reply_markup=admin_panel())


@admin_router.callback_query(F.data == "admin:set:dev")
async def cb_set_dev(call: CallbackQuery, state: FSMContext):
    if not (is_owner(call.from_user.id) or await db.is_admin(call.from_user.id)):
        await call.answer("⛔", show_alert=True); return
    await state.set_state(SettingsFSM.dev_username)
    await safe_edit(call, "✏️ username (بدون @):", reply_markup=cancel_kb("admin:settings"))
    await call.answer()


@admin_router.message(SettingsFSM.dev_username)
async def set_dev_username(message: Message, state: FSMContext):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    await state.clear()
    val = message.text.strip().lstrip("@")
    await db.set_setting("developer_username", val)
    await message.answer(f"✅ @{val}", reply_markup=admin_panel())


# ----- /check -----
@admin_router.message(Command("check"))
async def cmd_check(message: Message, bot: Bot):
    if not (is_owner(message.from_user.id) or await db.is_admin(message.from_user.id)):
        return
    cfg = await db.get_current_config()
    if not cfg or not cfg.get("watch_message_id"):
        await message.answer("❌ لا يوجد كوفينغ بمراقبة."); return
    count = await watcher.fetch_count(cfg["watch_chat_id"], cfg["watch_message_id"])
    if count is None:
        await message.answer("❌ فشل القراءة. تأكد USERBOT_SESSION صحيح."); return
    await db.set_reaction_count(cfg["id"], count)
    await message.answer(f"❤️ الكوفينغ #{cfg['id']}: <b>{count}</b> / {cfg['required_reactions']}")
    if count >= cfg["required_reactions"] and not cfg["is_unlocked"]:
        await db.unlock_config(cfg["id"])
        await on_config_unlocked(cfg["id"])
        await message.answer(f"🎉 تم فتح الكوفينغ #{cfg['id']}!")


# =====================================================================
#                          Main
# =====================================================================
async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="بدء"),
        BotCommand(command="admin", description="لوحة المالك"),
        BotCommand(command="cancel", description="إلغاء"),
        BotCommand(command="check", description="فحص التفاعلات"),
    ])


async def main():
    global _bot_ref
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود.")
    if not OWNER_ID:
        raise RuntimeError("OWNER_ID غير موجود.")

    await db.init()

    if not USERBOT_SESSION_STR:
        logger.warning("⚠️ USERBOT_SESSION غير موجود — البوت سيعمل بدون رصد تفاعلات!")
    else:
        logger.info(f"✅ USERBOT_SESSION موجود (طول: {len(USERBOT_SESSION_STR)})")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    _bot_ref = bot
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(user_router)
    await set_commands(bot)
    watcher.on_unlock = on_config_unlocked

    try:
        await watcher.start()
    except Exception:
        logger.exception("⚠️ فشل تشغيل Userbot.")

    async def periodic_sync():
        while True:
            await asyncio.sleep(60)
            try:
                await watcher.sync_all()
            except Exception as e:
                logger.warning(f"sync: {e}")

    sync_task = asyncio.create_task(periodic_sync())
    me = await bot.get_me()
    logger.info(f"🤖 Bot started: @{me.username}")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sync_task.cancel()
        await watcher.stop()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
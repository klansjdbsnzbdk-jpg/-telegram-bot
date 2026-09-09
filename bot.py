import asyncio
import logging
import sqlite3
import aiosqlite
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup

# ==================== الإعدادات ====================
BOT_TOKEN = "8914863858:AAEsZujShfvrZ5VUQ6KT8A2QIClntbihH8Y"
OWNER_ID = 8633059017
DATABASE_PATH = "coving_bot.db"
ITEMS_PER_PAGE = 10

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== قاعدة البيانات ====================
class Database:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self._init_tables()
        self._migrate_tables()
    
    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_banned BOOLEAN DEFAULT 0,
                    is_admin BOOLEAN DEFAULT 0,
                    phone_number TEXT,
                    is_algerian_verified BOOLEAN DEFAULT 0,
                    verified_at TIMESTAMP,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS coving_files (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_file_id TEXT NOT NULL,
                    file_unique_id TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    status TEXT DEFAULT 'available',
                    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS file_deliveries (
                    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER,
                    user_id INTEGER,
                    delivery_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (file_id) REFERENCES coving_files(file_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS required_channels (
                    channel_id INTEGER PRIMARY KEY,
                    username TEXT,
                    title TEXT,
                    link TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    admin_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (admin_id) REFERENCES users(user_id),
                    FOREIGN KEY (added_by) REFERENCES users(user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user_id INTEGER,
                    to_user_id INTEGER,
                    message TEXT,
                    message_type TEXT,
                    file_id TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_reply BOOLEAN DEFAULT 0,
                    reply_to_id INTEGER,
                    FOREIGN KEY (from_user_id) REFERENCES users(user_id),
                    FOREIGN KEY (to_user_id) REFERENCES users(user_id)
                )
            ''')
            
            cursor.execute('''
                INSERT OR IGNORE INTO admins (admin_id, added_by)
                VALUES (?, ?)
            ''', (OWNER_ID, OWNER_ID))
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name, is_admin)
                VALUES (?, 'owner', 'Owner', 1)
            ''', (OWNER_ID,))
            
            conn.commit()
            logger.info("Database tables created successfully")
    
    def _migrate_tables(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'phone_number' not in columns:
                    cursor.execute('ALTER TABLE users ADD COLUMN phone_number TEXT')
                if 'is_algerian_verified' not in columns:
                    cursor.execute('ALTER TABLE users ADD COLUMN is_algerian_verified BOOLEAN DEFAULT 0')
                if 'verified_at' not in columns:
                    cursor.execute('ALTER TABLE users ADD COLUMN verified_at TIMESTAMP')
                
                conn.commit()
        except Exception as e:
            logger.error(f"Migration error: {e}")
    
    async def add_user(self, user_id: int, username: Optional[str], first_name: str, last_name: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_activity)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, username, first_name, last_name))
            await db.commit()
    
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def is_user_banned(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            return row[0] == 1 if row else False
    
    async def is_user_algerian_verified(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT is_algerian_verified FROM users WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            return row[0] == 1 if row else False
    
    async def verify_algerian_user(self, user_id: int, phone_number: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                UPDATE users 
                SET phone_number = ?, 
                    is_algerian_verified = 1, 
                    verified_at = CURRENT_TIMESTAMP 
                WHERE user_id = ?
            ''', (phone_number, user_id))
            await db.commit()
            return True
    
    async def ban_user(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            await db.commit()
            return True
    
    async def unban_user(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            await db.commit()
            return True
    
    async def is_admin(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,))
            row = await cursor.fetchone()
            return bool(row)
    
    async def add_admin(self, admin_id: int, added_by: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute('''
                    INSERT INTO admins (admin_id, added_by)
                    VALUES (?, ?)
                ''', (admin_id, added_by))
                await db.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (admin_id,))
                await db.commit()
                return True
            except sqlite3.IntegrityError:
                return False
    
    async def remove_admin(self, admin_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM admins WHERE admin_id = ?', (admin_id,))
            await db.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (admin_id,))
            await db.commit()
            return True
    
    async def get_admins(self) -> List[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT admin_id FROM admins')
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    
    async def get_available_file(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT * FROM coving_files 
                WHERE status = 'available' 
                ORDER BY file_id ASC 
                LIMIT 1
            ''')
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def get_file(self, file_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM coving_files WHERE file_id = ?', (file_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def mark_file_delivered(self, file_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT INTO file_deliveries (file_id, user_id)
                VALUES (?, ?)
            ''', (file_id, user_id))
            await db.commit()
    
    async def get_file_deliveries_count(self, file_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT COUNT(*) FROM file_deliveries WHERE file_id = ?
            ''', (file_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_coving_file(self, telegram_file_id: str, file_unique_id: str, 
                              file_name: str, mime_type: str, file_size: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                INSERT INTO coving_files (telegram_file_id, file_unique_id, file_name, mime_type, file_size, status)
                VALUES (?, ?, ?, ?, ?, 'available')
            ''', (telegram_file_id, file_unique_id, file_name, mime_type, file_size))
            await db.commit()
            return cursor.lastrowid
    
    async def delete_file(self, file_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM coving_files WHERE file_id = ?', (file_id,))
            await db.commit()
            return True
    
    async def get_files_stats(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT COUNT(*) FROM coving_files WHERE status = "available"')
            available = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(DISTINCT file_id) FROM file_deliveries')
            delivered_files = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM coving_files')
            total = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM file_deliveries')
            total_deliveries = (await cursor.fetchone())[0]
            
            return {
                'available': available,
                'delivered_files': delivered_files,
                'total': total,
                'total_deliveries': total_deliveries
            }
    
    async def get_all_files(self, offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT *, 
                    (SELECT COUNT(*) FROM file_deliveries WHERE file_id = coving_files.file_id) as delivered_count
                FROM coving_files 
                ORDER BY upload_time DESC 
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_auto_deliveries(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT fd.*, u.username, u.first_name, u.phone_number, u.is_algerian_verified,
                       cf.file_name
                FROM file_deliveries fd
                JOIN users u ON fd.user_id = u.user_id
                JOIN coving_files cf ON fd.file_id = cf.file_id
                ORDER BY fd.delivery_time DESC
                LIMIT ?
            ''', (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def add_required_channel(self, channel_id: int, username: str, title: str, link: str, added_by: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO required_channels (channel_id, username, title, link, added_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (channel_id, username, title, link, added_by))
            await db.commit()
    
    async def remove_required_channel(self, channel_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM required_channels WHERE channel_id = ?', (channel_id,))
            await db.commit()
    
    async def get_required_channels(self, active_only: bool = True) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = 'SELECT * FROM required_channels'
            if active_only:
                query += ' WHERE is_active = 1'
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_stats(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT COUNT(*) FROM users')
            total_users = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
            banned_users = (await cursor.fetchone())[0]
            
            cursor = await db.execute('''
                SELECT COUNT(*) FROM users 
                WHERE last_activity >= datetime('now', '-7 days')
            ''')
            active_users = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM users WHERE is_algerian_verified = 1')
            verified_users = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM file_deliveries')
            total_deliveries = (await cursor.fetchone())[0]
            
            files_stats = await self.get_files_stats()
            
            return {
                'total_users': total_users,
                'banned_users': banned_users,
                'active_users': active_users,
                'verified_users': verified_users,
                'total_deliveries': total_deliveries,
                'available_files': files_stats['available'],
                'delivered_files': files_stats['delivered_files'],
                'total_files': files_stats['total']
            }

db = Database()

# ==================== الحالات ====================
class AdminReplyState(StatesGroup):
    waiting_for_reply = State()

class UserReplyState(StatesGroup):
    waiting_for_reply = State()

class AddChannelState(StatesGroup):
    waiting_for_channel = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class AddFileState(StatesGroup):
    waiting_for_file = State()

class BanUserState(StatesGroup):
    waiting_for_user_id = State()

class UnbanUserState(StatesGroup):
    waiting_for_user_id = State()

class SearchUserState(StatesGroup):
    waiting_for_query = State()

class AddAdminState(StatesGroup):
    waiting_for_admin_id = State()

# ==================== الكيبوردات ====================
def get_main_menu(is_admin: bool = False, is_owner: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📥 طلب كوفينغ", callback_data="request_coving")],
        [InlineKeyboardButton(text="📞 التواصل مع الإدارة", callback_data="contact_admin")],
        [InlineKeyboardButton(text="📢 القنوات المطلوبة", callback_data="required_channels")],
        [InlineKeyboardButton(text="ℹ️ طريقة الاستخدام", callback_data="how_to_use")]
    ]
    
    if is_admin or is_owner:
        keyboard.append([InlineKeyboardButton(text="👑 لوحة المالك", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_phone_share_keyboard() -> ReplyKeyboardMarkup:
    button = KeyboardButton(text="📱 مشاركة رقم الهاتف", request_contact=True)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[button]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard

def get_admin_panel(is_owner: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📁 إدارة الكوفينغات", callback_data="manage_files")],
        [InlineKeyboardButton(text="📢 الاشتراك الإجباري", callback_data="manage_channels")],
        [InlineKeyboardButton(text="👥 إدارة المستخدمين", callback_data="manage_users")],
        [InlineKeyboardButton(text="📊 التسليمات", callback_data="deliveries_list")]
    ]
    
    if is_owner:
        keyboard.extend([
            [InlineKeyboardButton(text="👮 إدارة الأدمن", callback_data="manage_admins")],
            [InlineKeyboardButton(text="📊 الإحصائيات", callback_data="statistics")],
            [InlineKeyboardButton(text="📢 إذاعة", callback_data="broadcast")],
            [InlineKeyboardButton(text="⚙️ إعدادات", callback_data="settings")]
        ])
    
    keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_files_management_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="➕ إضافة كوفينغ", callback_data="add_coving_file")],
        [InlineKeyboardButton(text="📦 المخزون", callback_data="view_stock")],
        [InlineKeyboardButton(text="🗑 حذف كوفينغ", callback_data="delete_coving_file")],
        [InlineKeyboardButton(text="📊 إحصائيات الملفات", callback_data="file_stats")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_channels_management_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="➕ إضافة قناة", callback_data="add_channel")],
        [InlineKeyboardButton(text="📋 القنوات المطلوبة", callback_data="list_channels")],
        [InlineKeyboardButton(text="🗑 حذف قناة", callback_data="delete_channel")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_users_management_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📊 عدد المستخدمين", callback_data="user_count")],
        [InlineKeyboardButton(text="🚫 حظر مستخدم", callback_data="ban_user")],
        [InlineKeyboardButton(text="✅ فك الحظر", callback_data="unban_user")],
        [InlineKeyboardButton(text="🔎 البحث عن مستخدم", callback_data="search_user")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admins_management_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="➕ إضافة أدمن", callback_data="add_admin")],
        [InlineKeyboardButton(text="🗑 حذف أدمن", callback_data="remove_admin")],
        [InlineKeyboardButton(text="📋 قائمة الأدمن", callback_data="list_admins")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_button(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_reply_to_admin_button() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="↩️ الرد على الإدارة", callback_data="reply_to_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_reply_to_user_button(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="↩️ الرد على المستخدم", callback_data=f"reply_to_user_{user_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_check_subscription_button() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🔄 تحقق من الاشتراك", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_remove_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[]], resize_keyboard=True)

# ==================== الرواتر ====================
router = Router()

# ==================== دوال مساعدة ====================
def is_algerian_phone_number(phone: str) -> bool:
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    patterns = [
        r'^\+213\d{9}$', r'^00213\d{9}$', r'^213\d{9}$',
        r'^0\d{9}$', r'^05\d{8}$', r'^07\d{8}$', r'^06\d{8}$',
        r'^5\d{8}$', r'^7\d{8}$', r'^6\d{8}$',
    ]
    for pattern in patterns:
        if re.match(pattern, phone):
            if phone.startswith('0') or phone.startswith('5') or phone.startswith('6') or phone.startswith('7'):
                if phone.startswith('05') or phone.startswith('5'):
                    return len(phone) == 10 or len(phone) == 9
                elif phone.startswith('06') or phone.startswith('6'):
                    return len(phone) == 10 or len(phone) == 9
                elif phone.startswith('07') or phone.startswith('7'):
                    return len(phone) == 10 or len(phone) == 9
                elif phone.startswith('0'):
                    return len(phone) == 10
            return True
    return False

def normalize_phone_number(phone: str) -> str:
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    if phone.startswith('0'):
        phone = '+213' + phone[1:]
    elif phone.startswith('213') and not phone.startswith('+213'):
        phone = '+' + phone
    elif phone.startswith('00213'):
        phone = '+' + phone[2:]
    elif phone.startswith(('5', '6', '7')) and len(phone) == 9:
        phone = '+213' + phone
    return phone

async def check_subscriptions(bot, user_id: int, channels: list) -> list:
    not_subscribed = []
    for channel in channels:
        try:
            chat_member = await bot.get_chat_member(channel['channel_id'], user_id)
            if chat_member.status in ['left', 'kicked']:
                not_subscribed.append(channel)
        except Exception as e:
            logger.error(f"Error checking subscription: {e}")
            not_subscribed.append(channel)
    return not_subscribed

async def kick_user_from_channels(bot, user_id: int, channels: list):
    """طرد المستخدم من جميع القنوات المطلوبة"""
    for channel in channels:
        try:
            await bot.ban_chat_member(channel['channel_id'], user_id)
            logger.info(f"User {user_id} kicked from channel {channel['channel_id']}")
        except Exception as e:
            logger.error(f"Error kicking user {user_id} from channel {channel['channel_id']}: {e}")

async def show_main_menu(message: types.Message, user_id: int):
    is_admin = await db.is_admin(user_id)
    is_owner = user_id == OWNER_ID
    keyboard = get_main_menu(is_admin, is_owner)
    await message.answer(
        "👋 القائمة الرئيسية:\n\nاختر من الخيارات أدناه:",
        reply_markup=keyboard
    )

async def show_admin_panel(message: types.Message, user_id: int):
    is_owner = user_id == OWNER_ID
    keyboard = get_admin_panel(is_owner)
    try:
        await message.edit_text("👑 لوحة المالك\n\nاختر من الخيارات أدناه:", reply_markup=keyboard)
    except:
        await message.answer("👑 لوحة المالك\n\nاختر من الخيارات أدناه:", reply_markup=keyboard)

# ==================== أوامر المستخدم ====================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    await state.clear()
    
    if await db.is_user_banned(user_id):
        await message.answer("🚫 عذرًا، تم حظرك من استخدام هذا البوت.")
        return
    
    await db.add_user(user_id, username, first_name, last_name)
    
    if not username:
        await message.answer(
            "❌ عذرًا، لا يمكنك استخدام البوت لأن حسابك مجهول.\n\n"
            "👤 يجب عليك إضافة Username إلى حسابك في Telegram ثم العودة إلى البوت والمحاولة مرة أخرى."
        )
        return
    
    channels = await db.get_required_channels(active_only=True)
    if channels:
        not_subscribed = await check_subscriptions(message.bot, user_id, channels)
        if not_subscribed:
            channels_text = "\n".join([f"{i+1}️⃣ {ch['title']} (@{ch['username']})" for i, ch in enumerate(channels)])
            keyboard = get_check_subscription_button()
            await message.answer(
                f"📢 يجب عليك الاشتراك في القنوات التالية أولًا:\n\n{channels_text}\n\nبعد الاشتراك اضغط:\n🔄 تحقق من الاشتراك",
                reply_markup=keyboard, disable_web_page_preview=True
            )
            return
    
    is_admin = await db.is_admin(user_id)
    is_owner = user_id == OWNER_ID
    keyboard = get_main_menu(is_admin, is_owner)
    await message.answer(
        f"👋 أهلاً بك {first_name}!\n\nمرحبًا بك في بوت كوفينغ.\nيمكنك طلب ملفات الكوفينغ بسهولة من خلال القائمة أدناه.",
        reply_markup=keyboard
    )

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ لا توجد عملية نشطة لإلغائها.")
        return
    await state.clear()
    await message.answer("✅ تم إلغاء العملية.", reply_markup=get_remove_keyboard())
    user_id = message.from_user.id
    is_admin = await db.is_admin(user_id)
    is_owner = user_id == OWNER_ID
    keyboard = get_main_menu(is_admin, is_owner)
    await message.answer("👋 القائمة الرئيسية:", reply_markup=keyboard)

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    user_id = message.from_user.id
    if not await db.is_admin(user_id) and user_id != OWNER_ID:
        await message.answer("❌ عذرًا، ليس لديك صلاحية للوصول إلى لوحة المالك.")
        return
    await show_admin_panel(message, user_id)

# ==================== طلب كوفينغ ====================
@router.callback_query(F.data == "request_coving")
async def request_coving(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # التحقق من الحظر
    if await db.is_user_banned(user_id):
        await callback.message.edit_text("🚫 عذرًا، تم حظرك من استخدام هذا البوت.")
        return
    
    # التحقق من التوثيق
    if await db.is_user_algerian_verified(user_id):
        # مستخدم موثق → يعطيه كوفينغ مباشرة
        await give_coving_file(callback.message, user_id, callback.from_user.username, callback.from_user.first_name)
        return
    
    # غير موثق → يطلب مشاركة الرقم
    keyboard = get_phone_share_keyboard()
    await callback.message.delete()
    await callback.message.answer(
        "🇩🇿 للتأكد من أنك تستخدم رقمًا جزائريًا، اضغط على الزر أدناه وشارك رقم هاتفك مع البوت.\n\n"
        "📌 ملاحظة: رقم هاتفك سيتم تخزينه بشكل آمن ولن يتم مشاركته مع أي طرف آخر.\n"
        "⚠️ إذا كان رقمك غير جزائري، سيتم حظرك من البوت والقنوات.",
        reply_markup=keyboard
    )

# ==================== معالجة رقم الهاتف ====================
@router.message(F.contact)
async def handle_phone_number(message: Message, state: FSMContext):
    user_id = message.from_user.id
    contact = message.contact
    
    if contact.user_id != user_id:
        await message.answer("❌ يرجى مشاركة رقم هاتفك الخاص فقط.", reply_markup=get_remove_keyboard())
        await show_main_menu(message, user_id)
        return
    
    phone_number = contact.phone_number
    
    # التحقق من أن الرقم جزائري
    if is_algerian_phone_number(phone_number):
        # توثيق المستخدم
        normalized_phone = normalize_phone_number(phone_number)
        await db.verify_algerian_user(user_id, normalized_phone)
        
        await message.answer(
            f"✅ تم التحقق بنجاح!\n\n🇩🇿 رقم هاتفك جزائري ويمكنك الآن استخدام البوت.\n\n📱 الرقم المسجل: {normalized_phone}",
            reply_markup=get_remove_keyboard()
        )
        
        # إعطاء الكوفينغ مباشرة
        user_data = await db.get_user(user_id)
        await give_coving_file(
            message, 
            user_id, 
            message.from_user.username, 
            message.from_user.first_name,
            is_new_verified=True
        )
    else:
        # ❌ رقم غير جزائري → حظر المستخدم وطرده من القنوات
        await db.ban_user(user_id)
        
        # طرد المستخدم من جميع القنوات
        channels = await db.get_required_channels(active_only=True)
        if channels:
            await kick_user_from_channels(message.bot, user_id, channels)
        
        await message.answer(
            "❌ عذرًا، هذه الخدمة متاحة فقط للمستخدمين الذين لديهم أرقام هاتف جزائرية 🇩🇿.\n\n"
            "🚫 تم حظرك من البوت ومن جميع القنوات المطلوبة.\n\n"
            "إذا كنت تملك رقمًا جزائريًا، تواصل مع الإدارة لإلغاء الحظر.",
            reply_markup=get_remove_keyboard()
        )
        
        # إشعار المالك
        await notify_owner_ban(message.bot, user_id, message.from_user.username, message.from_user.first_name, phone_number)

async def give_coving_file(message: types.Message, user_id: int, username: str, first_name: str, is_new_verified: bool = False):
    """إعطاء المستخدم ملف كوفينغ"""
    available_file = await db.get_available_file()
    if not available_file:
        await message.answer(
            "⚠️ عذرًا، لا توجد ملفات كوفينغ متوفرة حاليًا.\n\nيرجى المحاولة لاحقًا."
        )
        return
    
    # تسجيل التسليم
    await db.mark_file_delivered(
        file_id=available_file['file_id'],
        user_id=user_id
    )
    
    # إرسال الملف للمستخدم
    try:
        await message.answer_document(
            available_file['telegram_file_id'],
            caption=f"✅ تم إرسال الكوفينغ بنجاح 🇩🇿\n\n"
                    f"👤 المستخدم: @{username or 'لا يوجد'}\n"
                    f"📱 رقمك موثق كجزائري\n"
                    f"📦 الملف: {available_file['file_name']}\n\n"
                    f"📌 يمكنك طلب كوفينغ آخر في أي وقت."
        )
    except Exception as e:
        logger.error(f"Error sending file to user {user_id}: {e}")
        await message.answer("❌ حدث خطأ أثناء إرسال الملف، يرجى المحاولة مرة أخرى.")
        return
    
    # إشعار المالك
    user_data = await db.get_user(user_id)
    phone = user_data.get('phone_number', 'غير مسجل') if user_data else 'غير مسجل'
    
    delivery_count = await db.get_file_deliveries_count(available_file['file_id'])
    
    await notify_owner_delivery(
        message.bot,
        user_id,
        username or 'لا يوجد',
        first_name,
        phone,
        available_file['file_id'],
        available_file['file_name'],
        delivery_count
    )
    
    if is_new_verified:
        await message.answer(
            "✅ يمكنك الآن طلب كوفينغ في أي وقت من خلال الزر 📥 طلب كوفينغ."
        )
    
    # عرض القائمة الرئيسية
    await show_main_menu(message, user_id)

async def notify_owner_delivery(bot, user_id: int, username: str, first_name: str, phone: str, file_id: int, file_name: str, delivery_count: int):
    """إشعار المالك بالتسليم"""
    message_text = (
        f"✅ تسليم كوفينغ 🇩🇿\n\n"
        f"👤 المستخدم: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📛 الاسم: {first_name}\n"
        f"📱 رقم الهاتف: {phone}\n"
        f"📦 الملف: {file_name} (#{file_id})\n"
        f"📤 تم تسليم هذا الملف {delivery_count} مرة\n"
        f"🕐 الوقت: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    
    try:
        await bot.send_message(OWNER_ID, message_text)
    except Exception as e:
        logger.error(f"Error notifying owner: {e}")

async def notify_owner_ban(bot, user_id: int, username: str, first_name: str, phone: str):
    """إشعار المالك بحظر مستخدم غير جزائري"""
    message_text = (
        f"🚫 تم حظر مستخدم غير جزائري\n\n"
        f"👤 المستخدم: @{username or 'لا يوجد'}\n"
        f"🆔 ID: {user_id}\n"
        f"📛 الاسم: {first_name}\n"
        f"📱 رقم الهاتف: {phone}\n"
        f"🕐 الوقت: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"📌 تم حظره من البوت ومن جميع القنوات المطلوبة."
    )
    
    try:
        await bot.send_message(OWNER_ID, message_text)
    except Exception as e:
        logger.error(f"Error notifying owner: {e}")

# ==================== كالبات المستخدم ====================
@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    channels = await db.get_required_channels(active_only=True)
    if not channels:
        await callback.message.edit_text("✅ لا توجد قنوات مطلوبة.")
        await show_main_menu(callback.message, user_id)
        return
    not_subscribed = await check_subscriptions(callback.bot, user_id, channels)
    if not_subscribed:
        channels_text = "\n".join([f"{i+1}️⃣ {ch['title']} (@{ch['username']})" for i, ch in enumerate(not_subscribed)])
        keyboard = get_check_subscription_button()
        await callback.message.edit_text(
            f"❌ لا تزال غير مشترك في القنوات التالية:\n\n{channels_text}\n\nبعد الاشتراك اضغط:\n🔄 تحقق من الاشتراك",
            reply_markup=keyboard, disable_web_page_preview=True
        )
    else:
        await callback.message.edit_text("✅ تم التحقق من اشتراكك في جميع القنوات.")
        await show_main_menu(callback.message, user_id)

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.answer()
    await show_main_menu(callback.message, callback.from_user.id)

@router.callback_query(F.data == "contact_admin")
async def contact_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    if await db.is_user_banned(user_id):
        await callback.message.edit_text("🚫 عذرًا، تم حظرك من استخدام هذا البوت.")
        return
    await callback.message.edit_text(
        "✉️ يمكنك التواصل مع الإدارة من خلال الضغط على الزر أدناه.\n\nسيتم إرسال رسالتك إلى المشرفين.",
        reply_markup=get_reply_to_admin_button()
    )

@router.callback_query(F.data == "reply_to_admin")
async def reply_to_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserReplyState.waiting_for_reply)
    await callback.message.edit_text(
        "✉️ اكتب رسالتك وسيتم إرسالها إلى الإدارة.\n\nيمكنك إرسال نص، صورة، ملف، أو فيديو.\nاضغط /cancel لإلغاء العملية."
    )

@router.message(StateFilter(UserReplyState.waiting_for_reply))
async def handle_user_reply_to_admin(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or 'لا يوجد'
    first_name = message.from_user.first_name
    if await db.is_user_banned(user_id):
        await message.answer("🚫 عذرًا، تم حظرك من استخدام هذا البوت.")
        await state.clear()
        return
    message_text = message.text or "رسالة غير نصية"
    message_type = 'text'
    file_id = None
    if message.photo:
        message_type = 'photo'
        file_id = message.photo[-1].file_id
        message_text = message.caption or "صورة"
    elif message.document:
        message_type = 'document'
        file_id = message.document.file_id
        message_text = message.caption or message.document.file_name
    elif message.video:
        message_type = 'video'
        file_id = message.video.file_id
        message_text = message.caption or "فيديو"
    
    admin_message = (
        f"📩 رد جديد من المستخدم\n\n👤 @{username}\n🆔 ID: {user_id}\n"
        f"📛 الاسم: {first_name}\n\n💬 الرسالة:\n{message_text}"
    )
    reply_keyboard = get_reply_to_user_button(user_id)
    try:
        if message_type == 'text':
            await message.bot.send_message(OWNER_ID, admin_message, reply_markup=reply_keyboard)
        elif message_type == 'photo':
            await message.bot.send_photo(OWNER_ID, file_id, caption=admin_message, reply_markup=reply_keyboard)
        elif message_type == 'document':
            await message.bot.send_document(OWNER_ID, file_id, caption=admin_message, reply_markup=reply_keyboard)
        elif message_type == 'video':
            await message.bot.send_video(OWNER_ID, file_id, caption=admin_message, reply_markup=reply_keyboard)
    except Exception as e:
        logger.error(f"Error sending message to admin: {e}")
    await message.answer("✅ تم إرسال رسالتك إلى الإدارة.")
    await state.clear()

@router.callback_query(F.data == "required_channels")
async def show_required_channels(callback: CallbackQuery):
    await callback.answer()
    channels = await db.get_required_channels(active_only=True)
    if not channels:
        await callback.message.edit_text("📢 لا توجد قنوات مطلوبة حالياً.\n\nيمكنك استخدام البوت مباشرة.")
        return
    channels_text = "📢 القنوات المطلوبة للاشتراك:\n\n"
    for i, channel in enumerate(channels, 1):
        channels_text += f"{i}️⃣ {channel['title']}\n   @{channel['username']}\n\n"
    channels_text += "يرجى الاشتراك في جميع القنوات أعلاه للاستفادة من خدمات البوت."
    keyboard = get_check_subscription_button()
    await callback.message.edit_text(channels_text, reply_markup=keyboard)

@router.callback_query(F.data == "how_to_use")
async def how_to_use(callback: CallbackQuery):
    await callback.answer()
    text = (
        "ℹ️ طريقة استخدام البوت:\n\n"
        "1️⃣ اضغط على 📥 طلب كوفينغ.\n"
        "2️⃣ شارك رقم هاتفك مع البوت.\n"
        "3️⃣ إذا كان رقمك جزائرياً 🇩🇿، ستحصل على الكوفينغ فوراً.\n"
        "4️⃣ إذا كان رقمك غير جزائري، سيتم حظرك من البوت والقنوات.\n"
        "5️⃣ يمكنك طلب كوفينغ في أي وقت.\n"
        "6️⃣ للتواصل مع الإدارة استخدم 📞 التواصل مع الإدارة.\n\n"
        "📌 ملاحظات:\n"
        "- يجب أن يكون لديك اسم مستخدم (Username) لاستخدام البوت.\n"
        "- يجب أن يكون لديك رقم هاتف جزائري.\n"
        "- يجب الاشتراك في القنوات المطلوبة.\n"
        "- الموثقون جزائرياً يحصلون على الكوفينغ تلقائياً."
    )
    await callback.message.edit_text(text, reply_markup=get_back_button())

# ==================== كالبات لوحة المالك ====================
@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    if not await db.is_admin(user_id) and user_id != OWNER_ID:
        await callback.message.edit_text("❌ عذرًا، ليس لديك صلاحية للوصول إلى لوحة المالك.")
        return
    await show_admin_panel(callback.message, user_id)

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    await callback.answer()
    await show_admin_panel(callback.message, callback.from_user.id)

# ==================== عرض التسليمات ====================
@router.callback_query(F.data == "deliveries_list")
async def deliveries_list(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    if not await db.is_admin(user_id) and user_id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لعرض التسليمات.")
        return
    
    deliveries = await db.get_auto_deliveries(50)
    
    if not deliveries:
        await callback.message.edit_text(
            "📊 لا توجد تسليمات حتى الآن.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    text = "📊 قائمة التسليمات 🇩🇿\n\n"
    for i, d in enumerate(deliveries[:20], 1):
        text += f"{i}. @{d['username'] or 'مجهول'}\n"
        text += f"   🆔 ID: {d['user_id']}\n"
        text += f"   📱 رقم: {d['phone_number'] or 'غير مسجل'}\n"
        text += f"   📦 ملف: {d['file_name']}\n"
        text += f"   🕐 {d['delivery_time'][:16]}\n\n"
    
    if len(deliveries) > 20:
        text += f"\n📌 عرض آخر 20 من {len(deliveries)} تسليم"
    
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

# ==================== إدارة الكوفينغات ====================
@router.callback_query(F.data == "manage_files")
async def manage_files(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_files_management_menu()
    await callback.message.edit_text("📁 إدارة الكوفينغات\n\nاختر من الخيارات أدناه:", reply_markup=keyboard)

@router.callback_query(F.data == "add_coving_file")
async def add_coving_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddFileState.waiting_for_file)
    await callback.message.edit_text(
        "📤 أرسل ملف الكوفينغ الآن.\n\nيمكنك إرسال ملف من نوع PDF, DOC, DOCX, أو أي ملف مناسب.\n"
        "سيتم تخزين الملف في قاعدة البيانات وسيتم استخدامه لتلبية طلبات المستخدمين.\n"
        "الملف سيبقى متوفراً حتى تقوم بحذفه يدوياً.\n\nاضغط /cancel لإلغاء العملية."
    )

@router.message(StateFilter(AddFileState.waiting_for_file), F.document)
async def handle_coving_file_upload(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await db.is_admin(user_id) and user_id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية لإضافة ملفات.")
        await state.clear()
        return
    document = message.document
    file_id = await db.add_coving_file(
        document.file_id, document.file_unique_id,
        document.file_name or "unknown", document.mime_type or "unknown", document.file_size
    )
    await message.answer(
        f"✅ تمت إضافة الكوفينغ بنجاح إلى المخزن.\n\n📄 اسم الملف: {document.file_name}\n"
        f"📊 الحجم: {document.file_size / 1024:.2f} كيلوبايت\n🆔 رقم الملف: #{file_id}\n\n"
        f"📌 ملاحظة: الملف سيبقى متوفراً لتلبية طلبات المستخدمين حتى تقوم بحذفه يدوياً."
    )
    await state.clear()

@router.message(StateFilter(AddFileState.waiting_for_file))
async def invalid_file_upload(message: Message, state: FSMContext):
    await message.answer("❌ الرجاء إرسال ملف صحيح.\n\nاضغط /cancel لإلغاء العملية.")

@router.callback_query(F.data == "view_stock")
async def view_stock(callback: CallbackQuery):
    await callback.answer()
    stats = await db.get_files_stats()
    files = await db.get_all_files(0, 10)
    text = f"📦 مخزون الكوفينغات\n\n🟢 المتوفر: {stats['available']}\n📤 عدد مرات التسليم: {stats['total_deliveries']}\n📊 الإجمالي: {stats['total']}\n\n"
    if files:
        text += "📋 الملفات:\n"
        for file in files[:5]:
            delivered_count = file.get('delivered_count', 0)
            text += f"🔹 {file['file_name']} (#{file['file_id']}) - تم تسليمه {delivered_count} مرة\n"
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data == "delete_coving_file")
async def delete_coving_file_start(callback: CallbackQuery):
    await callback.answer()
    files = await db.get_all_files(0, 20)
    if not files:
        await callback.message.edit_text("📭 لا توجد ملفات للحذف.\n\nقم بإضافة ملفات جديدة أولاً.", reply_markup=get_back_button(callback_data="back_to_admin"))
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for file in files[:10]:
        delivered_count = file.get('delivered_count', 0)
        status_emoji = "📤" if delivered_count > 0 else "🟢"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {file['file_name']} (#{file['file_id']}) - {delivered_count} تسليم",
                callback_data=f"delete_file_{file['file_id']}"
            )
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    await callback.message.edit_text(
        "🗑 اختر الملف الذي تريد حذفه:\n\n🟢 = لم يتم تسليمه بعد\n📤 = تم تسليمه لبعض المستخدمين\n⚠️ سيتم حذف الملف نهائياً.",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("delete_file_"))
async def delete_file_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    file_id = int(callback.data.split("_")[2])
    file_data = await db.get_file(file_id)
    if not file_data:
        await callback.message.edit_text("❌ الملف غير موجود.", reply_markup=get_back_button(callback_data="back_to_admin"))
        return
    delivered_count = await db.get_file_deliveries_count(file_id)
    await state.update_data(file_id=file_id)
    keyboard = get_confirm_delete_buttons(file_id)
    await callback.message.edit_text(
        f"⚠️ هل أنت متأكد من حذف الملف التالي؟\n\n📄 اسم الملف: {file_data['file_name']}\n🆔 رقم الملف: #{file_data['file_id']}\n📤 تم تسليمه: {delivered_count} مرة\n\nلا يمكن التراجع عن هذا الإجراء.",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("confirm_delete_file_"))
async def confirm_delete_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    file_id = int(callback.data.split("_")[3])
    await db.delete_file(file_id)
    await state.clear()
    await callback.message.edit_text(f"✅ تم حذف الملف #{file_id} بنجاح.", reply_markup=get_back_button(callback_data="back_to_admin"))

@router.callback_query(F.data == "cancel_delete_file")
async def cancel_delete_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ تم إلغاء عملية الحذف.")
    await show_admin_panel(callback.message, callback.from_user.id)

@router.callback_query(F.data == "file_stats")
async def file_stats(callback: CallbackQuery):
    await callback.answer()
    stats = await db.get_files_stats()
    text = f"📊 إحصائيات الملفات\n\n🟢 المتوفرة: {stats['available']}\n📤 عدد مرات التسليم: {stats['total_deliveries']}\n📊 الإجمالي: {stats['total']}\n\n📌 ملاحظة: الملفات تبقى متوفرة حتى بعد تسليمها للمستخدمين، ولا يتم حذفها تلقائياً."
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

# ==================== إدارة القنوات ====================
@router.callback_query(F.data == "manage_channels")
async def manage_channels(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_channels_management_menu()
    await callback.message.edit_text("📢 إدارة الاشتراك الإجباري\n\nاختر من الخيارات أدناه:", reply_markup=keyboard)

@router.callback_query(F.data == "add_channel")
async def add_channel_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddChannelState.waiting_for_channel)
    await callback.message.edit_text(
        "📢 أرسل معرف القناة أو رابطها.\n\nمثال:\n- معرف القناة: -1001234567890\n- رابط القناة: https://t.me/your_channel\n\nاضغط /cancel لإلغاء العملية."
    )

@router.message(StateFilter(AddChannelState.waiting_for_channel))
async def handle_add_channel(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if admin_id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية لإضافة قنوات.")
        await state.clear()
        return
    channel_input = message.text.strip()
    channel_id = None
    username = None
    title = ""
    try:
        if channel_input.startswith('https://t.me/'):
            username = channel_input.split('/')[-1]
            if username:
                try:
                    chat = await message.bot.get_chat(f"@{username}")
                    channel_id = chat.id
                    title = chat.title
                except Exception as e:
                    await message.answer(f"❌ لا يمكن العثور على القناة. تأكد من أن البوت مشرف في القناة.\n\nخطأ: {e}")
                    return
        elif channel_input.startswith('-100') or channel_input.startswith('-'):
            channel_id = int(channel_input)
            try:
                chat = await message.bot.get_chat(channel_id)
                title = chat.title
                username = chat.username
            except Exception as e:
                await message.answer(f"❌ لا يمكن العثور على القناة. تأكد من أن البوت مشرف في القناة.\n\nخطأ: {e}")
                return
        else:
            await message.answer("❌ الرجاء إدخال معرف قناة صحيح أو رابط صحيح.")
            return
        await db.add_required_channel(
            channel_id=channel_id,
            username=username or '',
            title=title,
            link=f"https://t.me/{username}" if username else '',
            added_by=admin_id
        )
        await message.answer(
            f"✅ تمت إضافة القناة بنجاح.\n\n📢 العنوان: {title}\n🆔 المعرف: {channel_id}\n👤 يوزرنيم: @{username or 'لا يوجد'}"
        )
    except ValueError:
        await message.answer("❌ معرف القناة غير صحيح.")
        return
    await state.clear()

@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery):
    await callback.answer()
    channels = await db.get_required_channels(active_only=False)
    if not channels:
        await callback.message.edit_text("📋 لا توجد قنوات مطلوبة حالياً.", reply_markup=get_back_button(callback_data="back_to_admin"))
        return
    text = "📋 القنوات المطلوبة:\n\n"
    for i, channel in enumerate(channels, 1):
        status = "🟢" if channel['is_active'] else "🔴"
        text += f"{status} {channel['title']}\n   🆔 {channel['channel_id']}\n"
        if channel['username']:
            text += f"   👤 @{channel['username']}\n"
        text += f"   📌 الحالة: {'نشطة' if channel['is_active'] else 'معطلة'}\n\n"
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data == "delete_channel")
async def delete_channel_start(callback: CallbackQuery):
    await callback.answer()
    channels = await db.get_required_channels(active_only=False)
    if not channels:
        await callback.message.edit_text("📋 لا توجد قنوات لحذفها.", reply_markup=get_back_button(callback_data="back_to_admin"))
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for channel in channels[:10]:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"🗑 {channel['title']}", callback_data=f"delete_channel_{channel['channel_id']}")
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    await callback.message.edit_text("🗑 اختر القناة التي تريد حذفها:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("delete_channel_"))
async def delete_channel(callback: CallbackQuery):
    await callback.answer()
    channel_id = int(callback.data.split("_")[2])
    await db.remove_required_channel(channel_id)
    await callback.message.edit_text(f"✅ تم حذف القناة بنجاح.", reply_markup=get_back_button(callback_data="back_to_admin"))

# ==================== إدارة المستخدمين ====================
@router.callback_query(F.data == "manage_users")
async def manage_users(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_users_management_menu()
    await callback.message.edit_text("👥 إدارة المستخدمين\n\nاختر من الخيارات أدناه:", reply_markup=keyboard)

@router.callback_query(F.data == "user_count")
async def user_count(callback: CallbackQuery):
    await callback.answer()
    stats = await db.get_stats()
    admins = await db.get_admins()
    text = f"📊 إحصائيات المستخدمين\n\n👥 إجمالي المستخدمين: {stats['total_users']}\n🟢 المستخدمون النشطون: {stats['active_users']}\n🚫 المحظورون: {stats['banned_users']}\n🇩🇿 الموثقون جزائرياً: {stats['verified_users']}\n📤 إجمالي التسليمات: {stats['total_deliveries']}\n👮 الأدمن: {len(admins)}"
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data == "ban_user")
async def ban_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BanUserState.waiting_for_user_id)
    await callback.message.edit_text("🚫 أرسل معرف المستخدم (User ID) الذي تريد حظره.\n\nيمكنك الحصول على معرف المستخدم من معلومات التسليم.\nاضغط /cancel لإلغاء العملية.")

@router.message(StateFilter(BanUserState.waiting_for_user_id))
async def handle_ban_user(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if admin_id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية لحظر المستخدمين.")
        await state.clear()
        return
    try:
        user_id = int(message.text.strip())
        if user_id == OWNER_ID:
            await message.answer("❌ لا يمكن حظر المالك.")
            await state.clear()
            return
        if await db.is_admin(user_id):
            await message.answer("❌ لا يمكن حظر أدمن.")
            await state.clear()
            return
        await db.ban_user(user_id)
        
        # طرد المستخدم من القنوات
        channels = await db.get_required_channels(active_only=True)
        if channels:
            await kick_user_from_channels(message.bot, user_id, channels)
        
        await message.answer(f"✅ تم حظر المستخدم {user_id} وطرده من القنوات.")
    except ValueError:
        await message.answer("❌ الرجاء إدخال معرف مستخدم صحيح (أرقام فقط).")
    await state.clear()

@router.callback_query(F.data == "unban_user")
async def unban_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UnbanUserState.waiting_for_user_id)
    await callback.message.edit_text("✅ أرسل معرف المستخدم (User ID) الذي تريد فك حظره.\n\nاضغط /cancel لإلغاء العملية.")

@router.message(StateFilter(UnbanUserState.waiting_for_user_id))
async def handle_unban_user(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if admin_id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية لفك حظر المستخدمين.")
        await state.clear()
        return
    try:
        user_id = int(message.text.strip())
        await db.unban_user(user_id)
        await message.answer(f"✅ تم فك حظر المستخدم {user_id}.")
    except ValueError:
        await message.answer("❌ الرجاء إدخال معرف مستخدم صحيح (أرقام فقط).")
    await state.clear()

@router.callback_query(F.data == "search_user")
async def search_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SearchUserState.waiting_for_query)
    await callback.message.edit_text("🔎 أرسل معرف المستخدم أو اسم المستخدم للبحث.\n\nمثال:\n- معرف: 123456789\n- يوزرنيم: @username\n\nاضغط /cancel لإلغاء العملية.")

@router.message(StateFilter(SearchUserState.waiting_for_query))
async def handle_search_user(message: Message, state: FSMContext):
    query = message.text.strip()
    try:
        if query.isdigit():
            user_id = int(query)
            user_data = await db.get_user(user_id)
        else:
            username = query.replace('@', '')
            async with aiosqlite.connect(DATABASE_PATH) as db_conn:
                db_conn.row_factory = aiosqlite.Row
                cursor = await db_conn.execute('SELECT * FROM users WHERE username = ?', (username,))
                user_data = await cursor.fetchone()
        if not user_data:
            await message.answer("❌ لم يتم العثور على المستخدم.")
            await state.clear()
            return
        text = f"👤 معلومات المستخدم:\n\n🆔 ID: {user_data['user_id']}\n👤 يوزرنيم: @{user_data['username'] or 'لا يوجد'}\n📛 الاسم: {user_data['first_name']}"
        if user_data['last_name']:
            text += f" {user_data['last_name']}"
        text += f"\n📌 الحالة: {'🚫 محظور' if user_data['is_banned'] else '🟢 نشط'}\n🇩🇿 موثق جزائرياً: {'✅' if user_data['is_algerian_verified'] else '❌'}"
        if user_data['phone_number']:
            text += f"\n📱 الرقم: {user_data['phone_number']}"
        text += f"\n📅 تاريخ التسجيل: {user_data['registered_at']}\n🕐 آخر نشاط: {user_data['last_activity']}"
        await message.answer(text)
    except Exception as e:
        await message.answer(f"❌ حدث خطأ: {e}")
    await state.clear()

# ==================== إدارة الأدمن ====================
@router.callback_query(F.data == "manage_admins")
async def manage_admins(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لإدارة الأدمن.")
        return
    keyboard = get_admins_management_menu()
    await callback.message.edit_text("👮 إدارة الأدمن\n\nاختر من الخيارات أدناه:", reply_markup=keyboard)

@router.callback_query(F.data == "add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لإضافة أدمن.")
        return
    await state.set_state(AddAdminState.waiting_for_admin_id)
    await callback.message.edit_text("➕ أرسل معرف المستخدم (User ID) الذي تريد إضافته كأدمن.\n\nاضغط /cancel لإلغاء العملية.")

@router.message(StateFilter(AddAdminState.waiting_for_admin_id))
async def handle_add_admin(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية لإضافة أدمن.")
        await state.clear()
        return
    try:
        admin_id = int(message.text.strip())
        if admin_id == OWNER_ID:
            await message.answer("❌ المالك بالفعل أدمن.")
            await state.clear()
            return
        success = await db.add_admin(admin_id, OWNER_ID)
        if success:
            await message.answer(f"✅ تم إضافة المستخدم {admin_id} كأدمن بنجاح.")
        else:
            await message.answer("❌ هذا المستخدم أدمن بالفعل.")
    except ValueError:
        await message.answer("❌ الرجاء إدخال معرف مستخدم صحيح (أرقام فقط).")
    await state.clear()

@router.callback_query(F.data == "remove_admin")
async def remove_admin_start(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لحذف أدمن.")
        return
    admins = await db.get_admins()
    admins = [a for a in admins if a != OWNER_ID]
    if not admins:
        await callback.message.edit_text("📋 لا يوجد أدمن لحذفهم.", reply_markup=get_back_button(callback_data="back_to_admin"))
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for admin_id in admins[:10]:
        user = await db.get_user(admin_id)
        name = user['first_name'] if user else str(admin_id)
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"🗑 {name} ({admin_id})", callback_data=f"remove_admin_{admin_id}")
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    await callback.message.edit_text("🗑 اختر الأدمن الذي تريد حذفه:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("remove_admin_"))
async def remove_admin(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لحذف أدمن.")
        return
    admin_id = int(callback.data.split("_")[2])
    if admin_id == OWNER_ID:
        await callback.message.edit_text("❌ لا يمكن حذف المالك.")
        return
    await db.remove_admin(admin_id)
    await callback.message.edit_text(f"✅ تم حذف الأدمن {admin_id} بنجاح.", reply_markup=get_back_button(callback_data="back_to_admin"))

@router.callback_query(F.data == "list_admins")
async def list_admins(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لعرض قائمة الأدمن.")
        return
    admins = await db.get_admins()
    if not admins:
        await callback.message.edit_text("📋 لا يوجد أدمن.", reply_markup=get_back_button(callback_data="back_to_admin"))
        return
    text = "👮 قائمة الأدمن:\n\n"
    for i, admin_id in enumerate(admins, 1):
        is_owner = " (👑 المالك)" if admin_id == OWNER_ID else ""
        user = await db.get_user(admin_id)
        if user:
            name = user['first_name']
            if user['username']:
                name += f" (@{user['username']})"
        else:
            name = str(admin_id)
        text += f"{i}️⃣ {name}{is_owner}\n"
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

# ==================== الإحصائيات والإذاعة ====================
@router.callback_query(F.data == "statistics")
async def statistics(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لعرض الإحصائيات.")
        return
    stats = await db.get_stats()
    text = f"📊 إحصائيات البوت\n\n👥 إجمالي المستخدمين: {stats['total_users']}\n🟢 المستخدمون النشطون: {stats['active_users']}\n🚫 المحظورون: {stats['banned_users']}\n🇩🇿 الموثقون جزائرياً: {stats['verified_users']}\n📤 إجمالي التسليمات: {stats['total_deliveries']}\n\n📦 الملفات المتوفرة: {stats['available_files']}\n📤 الملفات المسلمة: {stats['delivered_files']}\n📊 إجمالي الملفات: {stats['total_files']}"
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data == "broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية للإذاعة.")
        return
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.edit_text(
        "📢 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين.\n\nيمكنك إرسال نص، صورة، ملف، أو فيديو.\nسيتم إرسالها لجميع المستخدمين المسجلين.\n\n⚠️ تحذير: قد تستغرق العملية بعض الوقت.\nاضغط /cancel لإلغاء العملية."
    )

@router.message(StateFilter(BroadcastState.waiting_for_message))
async def handle_broadcast(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    if admin_id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية للإذاعة.")
        await state.clear()
        return
    async with aiosqlite.connect(DATABASE_PATH) as db_conn:
        cursor = await db_conn.execute('SELECT user_id FROM users WHERE is_banned = 0')
        users = await cursor.fetchall()
    if not users:
        await message.answer("❌ لا يوجد مستخدمون لإرسال الرسالة إليهم.")
        await state.clear()
        return
    sent_count = 0
    failed_count = 0
    progress_msg = await message.answer(f"⏳ جاري إرسال الإذاعة...\n\n0/{len(users)}")
    for i, (user_id,) in enumerate(users, 1):
        try:
            if message.photo:
                await message.bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption or "📢 إعلان من الإدارة")
            elif message.document:
                await message.bot.send_document(user_id, message.document.file_id, caption=message.caption or "📢 إعلان من الإدارة")
            elif message.video:
                await message.bot.send_video(user_id, message.video.file_id, caption=message.caption or "📢 إعلان من الإدارة")
            else:
                await message.bot.send_message(user_id, f"📢 إعلان من الإدارة\n\n{message.text}")
            sent_count += 1
        except Exception as e:
            logger.error(f"Error sending broadcast to user {user_id}: {e}")
            failed_count += 1
        if i % 10 == 0 or i == len(users):
            await progress_msg.edit_text(f"⏳ جاري إرسال الإذاعة...\n\n✅ تم الإرسال: {sent_count}\n❌ فشل الإرسال: {failed_count}\n📊 الإجمالي: {i}/{len(users)}")
        await asyncio.sleep(0.1)
    await progress_msg.edit_text(f"✅ اكتملت الإذاعة!\n\n✅ تم الإرسال: {sent_count}\n❌ فشل الإرسال: {failed_count}\n📊 الإجمالي: {len(users)} مستخدم")
    await state.clear()

@router.callback_query(F.data == "settings")
async def settings(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية للوصول للإعدادات.")
        return
    await callback.message.edit_text(
        f"⚙️ الإعدادات\n\n1️⃣ عدد العناصر في الصفحة الواحدة: {ITEMS_PER_PAGE}\n\n"
        "🇩🇿 نظام التحقق الجزائري:\n"
        "- المستخدم يشارك رقم هاتفه\n"
        "- إذا كان الرقم جزائري (+213 أو 05/06/07) → يحصل على الكوفينغ فوراً\n"
        "- إذا كان الرقم غير جزائري → يتم حظره وطرده من القنوات\n"
        "- لا يوجد نظام طلبات أو موافقة أدمن\n\n"
        "لتعديل الإعدادات، قم بتعديل المتغيرات في أعلى الملف."
    )

# ==================== إضافة دالة confirm_delete_buttons ====================
def get_confirm_delete_buttons(file_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🗑 نعم، حذف", callback_data=f"confirm_delete_file_{file_id}"),
            InlineKeyboardButton(text="↩️ إلغاء", callback_data="cancel_delete_file")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==================== رد الأدمن على المستخدم ====================
@router.callback_query(F.data.startswith("reply_to_user_"))
async def reply_to_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = int(callback.data.split("_")[3])
    await state.update_data(user_id=user_id)
    await state.set_state(AdminReplyState.waiting_for_reply)
    await callback.message.edit_text(
        f"✉️ أرسل الآن الرسالة التي تريد إرسالها إلى المستخدم.\n\n👤 ID: {user_id}\n\nيمكنك إرسال نص أو صورة أو ملف أو فيديو.\nاضغط /cancel لإلغاء العملية."
    )

@router.message(StateFilter(AdminReplyState.waiting_for_reply))
async def handle_admin_reply_to_user(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    data = await state.get_data()
    user_id = data.get('user_id')
    if not user_id:
        await message.answer("❌ حدث خطأ، يرجى المحاولة مرة أخرى.")
        await state.clear()
        return
    if not await db.is_admin(admin_id) and admin_id != OWNER_ID:
        await message.answer("❌ ليس لديك صلاحية للتواصل مع المستخدمين.")
        await state.clear()
        return
    message_text = message.text or "رسالة غير نصية"
    message_type = 'text'
    file_id = None
    if message.photo:
        message_type = 'photo'
        file_id = message.photo[-1].file_id
        message_text = message.caption or "صورة"
    elif message.document:
        message_type = 'document'
        file_id = message.document.file_id
        message_text = message.caption or message.document.file_name
    elif message.video:
        message_type = 'video'
        file_id = message.video.file_id
        message_text = message.caption or "فيديو"
    reply_keyboard = get_reply_to_admin_button()
    caption = f"👨‍💼 رسالة من الإدارة\n\n{message_text}"
    try:
        if message_type == 'text':
            await message.bot.send_message(user_id, caption, reply_markup=reply_keyboard)
        elif message_type == 'photo':
            await message.bot.send_photo(user_id, file_id, caption=caption, reply_markup=reply_keyboard)
        elif message_type == 'document':
            await message.bot.send_document(user_id, file_id, caption=caption, reply_markup=reply_keyboard)
        elif message_type == 'video':
            await message.bot.send_video(user_id, file_id, caption=caption, reply_markup=reply_keyboard)
    except Exception as e:
        logger.error(f"Error sending admin reply: {e}")
        await message.answer(f"❌ حدث خطأ أثناء إرسال الرسالة: {e}")
        return
    await message.answer("✅ تم إرسال رسالتك للمستخدم.")
    await state.clear()

# ==================== الدالة الرئيسية ====================
async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    logger.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped with error: {e}")

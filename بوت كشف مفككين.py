import asyncio
import logging
import sqlite3
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# ==================== الإعدادات ====================
BOT_TOKEN = "8560467962:AAHvxxjOZZb5dYGSMz5EXLUaxiEJeqOX8cQ"
OWNER_ID = 8633059017
DATABASE_PATH = "coving_bot.db"
MAX_PENDING_REQUESTS = 1
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
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    delivered_file_id TEXT,
                    admin_id INTEGER,
                    processed_time TIMESTAMP,
                    rejection_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
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
                    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    delivered_to_user_id INTEGER,
                    delivered_request_id INTEGER,
                    delivered_time TIMESTAMP,
                    FOREIGN KEY (delivered_to_user_id) REFERENCES users(user_id),
                    FOREIGN KEY (delivered_request_id) REFERENCES requests(request_id)
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
    
    async def create_request(self, user_id: int, username: str, first_name: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                INSERT INTO requests (user_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
            await db.commit()
            return cursor.lastrowid
    
    async def get_pending_requests_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND status = 'pending'
            ''', (user_id,))
            row = await cursor.fetchone()
            return row[0]
    
    async def get_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM requests WHERE request_id = ?', (request_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def update_request_status(self, request_id: int, status: str, admin_id: Optional[int] = None, 
                                   delivered_file_id: Optional[str] = None, 
                                   rejection_reason: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            updates = {'status': status}
            if admin_id:
                updates['admin_id'] = admin_id
            if delivered_file_id:
                updates['delivered_file_id'] = delivered_file_id
            if rejection_reason:
                updates['rejection_reason'] = rejection_reason
            
            set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values())
            values.append(request_id)
            
            query = f"UPDATE requests SET {set_clause}, processed_time = CURRENT_TIMESTAMP WHERE request_id = ?"
            await db.execute(query, values)
            await db.commit()
    
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
    
    async def mark_file_delivered(self, file_id: int, user_id: int, request_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                UPDATE coving_files 
                SET status = 'delivered', 
                    delivered_to_user_id = ?, 
                    delivered_request_id = ?, 
                    delivered_time = CURRENT_TIMESTAMP
                WHERE file_id = ?
            ''', (user_id, request_id, file_id))
            await db.commit()
    
    async def add_coving_file(self, telegram_file_id: str, file_unique_id: str, 
                              file_name: str, mime_type: str, file_size: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                INSERT INTO coving_files (telegram_file_id, file_unique_id, file_name, mime_type, file_size)
                VALUES (?, ?, ?, ?, ?)
            ''', (telegram_file_id, file_unique_id, file_name, mime_type, file_size))
            await db.commit()
            return cursor.lastrowid
    
    async def delete_file(self, file_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM coving_files WHERE file_id = ? AND status = "available"', (file_id,))
            await db.commit()
            return True
    
    async def get_files_stats(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT COUNT(*) FROM coving_files WHERE status = "available"')
            available = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM coving_files WHERE status = "delivered"')
            delivered = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM coving_files')
            total = (await cursor.fetchone())[0]
            
            return {
                'available': available,
                'delivered': delivered,
                'total': total
            }
    
    async def get_all_files(self, offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT * FROM coving_files 
                ORDER BY upload_time DESC 
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_requests_by_status(self, status: str, offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT * FROM requests 
                WHERE status = ? 
                ORDER BY request_time DESC 
                LIMIT ? OFFSET ?
            ''', (status, limit, offset))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_all_requests(self, offset: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT * FROM requests 
                ORDER BY request_time DESC 
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_requests_count_by_status(self, status: Optional[str] = None) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            if status:
                cursor = await db.execute('SELECT COUNT(*) FROM requests WHERE status = ?', (status,))
            else:
                cursor = await db.execute('SELECT COUNT(*) FROM requests')
            row = await cursor.fetchone()
            return row[0]
    
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
    
    async def toggle_channel_active(self, channel_id: int, active: bool):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE required_channels SET is_active = ? WHERE channel_id = ?', (active, channel_id))
            await db.commit()
    
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
            
            pending_requests = await self.get_requests_count_by_status('pending')
            approved_requests = await self.get_requests_count_by_status('approved')
            rejected_requests = await self.get_requests_count_by_status('rejected')
            total_requests = await self.get_requests_count_by_status()
            
            files_stats = await self.get_files_stats()
            
            return {
                'total_users': total_users,
                'banned_users': banned_users,
                'active_users': active_users,
                'pending_requests': pending_requests,
                'approved_requests': approved_requests,
                'rejected_requests': rejected_requests,
                'total_requests': total_requests,
                'available_files': files_stats['available'],
                'delivered_files': files_stats['delivered'],
                'total_files': files_stats['total']
            }

db = Database()

# ==================== الحالات (States) ====================
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
        [InlineKeyboardButton(text="📋 حالة طلبي", callback_data="my_requests")],
        [InlineKeyboardButton(text="📞 التواصل مع الإدارة", callback_data="contact_admin")],
        [InlineKeyboardButton(text="📢 القنوات المطلوبة", callback_data="required_channels")],
        [InlineKeyboardButton(text="ℹ️ طريقة الاستخدام", callback_data="how_to_use")]
    ]
    
    if is_admin or is_owner:
        keyboard.append([InlineKeyboardButton(text="👑 لوحة المالك", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_panel(is_owner: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📁 إدارة الكوفينغات", callback_data="manage_files")],
        [InlineKeyboardButton(text="📨 إدارة الطلبات", callback_data="manage_requests")],
        [InlineKeyboardButton(text="📢 الاشتراك الإجباري", callback_data="manage_channels")],
        [InlineKeyboardButton(text="👥 إدارة المستخدمين", callback_data="manage_users")]
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

def get_requests_management_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="⏳ الطلبات المعلقة", callback_data="requests_pending")],
        [InlineKeyboardButton(text="✅ الطلبات المقبولة", callback_data="requests_approved")],
        [InlineKeyboardButton(text="❌ الطلبات المرفوضة", callback_data="requests_rejected")],
        [InlineKeyboardButton(text="📋 جميع الطلبات", callback_data="requests_all")],
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

def get_request_action_buttons(request_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="✅ قبول الطلب", callback_data=f"approve_request_{request_id}"),
            InlineKeyboardButton(text="❌ رفض الطلب", callback_data=f"reject_request_{request_id}")
        ],
        [InlineKeyboardButton(text="💬 تواصل مع المستخدم", callback_data=f"reply_user_{request_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_confirm_reject_buttons(request_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="❌ نعم، رفض الطلب", callback_data=f"confirm_reject_{request_id}"),
            InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"cancel_reject_{request_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_confirm_delete_buttons(file_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🗑 نعم، حذف", callback_data=f"confirm_delete_file_{file_id}"),
            InlineKeyboardButton(text="↩️ إلغاء", callback_data="cancel_delete_file")
        ]
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

def get_pagination_buttons(current_page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup:
    keyboard = []
    nav_buttons = []
    
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"{prefix}_page_{current_page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"{prefix}_page_{current_page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==================== الرواتر الرئيسي ====================
router = Router()

# ==================== دوال مساعدة ====================
async def check_subscriptions(bot, user_id: int, channels: list) -> list:
    not_subscribed = []
    for channel in channels:
        try:
            chat_member = await bot.get_chat_member(channel['channel_id'], user_id)
            if chat_member.status in ['left', 'kicked']:
                not_subscribed.append(channel)
        except Exception as e:
            logger.error(f"Error checking subscription for channel {channel['channel_id']}: {e}")
            not_subscribed.append(channel)
    return not_subscribed

async def show_main_menu(message: types.Message, user_id: int):
    is_admin = await db.is_admin(user_id)
    is_owner = user_id == OWNER_ID
    keyboard = get_main_menu(is_admin, is_owner)
    
    try:
        await message.edit_text(
            "👋 القائمة الرئيسية:\n\n"
            "اختر من الخيارات أدناه:",
            reply_markup=keyboard
        )
    except:
        await message.answer(
            "👋 القائمة الرئيسية:\n\n"
            "اختر من الخيارات أدناه:",
            reply_markup=keyboard
        )

async def show_admin_panel(message: types.Message, user_id: int):
    is_owner = user_id == OWNER_ID
    keyboard = get_admin_panel(is_owner)
    
    try:
        await message.edit_text(
            "👑 لوحة المالك\n\n"
            "اختر من الخيارات أدناه:",
            reply_markup=keyboard
        )
    except:
        await message.answer(
            "👑 لوحة المالك\n\n"
            "اختر من الخيارات أدناه:",
            reply_markup=keyboard
        )

async def send_to_admin(bot, user_id: int, username: str, first_name: str, 
                        message_text: str, message_type: str, file_id: str = None):
    admin_message = (
        f"📩 رد جديد من المستخدم\n\n"
        f"👤 @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📛 الاسم: {first_name}\n\n"
        f"💬 الرسالة:\n{message_text}"
    )
    
    reply_keyboard = get_reply_to_user_button(user_id)
    
    try:
        if message_type == 'text':
            await bot.send_message(OWNER_ID, admin_message, reply_markup=reply_keyboard)
        elif message_type == 'photo':
            await bot.send_photo(OWNER_ID, file_id, caption=admin_message, reply_markup=reply_keyboard)
        elif message_type == 'document':
            await bot.send_document(OWNER_ID, file_id, caption=admin_message, reply_markup=reply_keyboard)
        elif message_type == 'video':
            await bot.send_video(OWNER_ID, file_id, caption=admin_message, reply_markup=reply_keyboard)
    except Exception as e:
        logger.error(f"Error sending message to admin: {e}")

async def update_admin_request_message(bot, message, request_id: int, status: str, admin_id: int):
    request = await db.get_request(request_id)
    if not request:
        return
    
    status_map = {
        'approved': '✅ تمت الموافقة على الطلب',
        'rejected': '❌ تم رفض الطلب'
    }
    
    username = request['username'] or 'لا يوجد'
    processed_time = datetime.now().strftime('%d/%m/%Y %H:%M')
    
    text = (
        f"{status_map.get(status, status)}\n\n"
        f"👤 @{username}\n"
        f"🆔 ID: {request['user_id']}\n"
        f"🔢 الطلب: #{request_id}\n"
        f"📦 الملف: {'تم التسليم' if status == 'approved' else 'مرفوض'}\n"
        f"🕐 وقت المعالجة: {processed_time}"
    )
    
    try:
        await message.edit_text(text)
    except:
        pass

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
                f"📢 يجب عليك الاشتراك في القنوات التالية أولًا:\n\n"
                f"{channels_text}\n\n"
                "بعد الاشتراك اضغط:\n"
                "🔄 تحقق من الاشتراك",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            return
    
    is_admin = await db.is_admin(user_id)
    is_owner = user_id == OWNER_ID
    keyboard = get_main_menu(is_admin, is_owner)
    
    await message.answer(
        f"👋 أهلاً بك {first_name}!\n\n"
        "مرحبًا بك في بوت كوفينغ.\n"
        "يمكنك طلب ملفات الكوفينغ بسهولة من خلال القائمة أدناه.",
        reply_markup=keyboard
    )

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ لا توجد عملية نشطة لإلغائها.")
        return
    
    await state.clear()
    await message.answer("✅ تم إلغاء العملية.")
    
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
            f"❌ لا تزال غير مشترك في القنوات التالية:\n\n"
            f"{channels_text}\n\n"
            "بعد الاشتراك اضغط:\n"
            "🔄 تحقق من الاشتراك",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        await callback.message.edit_text("✅ تم التحقق من اشتراكك في جميع القنوات.")
        await show_main_menu(callback.message, user_id)

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.answer()
    await show_main_menu(callback.message, callback.from_user.id)

@router.callback_query(F.data == "request_coving")
async def request_coving(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name
    
    if await db.is_user_banned(user_id):
        await callback.message.edit_text("🚫 عذرًا، تم حظرك من استخدام هذا البوت.")
        return
    
    if not username:
        await callback.message.edit_text(
            "❌ عذرًا، لا يمكنك استخدام البوت لأن حسابك مجهول.\n\n"
            "👤 يجب عليك إضافة Username إلى حسابك في Telegram ثم العودة إلى البوت والمحاولة مرة أخرى."
        )
        return
    
    channels = await db.get_required_channels(active_only=True)
    if channels:
        not_subscribed = await check_subscriptions(callback.bot, user_id, channels)
        if not_subscribed:
            channels_text = "\n".join([f"{i+1}️⃣ {ch['title']} (@{ch['username']})" for i, ch in enumerate(not_subscribed)])
            keyboard = get_check_subscription_button()
            await callback.message.edit_text(
                f"📢 يجب عليك الاشتراك في القنوات التالية أولًا:\n\n"
                f"{channels_text}\n\n"
                "بعد الاشتراك اضغط:\n"
                "🔄 تحقق من الاشتراك",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            return
    
    pending_count = await db.get_pending_requests_count(user_id)
    if pending_count >= MAX_PENDING_REQUESTS:
        requests = await db.get_requests_by_status('pending', 0, 1)
        if requests:
            request = requests[0]
            await callback.message.edit_text(
                f"⏳ لديك طلب قيد المراجعة بالفعل.\n\n"
                f"🆔 رقم الطلب: #{request['request_id']}\n\n"
                "يرجى انتظار معالجة طلبك."
            )
        else:
            await callback.message.edit_text(
                "⏳ لديك طلب قيد المراجعة بالفعل.\n\n"
                "يرجى انتظار معالجة طلبك."
            )
        return
    
    request_id = await db.create_request(user_id, username, first_name)
    
    await callback.message.edit_text(
        f"✅ تم إرسال طلبك بنجاح.\n\n"
        f"🆔 رقم الطلب: #{request_id}\n\n"
        f"⏳ طلبك الآن قيد المراجعة من الإدارة.\n\n"
        "سيتم إعلامك بالنتيجة عند معالجة الطلب."
    )
    
    request_data = await db.get_request(request_id)
    await notify_owner(callback.bot, request_data)

async def notify_owner(bot, request_data: dict):
    user_id = request_data['user_id']
    username = request_data['username'] or 'لا يوجد'
    first_name = request_data['first_name']
    request_id = request_data['request_id']
    request_time = request_data['request_time']
    
    try:
        dt = datetime.strptime(request_time, '%Y-%m-%d %H:%M:%S')
        request_time_formatted = dt.strftime('%d/%m/%Y %H:%M')
    except:
        request_time_formatted = request_time
    
    message_text = (
        f"🔔 طلب كوفينغ جديد\n\n"
        f"👤 المستخدم: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📛 الاسم: {first_name}\n"
        f"🕐 وقت الطلب: {request_time_formatted}\n"
        f"🔢 رقم الطلب: #{request_id}\n"
        f"📌 الحالة: ⏳ قيد المراجعة"
    )
    
    keyboard = get_request_action_buttons(request_id)
    
    try:
        await bot.send_message(OWNER_ID, message_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error notifying owner: {e}")

@router.callback_query(F.data == "my_requests")
async def my_requests(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DATABASE_PATH) as db_conn:
        db_conn.row_factory = aiosqlite.Row
        cursor = await db_conn.execute('''
            SELECT * FROM requests 
            WHERE user_id = ? 
            ORDER BY request_time DESC 
            LIMIT 10
        ''', (user_id,))
        requests = await cursor.fetchall()
    
    if not requests:
        await callback.message.edit_text(
            "📋 ليس لديك أي طلبات سابقة.\n\n"
            "لطلب كوفينغ، استخدم الزر 📥 طلب كوفينغ."
        )
        return
    
    status_map = {
        'pending': '⏳ قيد المراجعة',
        'approved': '✅ تمت الموافقة',
        'rejected': '❌ مرفوض'
    }
    
    requests_text = "📋 طلباتي:\n\n"
    for req in requests[:5]:
        status = status_map.get(req['status'], req['status'])
        requests_text += f"🆔 #{req['request_id']} - {status}\n"
        requests_text += f"🕐 {req['request_time']}\n\n"
    
    if len(requests) > 5:
        requests_text += f"📊 إجمالي الطلبات: {len(requests)}\n"
        requests_text += "عرض آخر 5 طلبات فقط"
    
    keyboard = get_back_button()
    await callback.message.edit_text(requests_text, reply_markup=keyboard)

@router.callback_query(F.data == "contact_admin")
async def contact_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    if await db.is_user_banned(user_id):
        await callback.message.edit_text("🚫 عذرًا، تم حظرك من استخدام هذا البوت.")
        return
    
    await callback.message.edit_text(
        "✉️ يمكنك التواصل مع الإدارة من خلال الضغط على الزر أدناه.\n\n"
        "سيتم إرسال رسالتك إلى المشرفين.",
        reply_markup=get_reply_to_admin_button()
    )

@router.callback_query(F.data == "reply_to_admin")
async def reply_to_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserReplyState.waiting_for_reply)
    await callback.message.edit_text(
        "✉️ اكتب رسالتك وسيتم إرسالها إلى الإدارة.\n\n"
        "يمكنك إرسال نص، صورة، ملف، أو فيديو.\n"
        "اضغط /cancel لإلغاء العملية."
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
    
    await send_to_admin(message.bot, user_id, username, first_name, message_text, message_type, file_id)
    
    await message.answer("✅ تم إرسال رسالتك إلى الإدارة.")
    await state.clear()

@router.callback_query(F.data == "required_channels")
async def show_required_channels(callback: CallbackQuery):
    await callback.answer()
    
    channels = await db.get_required_channels(active_only=True)
    
    if not channels:
        await callback.message.edit_text(
            "📢 لا توجد قنوات مطلوبة حالياً.\n\n"
            "يمكنك استخدام البوت مباشرة."
        )
        return
    
    channels_text = "📢 القنوات المطلوبة للاشتراك:\n\n"
    for i, channel in enumerate(channels, 1):
        channels_text += f"{i}️⃣ {channel['title']}\n"
        channels_text += f"   @{channel['username']}\n\n"
    
    channels_text += "يرجى الاشتراك في جميع القنوات أعلاه للاستفادة من خدمات البوت."
    
    keyboard = get_check_subscription_button()
    await callback.message.edit_text(channels_text, reply_markup=keyboard)

@router.callback_query(F.data == "how_to_use")
async def how_to_use(callback: CallbackQuery):
    await callback.answer()
    
    text = (
        "ℹ️ طريقة استخدام البوت:\n\n"
        "1️⃣ اضغط على 📥 طلب كوفينغ لإنشاء طلب جديد.\n"
        "2️⃣ انتظر معالجة طلبك من قبل الإدارة.\n"
        "3️⃣ ستتلقى إشعارًا عند الموافقة على طلبك.\n"
        "4️⃣ يمكنك متابعة حالة طلبك من خلال 📋 حالة طلبي.\n"
        "5️⃣ للتواصل مع الإدارة استخدم 📞 التواصل مع الإدارة.\n\n"
        "📌 ملاحظات:\n"
        "- يجب أن يكون لديك اسم مستخدم (Username) لاستخدام البوت.\n"
        "- يجب الاشتراك في القنوات المطلوبة.\n"
        "- لا يمكنك تقديم أكثر من طلب واحد في نفس الوقت.\n"
        "- سيتم التواصل معك عبر البوت في حال كان هناك أي استفسار."
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

# ==================== إدارة الكوفينغات ====================
@router.callback_query(F.data == "manage_files")
async def manage_files(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_files_management_menu()
    await callback.message.edit_text(
        "📁 إدارة الكوفينغات\n\n"
        "اختر من الخيارات أدناه:",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "add_coving_file")
async def add_coving_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddFileState.waiting_for_file)
    await callback.message.edit_text(
        "📤 أرسل ملف الكوفينغ الآن.\n\n"
        "يمكنك إرسال ملف من نوع PDF, DOC, DOCX, أو أي ملف مناسب.\n"
        "اضغط /cancel لإلغاء العملية."
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
        telegram_file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        file_name=document.file_name or "unknown",
        mime_type=document.mime_type or "unknown",
        file_size=document.file_size
    )
    
    await message.answer(
        f"✅ تمت إضافة الكوفينغ بنجاح إلى المخزن.\n\n"
        f"📄 اسم الملف: {document.file_name}\n"
        f"📊 الحجم: {document.file_size / 1024:.2f} كيلوبايت\n"
        f"🆔 رقم الملف: #{file_id}"
    )
    
    await state.clear()

@router.message(StateFilter(AddFileState.waiting_for_file))
async def invalid_file_upload(message: Message, state: FSMContext):
    await message.answer(
        "❌ الرجاء إرسال ملف صحيح.\n\n"
        "اضغط /cancel لإلغاء العملية."
    )

@router.callback_query(F.data == "view_stock")
async def view_stock(callback: CallbackQuery):
    await callback.answer()
    
    stats = await db.get_files_stats()
    files = await db.get_all_files(0, 10)
    
    text = f"📦 مخزون الكوفينغات\n\n"
    text += f"🟢 المتوفر: {stats['available']}\n"
    text += f"📤 تم التسليم: {stats['delivered']}\n"
    text += f"📊 الإجمالي: {stats['total']}\n\n"
    
    if files:
        text += "📋 أحدث الملفات:\n"
        for file in files[:5]:
            status_emoji = "🟢" if file['status'] == 'available' else "📤"
            text += f"{status_emoji} {file['file_name']} (#{file['file_id']})\n"
    
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data == "delete_coving_file")
async def delete_coving_file_start(callback: CallbackQuery):
    await callback.answer()
    
    files = await db.get_all_files(0, 20)
    available_files = [f for f in files if f['status'] == 'available']
    
    if not available_files:
        await callback.message.edit_text(
            "📭 لا توجد ملفات متوفرة للحذف.\n\n"
            "قم بإضافة ملفات جديدة أولاً.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for file in available_files[:10]:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 {file['file_name']} (#{file['file_id']})",
                callback_data=f"delete_file_{file['file_id']}"
            )
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    
    await callback.message.edit_text(
        "🗑 اختر الملف الذي تريد حذفه:\n\n"
        "⚠️ سيتم حذف الملف نهائياً.",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("delete_file_"))
async def delete_file_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    file_id = int(callback.data.split("_")[2])
    file_data = await db.get_file(file_id)
    
    if not file_data:
        await callback.message.edit_text(
            "❌ الملف غير موجود.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    await state.update_data(file_id=file_id)
    
    keyboard = get_confirm_delete_buttons(file_id)
    await callback.message.edit_text(
        f"⚠️ هل أنت متأكد من حذف الملف التالي؟\n\n"
        f"📄 اسم الملف: {file_data['file_name']}\n"
        f"🆔 رقم الملف: #{file_data['file_id']}\n\n"
        "لا يمكن التراجع عن هذا الإجراء.",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("confirm_delete_file_"))
async def confirm_delete_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    file_id = int(callback.data.split("_")[3])
    
    await db.delete_file(file_id)
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ تم حذف الملف #{file_id} بنجاح.",
        reply_markup=get_back_button(callback_data="back_to_admin")
    )

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
    
    text = f"📊 إحصائيات الملفات\n\n"
    text += f"🟢 المتوفرة: {stats['available']}\n"
    text += f"📤 المسلمة: {stats['delivered']}\n"
    text += f"📊 الإجمالي: {stats['total']}"
    
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

# ==================== إدارة الطلبات ====================
@router.callback_query(F.data == "manage_requests")
async def manage_requests(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_requests_management_menu()
    await callback.message.edit_text(
        "📨 إدارة الطلبات\n\n"
        "اختر من الخيارات أدناه:",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("requests_"))
async def show_requests_by_status(callback: CallbackQuery):
    await callback.answer()
    
    status_map = {
        'pending': '⏳ المعلقة',
        'approved': '✅ المقبولة',
        'rejected': '❌ المرفوضة',
        'all': 'جميع الطلبات'
    }
    
    parts = callback.data.split("_")
    status = parts[1]
    page = 1
    
    if "_page_" in callback.data:
        parts = callback.data.split("_page_")
        status = parts[0].split("_")[1]
        page = int(parts[1])
    
    offset = (page - 1) * ITEMS_PER_PAGE
    
    if status == 'all':
        requests = await db.get_all_requests(offset, ITEMS_PER_PAGE)
        total = await db.get_requests_count_by_status()
    else:
        requests = await db.get_requests_by_status(status, offset, ITEMS_PER_PAGE)
        total = await db.get_requests_count_by_status(status)
    
    if not requests:
        await callback.message.edit_text(
            f"📋 لا توجد {status_map.get(status, status)} حالياً.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    text = f"📋 {status_map.get(status, status)}:\n\n"
    for req in requests:
        username = req['username'] or 'مجهول'
        text += f"🔢 #{req['request_id']} - @{username} - {req['request_time'][:16]}\n"
        text += f"   📌 حالة: {status_map.get(req['status'], req['status'])}\n\n"
    
    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"requests_{status}_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"requests_{status}_page_{page+1}"))
    if nav_buttons:
        keyboard.inline_keyboard.append(nav_buttons)
    
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("approve_request_"))
async def approve_request(callback: CallbackQuery):
    await callback.answer()
    
    request_id = int(callback.data.split("_")[2])
    admin_id = callback.from_user.id
    
    if not await db.is_admin(admin_id) and admin_id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لقبول الطلبات.")
        return
    
    request = await db.get_request(request_id)
    if not request:
        await callback.message.edit_text("❌ الطلب غير موجود.")
        return
    
    if request['status'] != 'pending':
        await callback.message.edit_text("⚠️ هذا الطلب تمت معالجته مسبقًا.")
        return
    
    available_file = await db.get_available_file()
    if not available_file:
        await callback.message.edit_text(
            "⚠️ لا توجد ملفات كوفينغ متوفرة حاليًا.\n\n"
            "قم بإضافة ملفات جديدة إلى المخزن ثم أعد معالجة الطلب."
        )
        return
    
    await db.update_request_status(
        request_id=request_id,
        status='approved',
        admin_id=admin_id,
        delivered_file_id=available_file['telegram_file_id']
    )
    
    await db.mark_file_delivered(
        file_id=available_file['file_id'],
        user_id=request['user_id'],
        request_id=request_id
    )
    
    try:
        await callback.bot.send_document(
            request['user_id'],
            available_file['telegram_file_id'],
            caption=f"✅ تمت الموافقة على طلبك\n\n"
                    f"🆔 رقم الطلب: #{request_id}\n\n"
                    f"📦 تم إرسال الكوفينغ الخاص بك في الرسالة التالية."
        )
    except Exception as e:
        logger.error(f"Error sending file to user {request['user_id']}: {e}")
    
    await update_admin_request_message(callback.bot, callback.message, request_id, 'approved', admin_id)
    
    await callback.message.edit_text(
        f"✅ تمت الموافقة على الطلب #{request_id} بنجاح.",
        reply_markup=get_back_button(callback_data="back_to_admin")
    )

@router.callback_query(F.data.startswith("reject_request_"))
async def reject_request_confirm(callback: CallbackQuery):
    await callback.answer()
    
    request_id = int(callback.data.split("_")[2])
    
    keyboard = get_confirm_reject_buttons(request_id)
    await callback.message.edit_text(
        f"❌ هل أنت متأكد من رفض الطلب #{request_id}؟",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("confirm_reject_"))
async def confirm_reject_request(callback: CallbackQuery):
    await callback.answer()
    
    request_id = int(callback.data.split("_")[2])
    admin_id = callback.from_user.id
    
    if not await db.is_admin(admin_id) and admin_id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لرفض الطلبات.")
        return
    
    request = await db.get_request(request_id)
    if not request:
        await callback.message.edit_text("❌ الطلب غير موجود.")
        return
    
    if request['status'] != 'pending':
        await callback.message.edit_text("⚠️ هذا الطلب تمت معالجته مسبقًا.")
        return
    
    await db.update_request_status(
        request_id=request_id,
        status='rejected',
        admin_id=admin_id,
        rejection_reason="لم يتم تقديم سبب"
    )
    
    try:
        await callback.bot.send_message(
            request['user_id'],
            f"❌ تم رفض طلبك\n\n"
            f"🆔 رقم الطلب: #{request_id}\n\n"
            f"للأسف لم تتم الموافقة على طلبك.\n\n"
            f"إذا كان لديك استفسار يمكنك التواصل مع الإدارة."
        )
    except Exception as e:
        logger.error(f"Error sending rejection notification to user {request['user_id']}: {e}")
    
    await update_admin_request_message(callback.bot, callback.message, request_id, 'rejected', admin_id)

@router.callback_query(F.data.startswith("cancel_reject_"))
async def cancel_reject_request(callback: CallbackQuery):
    await callback.answer()
    
    request_id = int(callback.data.split("_")[2])
    
    keyboard = get_request_action_buttons(request_id)
    await callback.message.edit_text(
        "❌ تم إلغاء عملية الرفض.",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("reply_user_"))
async def reply_to_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    request_id = int(callback.data.split("_")[2])
    request = await db.get_request(request_id)
    
    if not request:
        await callback.message.edit_text("❌ الطلب غير موجود.")
        return
    
    await state.update_data(user_id=request['user_id'], request_id=request_id)
    await state.set_state(AdminReplyState.waiting_for_reply)
    
    await callback.message.edit_text(
        f"✉️ أرسل الآن الرسالة التي تريد إرسالها إلى المستخدم.\n\n"
        f"👤 المستخدم: @{request['username'] or 'مجهول'}\n"
        f"🆔 رقم الطلب: #{request_id}\n\n"
        "يمكنك إرسال نص أو صورة أو ملف أو فيديو.\n"
        "اضغط /cancel لإلغاء العملية."
    )

@router.message(StateFilter(AdminReplyState.waiting_for_reply))
async def handle_admin_reply_to_user(message: Message, state: FSMContext):
    admin_id = message.from_user.id
    data = await state.get_data()
    user_id = data.get('user_id')
    request_id = data.get('request_id')
    
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
        logger.error(f"Error sending admin reply to user {user_id}: {e}")
        await message.answer(f"❌ حدث خطأ أثناء إرسال الرسالة: {e}")
        return
    
    await message.answer("✅ تم إرسال رسالتك للمستخدم.")
    await state.clear()

# ==================== إدارة القنوات ====================
@router.callback_query(F.data == "manage_channels")
async def manage_channels(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_channels_management_menu()
    await callback.message.edit_text(
        "📢 إدارة الاشتراك الإجباري\n\n"
        "اختر من الخيارات أدناه:",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "add_channel")
async def add_channel_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddChannelState.waiting_for_channel)
    await callback.message.edit_text(
        "📢 أرسل معرف القناة أو رابطها.\n\n"
        "مثال:\n"
        "- معرف القناة: -1001234567890\n"
        "- رابط القناة: https://t.me/your_channel\n\n"
        "اضغط /cancel لإلغاء العملية."
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
            f"✅ تمت إضافة القناة بنجاح.\n\n"
            f"📢 العنوان: {title}\n"
            f"🆔 المعرف: {channel_id}\n"
            f"👤 يوزرنيم: @{username or 'لا يوجد'}"
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
        await callback.message.edit_text(
            "📋 لا توجد قنوات مطلوبة حالياً.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    text = "📋 القنوات المطلوبة:\n\n"
    for i, channel in enumerate(channels, 1):
        status = "🟢" if channel['is_active'] else "🔴"
        text += f"{status} {channel['title']}\n"
        text += f"   🆔 {channel['channel_id']}\n"
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
        await callback.message.edit_text(
            "📋 لا توجد قنوات لحذفها.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for channel in channels[:10]:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 {channel['title']}",
                callback_data=f"delete_channel_{channel['channel_id']}"
            )
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    
    await callback.message.edit_text(
        "🗑 اختر القناة التي تريد حذفها:",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("delete_channel_"))
async def delete_channel(callback: CallbackQuery):
    await callback.answer()
    
    channel_id = int(callback.data.split("_")[2])
    
    await db.remove_required_channel(channel_id)
    
    await callback.message.edit_text(
        f"✅ تم حذف القناة بنجاح.",
        reply_markup=get_back_button(callback_data="back_to_admin")
    )

# ==================== إدارة المستخدمين ====================
@router.callback_query(F.data == "manage_users")
async def manage_users(callback: CallbackQuery):
    await callback.answer()
    keyboard = get_users_management_menu()
    await callback.message.edit_text(
        "👥 إدارة المستخدمين\n\n"
        "اختر من الخيارات أدناه:",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "user_count")
async def user_count(callback: CallbackQuery):
    await callback.answer()
    
    stats = await db.get_stats()
    admins = await db.get_admins()
    
    text = f"📊 إحصائيات المستخدمين\n\n"
    text += f"👥 إجمالي المستخدمين: {stats['total_users']}\n"
    text += f"🟢 المستخدمون النشطون: {stats['active_users']}\n"
    text += f"🚫 المحظورون: {stats['banned_users']}\n"
    text += f"👮 الأدمن: {len(admins)}"
    
    keyboard = get_back_button(callback_data="back_to_admin")
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data == "ban_user")
async def ban_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BanUserState.waiting_for_user_id)
    await callback.message.edit_text(
        "🚫 أرسل معرف المستخدم (User ID) الذي تريد حظره.\n\n"
        "يمكنك الحصول على معرف المستخدم من معلومات الطلب.\n"
        "اضغط /cancel لإلغاء العملية."
    )

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
        await message.answer(f"✅ تم حظر المستخدم {user_id} بنجاح.")
        
    except ValueError:
        await message.answer("❌ الرجاء إدخال معرف مستخدم صحيح (أرقام فقط).")
    
    await state.clear()

@router.callback_query(F.data == "unban_user")
async def unban_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UnbanUserState.waiting_for_user_id)
    await callback.message.edit_text(
        "✅ أرسل معرف المستخدم (User ID) الذي تريد فك حظره.\n\n"
        "اضغط /cancel لإلغاء العملية."
    )

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
        await message.answer(f"✅ تم فك حظر المستخدم {user_id} بنجاح.")
    except ValueError:
        await message.answer("❌ الرجاء إدخال معرف مستخدم صحيح (أرقام فقط).")
    
    await state.clear()

@router.callback_query(F.data == "search_user")
async def search_user_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SearchUserState.waiting_for_query)
    await callback.message.edit_text(
        "🔎 أرسل معرف المستخدم أو اسم المستخدم للبحث.\n\n"
        "مثال:\n"
        "- معرف: 123456789\n"
        "- يوزرنيم: @username\n\n"
        "اضغط /cancel لإلغاء العملية."
    )

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
                cursor = await db_conn.execute(
                    'SELECT * FROM users WHERE username = ?',
                    (username,)
                )
                user_data = await cursor.fetchone()
        
        if not user_data:
            await message.answer("❌ لم يتم العثور على المستخدم.")
            await state.clear()
            return
        
        text = f"👤 معلومات المستخدم:\n\n"
        text += f"🆔 ID: {user_data['user_id']}\n"
        text += f"👤 يوزرنيم: @{user_data['username'] or 'لا يوجد'}\n"
        text += f"📛 الاسم: {user_data['first_name']}"
        if user_data['last_name']:
            text += f" {user_data['last_name']}"
        text += f"\n📌 الحالة: {'🚫 محظور' if user_data['is_banned'] else '🟢 نشط'}\n"
        text += f"📅 تاريخ التسجيل: {user_data['registered_at']}\n"
        text += f"🕐 آخر نشاط: {user_data['last_activity']}"
        
        async with aiosqlite.connect(DATABASE_PATH) as db_conn:
            cursor = await db_conn.execute(
                'SELECT COUNT(*) FROM requests WHERE user_id = ?',
                (user_data['user_id'],)
            )
            requests_count = (await cursor.fetchone())[0]
        text += f"\n📨 عدد الطلبات: {requests_count}"
        
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
    await callback.message.edit_text(
        "👮 إدارة الأدمن\n\n"
        "اختر من الخيارات أدناه:",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لإضافة أدمن.")
        return
    
    await state.set_state(AddAdminState.waiting_for_admin_id)
    await callback.message.edit_text(
        "➕ أرسل معرف المستخدم (User ID) الذي تريد إضافته كأدمن.\n\n"
        "اضغط /cancel لإلغاء العملية."
    )

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
        await callback.message.edit_text(
            "📋 لا يوجد أدمن لحذفهم.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for admin_id in admins[:10]:
        user = await db.get_user(admin_id)
        name = user['first_name'] if user else str(admin_id)
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 {name} ({admin_id})",
                callback_data=f"remove_admin_{admin_id}"
            )
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="back_to_admin")])
    
    await callback.message.edit_text(
        "🗑 اختر الأدمن الذي تريد حذفه:",
        reply_markup=keyboard
    )

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
    
    await callback.message.edit_text(
        f"✅ تم حذف الأدمن {admin_id} بنجاح.",
        reply_markup=get_back_button(callback_data="back_to_admin")
    )

@router.callback_query(F.data == "list_admins")
async def list_admins(callback: CallbackQuery):
    await callback.answer()
    
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية لعرض قائمة الأدمن.")
        return
    
    admins = await db.get_admins()
    
    if not admins:
        await callback.message.edit_text(
            "📋 لا يوجد أدمن.",
            reply_markup=get_back_button(callback_data="back_to_admin")
        )
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
    
    text = f"📊 إحصائيات البوت\n\n"
    text += f"👥 إجمالي المستخدمين: {stats['total_users']}\n"
    text += f"🟢 المستخدمون النشطون: {stats['active_users']}\n"
    text += f"🚫 المحظورون: {stats['banned_users']}\n\n"
    text += f"📨 إجمالي الطلبات: {stats['total_requests']}\n"
    text += f"⏳ الطلبات المعلقة: {stats['pending_requests']}\n"
    text += f"✅ الطلبات المقبولة: {stats['approved_requests']}\n"
    text += f"❌ الطلبات المرفوضة: {stats['rejected_requests']}\n\n"
    text += f"📦 الملفات المتوفرة: {stats['available_files']}\n"
    text += f"📤 الملفات المسلمة: {stats['delivered_files']}\n"
    text += f"📊 إجمالي الملفات: {stats['total_files']}"
    
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
        "📢 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين.\n\n"
        "يمكنك إرسال نص، صورة، ملف، أو فيديو.\n"
        "سيتم إرسالها لجميع المستخدمين المسجلين.\n\n"
        "⚠️ تحذير: قد تستغرق العملية بعض الوقت.\n"
        "اضغط /cancel لإلغاء العملية."
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
                await message.bot.send_photo(
                    user_id,
                    message.photo[-1].file_id,
                    caption=message.caption or "📢 إعلان من الإدارة"
                )
            elif message.document:
                await message.bot.send_document(
                    user_id,
                    message.document.file_id,
                    caption=message.caption or "📢 إعلان من الإدارة"
                )
            elif message.video:
                await message.bot.send_video(
                    user_id,
                    message.video.file_id,
                    caption=message.caption or "📢 إعلان من الإدارة"
                )
            else:
                await message.bot.send_message(
                    user_id,
                    f"📢 إعلان من الإدارة\n\n{message.text}"
                )
            sent_count += 1
        except Exception as e:
            logger.error(f"Error sending broadcast to user {user_id}: {e}")
            failed_count += 1
        
        if i % 10 == 0 or i == len(users):
            await progress_msg.edit_text(
                f"⏳ جاري إرسال الإذاعة...\n\n"
                f"✅ تم الإرسال: {sent_count}\n"
                f"❌ فشل الإرسال: {failed_count}\n"
                f"📊 الإجمالي: {i}/{len(users)}"
            )
        
        await asyncio.sleep(0.1)
    
    await progress_msg.edit_text(
        f"✅ اكتملت الإذاعة!\n\n"
        f"✅ تم الإرسال: {sent_count}\n"
        f"❌ فشل الإرسال: {failed_count}\n"
        f"📊 الإجمالي: {len(users)} مستخدم"
    )
    
    await state.clear()

@router.callback_query(F.data == "settings")
async def settings(callback: CallbackQuery):
    await callback.answer()
    
    if callback.from_user.id != OWNER_ID:
        await callback.message.edit_text("❌ ليس لديك صلاحية للوصول للإعدادات.")
        return
    
    await callback.message.edit_text(
        "⚙️ الإعدادات\n\n"
        f"1️⃣ الحد الأقصى للطلبات المعلقة للمستخدم: {MAX_PENDING_REQUESTS}\n"
        f"2️⃣ عدد العناصر في الصفحة الواحدة: {ITEMS_PER_PAGE}\n\n"
        "لتعديل الإعدادات، قم بتعديل المتغيرات في أعلى الملف."
    )

# ==================== الدالة الرئيسية ====================
async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
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
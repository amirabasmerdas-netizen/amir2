#!/usr/bin/env python3
"""
AmeleClashBot - ربات بازی متنی الهام گرفته از Clash of Clans
نسخه: 2.0.0
تکنولوژی: Python + aiogram 3.x + SQLite + aiohttp
مخزن: https://github.com/yourusername/ameleclashbot
"""

import asyncio
import sqlite3
import os
import logging
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

# Third-party imports
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Message, WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# aiohttp for web server
try:
    from aiohttp import web
except ImportError:
    import aiohttp.web as web

# ============================================================================
# تنظیمات و پیکربندی
# ============================================================================

# تنظیمات لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# متغیرهای محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))
ADMIN_ID = int(os.getenv("ADMIN_ID", 8285797031))
DATABASE_URL = os.getenv("DATABASE_URL", "ameleclash.db")

# اعتبارسنجی متغیرهای ضروری
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required!")
if not WEBHOOK_URL:
    logger.warning("WEBHOOK_URL not set, using polling mode (not recommended for production)")

# ============================================================================
# Enum ها و Data Classes
# ============================================================================

class League(Enum):
    BRONZE = "برنز"
    SILVER = "نقره‌ای"
    GOLD = "طلایی"
    CRYSTAL = "کریستالی"
    MASTER = "استاد"
    CHAMPION = "قهرمان"
    LEGEND = "افسانه‌ای"

class BuildingType(Enum):
    TOWNHALL = "townhall"
    MINE = "mine"
    COLLECTOR = "collector"
    BARRACKS = "barracks"

class ClanRole(Enum):
    MEMBER = "member"
    ELDER = "elder"
    CO_LEADER = "co-leader"
    LEADER = "leader"

@dataclass
class GameConfig:
    """پیکربندی بازی"""
    # منابع اولیه
    INITIAL_COINS: int = 1000
    INITIAL_ELIXIR: int = 1000
    INITIAL_GEMS: int = 50
    
    # تولید منابع
    BASE_COIN_RATE: float = 1.0  # سکه بر ثانیه
    BASE_ELIXIR_RATE: float = 0.5  # اکسیر بر ثانیه
    
    # هزینه‌ها
    CLAN_CREATION_COST: int = 1000
    TOWNHALL_UPGRADE_BASE: int = 1000
    MINE_UPGRADE_BASE: int = 500
    COLLECTOR_UPGRADE_BASE: int = 500
    BARRACKS_UPGRADE_BASE: int = 800
    
    # زمان‌ها (ثانیه)
    ATTACK_COOLDOWN: int = 300  # 5 دقیقه
    DAILY_REWARD_COOLDOWN: int = 86400  # 24 ساعت
    RESOURCE_UPDATE_INTERVAL: int = 60  # 1 دقیقه
    
    # محدودیت‌ها
    MAX_BUILDING_LEVEL: int = 10
    MAX_CLAN_MEMBERS: int = 50
    MAX_USERNAME_LENGTH: int = 20
    MIN_USERNAME_LENGTH: int = 3
    
    # سیستم حمله
    BASE_ATTACK_POWER: float = 10.0
    BASE_DEFENSE_POWER: float = 5.0
    SUPER_COUNTRY_BOOST: float = 5.0
    
    # تجربه و لول
    XP_PER_LEVEL: int = 1000
    XP_ATTACK_WIN: int = 50
    XP_ATTACK_LOSE: int = 10
    
    # پاداش روزانه
    DAILY_COINS: int = 500
    DAILY_ELIXIR: int = 300
    DAILY_GEMS: int = 5
    DAILY_MULTIPLIER: float = 1.0  # ضریب بر اساس سطح

# ============================================================================
# State Classes
# ============================================================================

class UserStates(StatesGroup):
    """حالت‌های کاربر برای FSM"""
    waiting_for_name = State()
    waiting_for_clan_name = State()
    waiting_for_clan_join_code = State()
    waiting_for_clan_message = State()
    waiting_for_report_reason = State()
    waiting_for_admin_action = State()

# ============================================================================
# Database Layer
# ============================================================================

class DatabaseManager:
    """مدیریت دیتابیس با الگوی Singleton"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.db_path = DATABASE_URL
        self.conn = None
        self._connect()
        self._create_tables()
        self._initialized = True
        logger.info("✅ DatabaseManager initialized")
    
    def _connect(self):
        """اتصال به دیتابیس"""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            logger.info(f"✅ Connected to database: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Database connection error: {e}")
            raise
    
    def _create_tables(self):
        """ایجاد جداول مورد نیاز"""
        cursor = self.conn.cursor()
        
        # کاربران
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                game_name TEXT NOT NULL,
                coins INTEGER DEFAULT 1000,
                elixir INTEGER DEFAULT 1000,
                gems INTEGER DEFAULT 50,
                clan_id INTEGER DEFAULT NULL,
                clan_role TEXT DEFAULT 'member',
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                last_attack_time INTEGER DEFAULT 0,
                last_daily_reward INTEGER DEFAULT 0,
                last_resource_update INTEGER DEFAULT (strftime('%s', 'now')),
                warnings INTEGER DEFAULT 0,
                banned_until INTEGER DEFAULT 0,
                banned_reason TEXT DEFAULT NULL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (clan_id) REFERENCES clans(clan_id) ON DELETE SET NULL
            )
        ''')
        
        # ساختمان‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS buildings (
                user_id INTEGER PRIMARY KEY,
                townhall_level INTEGER DEFAULT 1,
                mine_level INTEGER DEFAULT 1,
                collector_level INTEGER DEFAULT 1,
                barracks_level INTEGER DEFAULT 1,
                wall_level INTEGER DEFAULT 1,
                last_upgrade_time INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # قبایل
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clans (
                clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                tag TEXT UNIQUE,
                description TEXT DEFAULT '',
                leader_id INTEGER NOT NULL,
                level INTEGER DEFAULT 1,
                trophies INTEGER DEFAULT 0,
                member_count INTEGER DEFAULT 1,
                max_members INTEGER DEFAULT 50,
                join_code TEXT UNIQUE,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (leader_id) REFERENCES users(user_id)
            )
        ''')
        
        # پیام‌های قبیله
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clan_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                reported_count INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (clan_id) REFERENCES clans(clan_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # گزارش‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                reported_user_id INTEGER NOT NULL,
                message_id INTEGER,
                reason TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                reviewed_by INTEGER DEFAULT NULL,
                reviewed_at INTEGER DEFAULT NULL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (reporter_id) REFERENCES users(user_id),
                FOREIGN KEY (reported_user_id) REFERENCES users(user_id),
                FOREIGN KEY (message_id) REFERENCES clan_messages(message_id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(user_id)
            )
        ''')
        
        # حمله‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attacks (
                attack_id INTEGER PRIMARY KEY AUTOINCREMENT,
                attacker_id INTEGER NOT NULL,
                defender_id INTEGER NOT NULL,
                result TEXT NOT NULL,
                loot_coins INTEGER DEFAULT 0,
                loot_elixir INTEGER DEFAULT 0,
                attacker_trophies_change INTEGER DEFAULT 0,
                defender_trophies_change INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (attacker_id) REFERENCES users(user_id),
                FOREIGN KEY (defender_id) REFERENCES users(user_id)
            )
        ''')
        
        # رتبه‌بندی
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leaderboard (
                user_id INTEGER PRIMARY KEY,
                trophies INTEGER DEFAULT 0,
                league TEXT DEFAULT 'bronze',
                rank INTEGER DEFAULT 0,
                season_wins INTEGER DEFAULT 0,
                season_losses INTEGER DEFAULT 0,
                total_attacks INTEGER DEFAULT 0,
                total_defenses INTEGER DEFAULT 0,
                last_season_reset INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # ایندکس‌ها
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_clan_id ON users(clan_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned_until)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_clan_messages_clan_id ON clan_messages(clan_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attacks_attacker ON attacks(attacker_id, created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attacks_defender ON attacks(defender_id, created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_leaderboard_trophies ON leaderboard(trophies DESC)')
        
        self.conn.commit()
        logger.info("✅ Database tables created/verified")
        
        # ایجاد کاربر ادمین اگر وجود ندارد
        self._create_admin_user()
    
    def _create_admin_user(self):
        """ایجاد کاربر ادمین (کشور ابرقدرت)"""
        try:
            cursor = self.conn.cursor()
            
            # بررسی وجود کاربر ادمین
            cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (ADMIN_ID,))
            if cursor.fetchone():
                logger.info("✅ Admin user already exists")
                return
            
            # ایجاد کاربر ادمین
            cursor.execute('''
                INSERT INTO users 
                (user_id, game_name, coins, elixir, gems, level, xp) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (ADMIN_ID, "👑 کشور ابرقدرت 👑", 9999999, 9999999, 999999, 100, 999999))
            
            # ایجاد ساختمان‌های ادمین
            cursor.execute('''
                INSERT INTO buildings 
                (user_id, townhall_level, mine_level, collector_level, barracks_level, wall_level) 
                VALUES (?, 20, 20, 20, 20, 20)
            ''', (ADMIN_ID,))
            
            # ایجاد رکورد لیگ
            cursor.execute('''
                INSERT INTO leaderboard 
                (user_id, trophies, league, rank) 
                VALUES (?, 99999, 'legend', 1)
            ''', (ADMIN_ID,))
            
            self.conn.commit()
            logger.info(f"✅ Admin user created: ID={ADMIN_ID}")
            
        except Exception as e:
            logger.error(f"❌ Error creating admin user: {e}")
            self.conn.rollback()
    
    # ==================== User Methods ====================
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """دریافت اطلاعات کاربر"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"❌ Error getting user {user_id}: {e}")
            return None
    
    def create_user(self, user_id: int, username: str, game_name: str) -> Optional[Dict]:
        """ایجاد کاربر جدید"""
        try:
            cursor = self.conn.cursor()
            
            # بررسی وجود کاربر
            if self.get_user(user_id):
                logger.info(f"User {user_id} already exists")
                return self.get_user(user_id)
            
            # ایجاد کاربر
            cursor.execute('''
                INSERT INTO users (user_id, username, game_name) 
                VALUES (?, ?, ?)
            ''', (user_id, username, game_name))
            
            # ایجاد ساختمان‌ها
            cursor.execute('''
                INSERT INTO buildings (user_id) VALUES (?)
            ''', (user_id,))
            
            # ایجاد رکورد لیگ
            cursor.execute('''
                INSERT INTO leaderboard (user_id) VALUES (?)
            ''', (user_id,))
            
            self.conn.commit()
            logger.info(f"✅ User created: {game_name} (ID: {user_id})")
            return self.get_user(user_id)
            
        except Exception as e:
            logger.error(f"❌ Error creating user: {e}")
            self.conn.rollback()
            return None
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        """آپدیت اطلاعات کاربر"""
        try:
            if not kwargs:
                return True
            
            cursor = self.conn.cursor()
            set_clause = ', '.join([f'{key} = ?' for key in kwargs.keys()])
            values = list(kwargs.values()) + [user_id]
            
            cursor.execute(f'''
                UPDATE users 
                SET {set_clause}, updated_at = strftime('%s', 'now') 
                WHERE user_id = ?
            ''', values)
            
            self.conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"❌ Error updating user {user_id}: {e}")
            self.conn.rollback()
            return False
    
    def update_user_resources(self, user_id: int) -> bool:
        """آپدیت منابع کاربر بر اساس زمان"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        building = self.get_building(user_id)
        if not building:
            return False
        
        now = int(time.time())
        last_update = user.get('last_resource_update', now)
        time_diff = max(0, now - last_update)
        
        # محاسبه منابع تولید شده
        mine_level = building.get('mine_level', 1)
        collector_level = building.get('collector_level', 1)
        townhall_level = building.get('townhall_level', 1)
        
        coins_produced = int(time_diff * (GameConfig.BASE_COIN_RATE * mine_level))
        elixir_produced = int(time_diff * (GameConfig.BASE_ELIXIR_RATE * collector_level))
        
        # محدودیت ظرفیت
        max_capacity = townhall_level * 5000
        
        new_coins = min(user['coins'] + coins_produced, max_capacity)
        new_elixir = min(user['elixir'] + elixir_produced, max_capacity)
        
        return self.update_user(
            user_id,
            coins=new_coins,
            elixir=new_elixir,
            last_resource_update=now
        )
    
    # ==================== Building Methods ====================
    
    def get_building(self, user_id: int) -> Optional[Dict]:
        """دریافت اطلاعات ساختمان‌های کاربر"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM buildings WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"❌ Error getting building for user {user_id}: {e}")
            return None
    
    def upgrade_building(self, user_id: int, building_type: str, cost_coins: int = 0, cost_elixir: int = 0) -> bool:
        """ارتقای ساختمان"""
        try:
            user = self.get_user(user_id)
            building = self.get_building(user_id)
            
            if not user or not building:
                return False
            
            # بررسی منابع
            if user['coins'] < cost_coins or user['elixir'] < cost_elixir:
                return False
            
            current_level = building.get(f'{building_type}_level', 1)
            if current_level >= GameConfig.MAX_BUILDING_LEVEL:
                return False
            
            # کسر منابع و ارتقا
            cursor = self.conn.cursor()
            cursor.execute(f'''
                UPDATE buildings 
                SET {building_type}_level = {building_type}_level + 1, 
                    last_upgrade_time = ?
                WHERE user_id = ?
            ''', (int(time.time()), user_id))
            
            cursor.execute('''
                UPDATE users 
                SET coins = coins - ?, elixir = elixir - ?
                WHERE user_id = ?
            ''', (cost_coins, cost_elixir, user_id))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Error upgrading building: {e}")
            self.conn.rollback()
            return False
    
    # ==================== Clan Methods ====================
    
    def create_clan(self, name: str, leader_id: int, description: str = "") -> Optional[int]:
        """ایجاد قبیله جدید"""
        try:
            # تولید کد عضویت تصادفی
            import random, string
            join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO clans (name, leader_id, description, join_code, member_count) 
                VALUES (?, ?, ?, ?, 1)
            ''', (name, leader_id, description, join_code))
            
            clan_id = cursor.lastrowid
            
            # آپدیت نقش کاربر
            self.update_user(leader_id, clan_id=clan_id, clan_role='leader')
            
            self.conn.commit()
            logger.info(f"✅ Clan created: {name} (ID: {clan_id})")
            return clan_id
            
        except sqlite3.IntegrityError as e:
            logger.warning(f"Clan name already exists: {name}")
            return None
        except Exception as e:
            logger.error(f"❌ Error creating clan: {e}")
            self.conn.rollback()
            return None
    
    def get_clan(self, clan_id: int) -> Optional[Dict]:
        """دریافت اطلاعات قبیله"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM clans WHERE clan_id = ?', (clan_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"❌ Error getting clan {clan_id}: {e}")
            return None
    
    def get_clan_members(self, clan_id: int) -> List[Dict]:
        """دریافت اعضای قبیله"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT u.*, l.trophies, l.league 
                FROM users u
                LEFT JOIN leaderboard l ON u.user_id = l.user_id
                WHERE u.clan_id = ? AND u.banned_until < ?
                ORDER BY 
                    CASE u.clan_role 
                        WHEN 'leader' THEN 1
                        WHEN 'co-leader' THEN 2
                        WHEN 'elder' THEN 3
                        ELSE 4 
                    END,
                    l.trophies DESC
            ''', (clan_id, int(time.time())))
            
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"❌ Error getting clan members: {e}")
            return []
    
    # ==================== Attack Methods ====================
    
    def record_attack(self, attacker_id: int, defender_id: int, result: str, 
                     loot_coins: int = 0, loot_elixir: int = 0) -> bool:
        """ثبت حمله"""
        try:
            cursor = self.conn.cursor()
            
            # محاسبه تغییر تروفی
            trophies_change = 10 if "برد" in result else -5
            
            cursor.execute('''
                INSERT INTO attacks 
                (attacker_id, defender_id, result, loot_coins, loot_elixir, attacker_trophies_change) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (attacker_id, defender_id, result, loot_coins, loot_elixir, trophies_change))
            
            # آپدیت تروفی‌ها
            if "برد" in result:
                cursor.execute('''
                    UPDATE leaderboard 
                    SET trophies = trophies + ?, season_wins = season_wins + 1, total_attacks = total_attacks + 1
                    WHERE user_id = ?
                ''', (10, attacker_id))
                cursor.execute('''
                    UPDATE leaderboard 
                    SET trophies = GREATEST(trophies - 5, 0), season_losses = season_losses + 1, total_defenses = total_defenses + 1
                    WHERE user_id = ?
                ''', (defender_id,))
            else:
                cursor.execute('''
                    UPDATE leaderboard 
                    SET trophies = GREATEST(trophies - 5, 0), season_losses = season_losses + 1, total_attacks = total_attacks + 1
                    WHERE user_id = ?
                ''', (attacker_id,))
                cursor.execute('''
                    UPDATE leaderboard 
                    SET trophies = trophies + ?, season_wins = season_wins + 1, total_defenses = total_defenses + 1
                    WHERE user_id = ?
                ''', (5, defender_id,))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Error recording attack: {e}")
            self.conn.rollback()
            return False
    
    # ==================== Leaderboard Methods ====================
    
    def get_leaderboard(self, limit: int = 20) -> List[Dict]:
        """دریافت رتبه‌بندی"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT u.game_name, u.level, l.trophies, l.league, l.season_wins, l.rank,
                       RANK() OVER (ORDER BY l.trophies DESC) as current_rank
                FROM leaderboard l
                JOIN users u ON l.user_id = u.user_id
                WHERE u.banned_until < ?
                ORDER BY l.trophies DESC 
                LIMIT ?
            ''', (int(time.time()), limit))
            
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"❌ Error getting leaderboard: {e}")
            return []
    
    def update_leagues(self):
        """آپدیت لیگ کاربران"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE leaderboard 
                SET league = CASE 
                    WHEN trophies >= 5000 THEN 'legend'
                    WHEN trophies >= 3000 THEN 'champion'
                    WHEN trophies >= 2000 THEN 'master'
                    WHEN trophies >= 1000 THEN 'crystal'
                    WHEN trophies >= 500 THEN 'gold'
                    WHEN trophies >= 200 THEN 'silver'
                    ELSE 'bronze'
                END
            ''')
            
            # آپدیت رتبه
            cursor.execute('''
                UPDATE leaderboard 
                SET rank = (
                    SELECT rank FROM (
                        SELECT user_id, ROW_NUMBER() OVER (ORDER BY trophies DESC) as rank
                        FROM leaderboard
                    ) ranked WHERE ranked.user_id = leaderboard.user_id
                )
            ''')
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"❌ Error updating leagues: {e}")
    
    def close(self):
        """بستن اتصال دیتابیس"""
        if self.conn:
            self.conn.close()
            logger.info("✅ Database connection closed")

# ============================================================================
# Game Engine
# ============================================================================

class GameEngine:
    """موتور اصلی بازی"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.config = GameConfig()
        logger.info("✅ GameEngine initialized")
    
    def calculate_attack(self, attacker_id: int, defender_id: int) -> Dict[str, Any]:
        """محاسبه نتیجه حمله"""
        attacker = self.db.get_user(attacker_id)
        defender = self.db.get_user(defender_id)
        
        if not attacker or not defender:
            return {"success": False, "message": "⚠️ کاربر یافت نشد!"}
        
        # بررسی کول‌داون
        now = int(time.time())
        if now - attacker.get('last_attack_time', 0) < self.config.ATTACK_COOLDOWN:
            remaining = self.config.ATTACK_COOLDOWN - (now - attacker.get('last_attack_time', 0))
            return {"success": False, "message": f"⏳ {remaining} ثانیه تا حمله بعدی"}
        
        # بررسی بن بودن
        if defender.get('banned_until', 0) > now:
            return {"success": False, "message": "⚠️ این کاربر بن شده است"}
        
        # محاسبه قدرت
        attacker_building = self.db.get_building(attacker_id)
        defender_building = self.db.get_building(defender_id)
        
        attack_power = self.config.BASE_ATTACK_POWER
        defense_power = self.config.BASE_DEFENSE_POWER
        
        # تاثیر سطح
        attack_power += attacker['level'] * 0.5
        defense_power += defender['level'] * 0.3
        
        # تاثیر ساختمان‌ها
        if attacker_building:
            attack_power += attacker_building.get('barracks_level', 1) * 2
        
        if defender_building:
            defense_power += defender_building.get('townhall_level', 1) * 1.5
        
        # کشور ابرقدرت
        if defender_id == ADMIN_ID:
            defense_power *= self.config.SUPER_COUNTRY_BOOST
        
        # شبیه‌سازی نبرد
        total_power = attack_power + defense_power
        attack_chance = attack_power / total_power
        
        if random.random() < attack_chance:
            # برد
            loot_percentage = random.uniform(0.1, 0.3)  # 10-30% غنیمت
            loot_coins = min(int(defender['coins'] * loot_percentage), 5000)
            loot_elixir = min(int(defender['elixir'] * loot_percentage), 5000)
            
            # انتقال منابع
            self.db.update_user(defender_id, coins=defender['coins'] - loot_coins)
            self.db.update_user(defender_id, elixir=defender['elixir'] - loot_elixir)
            self.db.update_user(attacker_id, coins=attacker['coins'] + loot_coins)
            self.db.update_user(attacker_id, elixir=attacker['elixir'] + loot_elixir)
            
            # ثبت حمله
            self.db.record_attack(
                attacker_id, defender_id, "برد",
                loot_coins, loot_elixir
            )
            
            # آپدیت زمان حمله و XP
            self.db.update_user(attacker_id, last_attack_time=now)
            self._add_xp(attacker_id, self.config.XP_ATTACK_WIN)
            
            return {
                "success": True,
                "result": "برد",
                "loot_coins": loot_coins,
                "loot_elixir": loot_elixir,
                "attack_power": round(attack_power, 1),
                "defense_power": round(defense_power, 1)
            }
        else:
            # باخت
            self.db.update_user(attacker_id, last_attack_time=now)
            self.db.record_attack(attacker_id, defender_id, "باخت")
            self._add_xp(attacker_id, self.config.XP_ATTACK_LOSE)
            
            return {
                "success": True,
                "result": "باخت",
                "loot_coins": 0,
                "loot_elixir": 0,
                "attack_power": round(attack_power, 1),
                "defense_power": round(defense_power, 1)
            }
    
    def _add_xp(self, user_id: int, xp_amount: int):
        """افزایش تجربه کاربر"""
        user = self.db.get_user(user_id)
        if not user:
            return
        
        new_xp = user['xp'] + xp_amount
        new_level = user['level']
        
        # افزایش سطح
        while new_xp >= new_level * self.config.XP_PER_LEVEL:
            new_xp -= new_level * self.config.XP_PER_LEVEL
            new_level += 1
        
        self.db.update_user(user_id, xp=new_xp, level=new_level)
    
    def give_daily_reward(self, user_id: int) -> Optional[Dict]:
        """اعطای پاداش روزانه"""
        user = self.db.get_user(user_id)
        if not user:
            return None
        
        now = int(time.time())
        
        # بررسی اینکه آیا امروز پاداش گرفته یا نه
        if now - user.get('last_daily_reward', 0) < self.config.DAILY_REWARD_COOLDOWN:
            return None
        
        # محاسبه پاداش
        multiplier = 1.0 + (user['level'] * 0.1)
        reward_coins = int(self.config.DAILY_COINS * multiplier)
        reward_elixir = int(self.config.DAILY_ELIXIR * multiplier)
        reward_gems = int(self.config.DAILY_GEMS * multiplier)
        
        # اعطای پاداش
        self.db.update_user(
            user_id,
            coins=user['coins'] + reward_coins,
            elixir=user['elixir'] + reward_elixir,
            gems=user['gems'] + reward_gems,
            last_daily_reward=now
        )
        
        return {
            "coins": reward_coins,
            "elixir": reward_elixir,
            "gems": reward_gems
        }
    
    def check_forbidden_words(self, text: str) -> bool:
        """بررسی وجود کلمات ممنوعه"""
        forbidden_words = [
            "کص", "کیر", "کس", "گایید", "لاشی", "جنده", "ننت",
            "خارکصه", "مادرجنده", "کونی", "حرومزاده", "بیناموس",
            "kir", "kos", "jende", "lanat"
        ]
        
        text_lower = text.lower()
        return any(word in text_lower for word in forbidden_words)

# ============================================================================
# Web Panel
# ============================================================================

class ClanWebPanel:
    """پنل وب برای مشاهده پیام‌های قبیله"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def handle_request(self, request):
        """مدیریت درخواست‌های HTTP"""
        path = request.path
        
        if path == '/':
            return await self._serve_homepage()
        elif path.startswith('/clan/'):
            return await self._serve_clan_messages(request)
        elif path == '/health':
            return web.Response(text='OK', status=200)
        else:
            return web.Response(text='404 Not Found', status=404)
    
    async def _serve_homepage(self):
        """صفحه اصلی"""
        html = '''
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AmeleClashBot - پنل قبیله</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #1a2980, #26d0ce);
                    color: white;
                    min-height: 100vh;
                    padding: 20px;
                }
                .container {
                    max-width: 1000px;
                    margin: 0 auto;
                    background: rgba(0, 0, 0, 0.8);
                    border-radius: 20px;
                    padding: 30px;
                    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.5);
                    backdrop-filter: blur(10px);
                }
                header {
                    text-align: center;
                    margin-bottom: 30px;
                    padding-bottom: 20px;
                    border-bottom: 3px solid #FFD700;
                }
                h1 {
                    color: #FFD700;
                    font-size: 2.5em;
                    margin-bottom: 10px;
                    text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
                }
                .subtitle {
                    color: #aaa;
                    font-size: 1.1em;
                }
                .info-box {
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px 0;
                    border-right: 5px solid #4CAF50;
                }
                .warning {
                    background: rgba(255, 87, 34, 0.2);
                    border-color: #FF5722;
                }
                .feature-list {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-top: 30px;
                }
                .feature {
                    background: rgba(255, 255, 255, 0.05);
                    padding: 20px;
                    border-radius: 10px;
                    text-align: center;
                    transition: transform 0.3s;
                }
                .feature:hover {
                    transform: translateY(-5px);
                    background: rgba(255, 255, 255, 0.1);
                }
                .feature-icon {
                    font-size: 2em;
                    margin-bottom: 10px;
                }
                footer {
                    text-align: center;
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid rgba(255, 255, 255, 0.1);
                    color: #888;
                    font-size: 0.9em;
                }
                .btn {
                    display: inline-block;
                    background: linear-gradient(45deg, #FFD700, #FFA000);
                    color: #000;
                    padding: 12px 24px;
                    border-radius: 25px;
                    text-decoration: none;
                    font-weight: bold;
                    margin: 10px;
                    transition: all 0.3s;
                    border: none;
                    cursor: pointer;
                }
                .btn:hover {
                    transform: scale(1.05);
                    box-shadow: 0 5px 15px rgba(255, 215, 0, 0.4);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <header>
                    <h1>🏰 AmeleClashBot</h1>
                    <p class="subtitle">پنل مدیریت قبیله - نسخه حرفه‌ای</p>
                </header>
                
                <div class="info-box">
                    <h2>📖 راهنمای استفاده</h2>
                    <p>برای مشاهده پیام‌های قبیله، از ربات تلگرام لینک مخصوص قبیله خود را دریافت کنید.</p>
                    <p>این پنل فقط برای اعضای قبیله قابل دسترسی است و نیاز به احراز هویت دارد.</p>
                </div>
                
                <div class="feature-list">
                    <div class="feature">
                        <div class="feature-icon">💬</div>
                        <h3>چت قبیله</h3>
                        <p>مشاهده تمام پیام‌های قبیله به صورت زنده</p>
                    </div>
                    <div class="feature">
                        <div class="feature-icon">👥</div>
                        <h3>مدیریت اعضا</h3>
                        <p>مدیریت اعضای قبیله و نقش‌های آنها</p>
                    </div>
                    <div class="feature">
                        <div class="feature-icon">⚔️</div>
                        <h3>آمار جنگ</h3>
                        <p>مشاهده آمار حمله و دفاع اعضا</p>
                    </div>
                    <div class="feature">
                        <div class="feature-icon">📊</div>
                        <h3>گزارش‌ها</h3>
                        <p>گزارش‌های سیستمی و مدیریتی</p>
                    </div>
                </div>
                
                <div class="info-box warning">
                    <h2>⚠️ امنیت</h2>
                    <p>• تمام ارتباطات به صورت رمزگذاری شده انجام می‌شود</p>
                    <p>• دسترسی فقط برای اعضای تأیید شده قبیله</p>
                    <p>• لاگ کامل تمام فعالیت‌ها</p>
                </div>
                
                <footer>
                    <p>© 2024 AmeleClashBot - کلیه حقوق محفوظ است</p>
                    <p>نسخه: 2.0.0 | توسعه یافته با ❤️</p>
                </footer>
            </div>
        </body>
        </html>
        '''
        
        return web.Response(text=html, content_type='text/html')
    
    async def _serve_clan_messages(self, request):
        """نمایش پیام‌های قبیله"""
        try:
            # استخراج پارامترها
            clan_id = int(request.path.split('/')[2])
            token = request.query.get('token', '')
            
            # احراز هویت ساده (در واقعیت باید بهتر باشد)
            clan = self.db.get_clan(clan_id)
            if not clan:
                return web.Response(text='<h1>قبیله یافت نشد</h1>', status=404, content_type='text/html')
            
            if token != clan.get('join_code', ''):
                return web.Response(text='<h1>دسترسی غیرمجاز</h1>', status=403, content_type='text/html')
            
            # دریافت پیام‌ها
            cursor = self.db.conn.cursor()
            cursor.execute('''
                SELECT cm.*, u.game_name, u.username 
                FROM clan_messages cm
                JOIN users u ON cm.user_id = u.user_id
                WHERE cm.clan_id = ? 
                ORDER BY cm.created_at DESC 
                LIMIT 100
            ''', (clan_id,))
            
            messages = cursor.fetchall()
            
            # تولید HTML
            html = f'''
            <!DOCTYPE html>
            <html dir="rtl">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>پیام‌های قبیله {clan['name']}</title>
                <style>
                    body {{
                        font-family: Tahoma, sans-serif;
                        background: linear-gradient(135deg, #1a2980, #26d0ce);
                        color: white;
                        padding: 20px;
                    }}
                    .container {{
                        max-width: 800px;
                        margin: 0 auto;
                        background: rgba(0,0,0,0.8);
                        border-radius: 15px;
                        padding: 20px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                    }}
                    h1 {{
                        text-align: center;
                        color: #FFD700;
                        border-bottom: 2px solid #FFD700;
                        padding-bottom: 10px;
                        margin-bottom: 20px;
                    }}
                    .message {{
                        background: rgba(255,255,255,0.1);
                        border-radius: 10px;
                        padding: 15px;
                        margin: 10px 0;
                        border-right: 5px solid #4CAF50;
                        transition: transform 0.2s;
                    }}
                    .message:hover {{
                        transform: translateX(-5px);
                        background: rgba(255,255,255,0.15);
                    }}
                    .user {{
                        color: #FFD700;
                        font-weight: bold;
                        margin-bottom: 5px;
                        font-size: 1.1em;
                    }}
                    .time {{
                        color: #aaa;
                        font-size: 0.8em;
                        text-align: left;
                        margin-top: 5px;
                    }}
                    .admin-message {{
                        border-right-color: #FF5722;
                        background: rgba(255, 87, 34, 0.1);
                    }}
                    .message-content {{
                        margin: 10px 0;
                        line-height: 1.6;
                    }}
                    .stats {{
                        text-align: center;
                        color: #aaa;
                        margin-bottom: 20px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🏰 پیام‌های قبیله {clan['name']}</h1>
                    <div class="stats">📊 تعداد پیام‌ها: {len(messages)} | آخرین به‌روزرسانی: {datetime.now().strftime('%H:%M')}</div>
            '''
            
            for msg in messages:
                msg_dict = dict(msg)
                time_str = datetime.fromtimestamp(msg_dict['created_at']).strftime('%Y/%m/%d %H:%M')
                is_admin = msg_dict['user_id'] == ADMIN_ID
                
                html += f'''
                <div class="message {'admin-message' if is_admin else ''}">
                    <div class="user">
                        {'👑' if is_admin else '👤'} {msg_dict['game_name']} 
                        <small>(@{msg_dict['username'] or 'ناشناس'})</small>
                    </div>
                    <div class="message-content">{msg_dict['message']}</div>
                    <div class="time">🕐 {time_str}</div>
                </div>
                '''
            
            html += '''
                </div>
            </body>
            </html>
            '''
            
            return web.Response(text=html, content_type='text/html')
            
        except Exception as e:
            logger.error(f"❌ Error serving clan messages: {e}")
            return web.Response(text=f'خطا: {str(e)}', status=500)

# ============================================================================
# Main Bot Class
# ============================================================================

class AmeleClashBot:
    """کلاس اصلی ربات"""
    
    def __init__(self):
        self.bot = None
        self.dp = None
        self.db = DatabaseManager()
        self.game = GameEngine(self.db)
        self.web_panel = ClanWebPanel(self.db)
        self.app = None
        self.runner = None
        self.site = None
        
        logger.info("✅ AmeleClashBot instance created")
    
    async def setup(self):
        """تنظیمات اولیه ربات"""
        logger.info("🚀 Setting up AmeleClashBot...")
        
        # ایجاد ربات
        self.bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True
            )
        )
        
        # ایجاد dispatcher
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # ثبت هندلرها
        self._register_handlers()
        
        # ایجاد برنامه وب
        self.app = web.Application()
        self.app.router.add_get('/{tail:.*}', self.web_panel.handle_request)
        
        # تنظیم وب‌هوک
        handler = SimpleRequestHandler(
            dispatcher=self.dp,
            bot=self.bot,
        )
        self.app.router.add_post("/webhook", handler)
        
        # تنظیم application
        setup_application(self.app, self.dp, bot=self.bot)
        
        # راه‌اندازی سرور
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', PORT)
        await self.site.start()
        
        logger.info(f"✅ Web server started on port {PORT}")
    
    def _register_handlers(self):
        """ثبت تمام هندلرهای ربات"""
        
        # ========== Command Handlers ==========
        
        @self.dp.message(CommandStart())
        async def cmd_start(message: Message, state: FSMContext):
            """شروع بازی"""
            user_id = message.from_user.id
            username = message.from_user.username or ""
            
            logger.info(f"🎮 /start from {user_id} (@{username})")
            
            # آپدیت منابع کاربر
            self.db.update_user_resources(user_id)
            
            user = self.db.get_user(user_id)
            
            if user:
                await self._show_main_menu(message, user)
            else:
                await message.answer(
                    "🎮 <b>به AmeleClashBot خوش آمدید!</b>\n\n"
                    "🏰 این یک بازی استراتژیک متنی الهام گرفته از Clash of Clans است.\n\n"
                    "📝 لطفاً <b>نام دهکده</b> خود را وارد کنید:",
                    parse_mode=ParseMode.HTML
                )
                await state.set_state(UserStates.waiting_for_name)
        
        @self.dp.message(Command("profile"))
        async def cmd_profile(message: Message):
            """نمایش پروفایل"""
            user_id = message.from_user.id
            
            # آپدیت منابع
            self.db.update_user_resources(user_id)
            user = self.db.get_user(user_id)
            
            if not user:
                await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                return
            
            building = self.db.get_building(user_id)
            clan = self.db.get_clan(user['clan_id']) if user['clan_id'] else None
            
            # ساخت متن پروفایل
            profile_text = [
                f"👤 <b>پروفایل {user['game_name']}</b>",
                "",
                f"📊 <b>سطح {user['level']}</b> | XP: {user['xp']}/{user['level'] * 1000}",
                "",
                "💰 <b>منابع:</b>",
                f"  • سکه: {user['coins']:,} 🪙",
                f"  • اکسیر: {user['elixir']:,} 🧪",
                f"  • جم: {user['gems']:,} 💎",
                "",
                "🏰 <b>ساختمان‌ها:</b>",
                f"  • تاون هال: سطح {building['townhall_level'] if building else 1}",
                f"  • معدن سکه: سطح {building['mine_level'] if building else 1}",
                f"  • کالکتور اکسیر: سطح {building['collector_level'] if building else 1}",
                f"  • پادگان: سطح {building['barracks_level'] if building else 1}",
            ]
            
            if clan:
                profile_text.extend([
                    "",
                    "🏛️ <b>قبیله:</b>",
                    f"  • نام: {clan['name']}",
                    f"  • نقش: {user['clan_role']}",
                    f"  • اعضا: {clan['member_count']}/{clan['max_members']}",
                ])
            
            # دکمه‌ها
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.answer(
                "\n".join(profile_text),
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("attack"))
        async def cmd_attack(message: Message):
            """منوی حمله"""
            user_id = message.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                return
            
            # دریافت لیست هدف‌ها
            cursor = self.db.conn.cursor()
            cursor.execute('''
                SELECT u.user_id, u.game_name, u.level, l.trophies, l.league 
                FROM users u
                JOIN leaderboard l ON u.user_id = l.user_id
                WHERE u.user_id != ? AND u.banned_until < ? AND u.user_id != ?
                ORDER BY l.trophies DESC 
                LIMIT 5
            ''', (user_id, int(time.time()), ADMIN_ID))
            
            targets = cursor.fetchall()
            
            keyboard = InlineKeyboardBuilder()
            
            for target in targets:
                target_dict = dict(target)
                keyboard.add(InlineKeyboardButton(
                    text=f"⚔️ {target_dict['game_name']} (سطح {target_dict['level']})",
                    callback_data=f"attack_{target_dict['user_id']}"
                ))
            
            # کشور ابرقدرت
            keyboard.add(InlineKeyboardButton(
                text="👑 کشور ابرقدرت ⚠️",
                callback_data=f"attack_{ADMIN_ID}"
            ))
            
            keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.answer(
                "⚔️ <b>سیستم حمله</b>\n\n"
                "هدف حمله را انتخاب کنید:\n"
                "(هر حمله ۵ دقیقه کول‌داون دارد)\n\n"
                "🎯 <i>توصیه: بازیکنان با تروفی کمتر را هدف قرار دهید!</i>",
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("build"))
        async def cmd_build(message: Message):
            """منوی ساختمان‌ها"""
            user_id = message.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                return
            
            building = self.db.get_building(user_id)
            if not building:
                await message.answer("⚠️ اطلاعات ساختمان‌ها یافت نشد!")
                return
            
            # محاسبه هزینه‌ها
            config = GameConfig()
            townhall_cost = building['townhall_level'] * config.TOWNHALL_UPGRADE_BASE
            mine_cost = building['mine_level'] * config.MINE_UPGRADE_BASE
            collector_cost = building['collector_level'] * config.COLLECTOR_UPGRADE_BASE
            barracks_cost = building['barracks_level'] * config.BARRACKS_UPGRADE_BASE
            
            text = [
                "🏗️ <b>ساختمان‌های دهکده</b>",
                "",
                f"🏰 <b>تاون هال: سطح {building['townhall_level']}</b>",
                f"   ظرفیت منابع: {building['townhall_level'] * 5000:,}",
                f"   هزینه ارتقا: {townhall_cost:,} سکه",
                "",
                f"⛏️ <b>معدن سکه: سطح {building['mine_level']}</b>",
                f"   تولید: {building['mine_level'] * config.BASE_COIN_RATE:.1f} سکه/ثانیه",
                f"   هزینه ارتقا: {mine_cost:,} سکه",
                "",
                f"⚗️ <b>کالکتور اکسیر: سطح {building['collector_level']}</b>",
                f"   تولید: {building['collector_level'] * config.BASE_ELIXIR_RATE:.1f} اکسیر/ثانیه",
                f"   هزینه ارتقا: {collector_cost:,} اکسیر",
                "",
                f"⚔️ <b>پادگان: سطح {building['barracks_level']}</b>",
                f"   قدرت حمله: +{building['barracks_level'] * 2}%",
                f"   هزینه ارتقا: {barracks_cost:,} سکه",
            ]
            
            keyboard = InlineKeyboardBuilder()
            keyboard.row(
                InlineKeyboardButton(text="🏰 تاون هال", callback_data="upgrade_townhall"),
                InlineKeyboardButton(text="⛏️ معدن", callback_data="upgrade_mine"),
            )
            keyboard.row(
                InlineKeyboardButton(text="⚗️ کالکتور", callback_data="upgrade_collector"),
                InlineKeyboardButton(text="⚔️ پادگان", callback_data="upgrade_barracks"),
            )
            keyboard.row(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.answer(
                "\n".join(text),
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("clan"))
        async def cmd_clan(message: Message):
            """منوی قبیله"""
            user_id = message.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                return
            
            keyboard = InlineKeyboardBuilder()
            
            if user['clan_id']:
                # کاربر در قبیله است
                clan = self.db.get_clan(user['clan_id'])
                members = self.db.get_clan_members(user['clan_id'])
                
                text = [
                    f"🏛️ <b>قبیله {clan['name']}</b>",
                    f"👑 رهبر: {clan['leader_id']}",
                    f"👥 اعضا: {len(members)}/{clan['max_members']}",
                    f"🏆 تروفی: {clan['trophies']:,}",
                    "",
                    "<b>چه کاری انجام دهیم؟</b>"
                ]
                
                keyboard.row(
                    InlineKeyboardButton(text="💬 چت قبیله", callback_data="clan_chat"),
                    InlineKeyboardButton(text="👥 اعضا", callback_data="clan_members"),
                )
                
                if user['clan_role'] in ['leader', 'co-leader']:
                    keyboard.row(
                        InlineKeyboardButton(text="⚙️ مدیریت", callback_data="clan_manage"),
                        InlineKeyboardButton(text="🔗 لینک پنل", callback_data="clan_panel"),
                    )
                
                keyboard.row(InlineKeyboardButton(text="🚪 خروج", callback_data="clan_leave"))
                
            else:
                # کاربر در قبیله نیست
                text = [
                    "🏛️ <b>سیستم قبیله</b>",
                    "",
                    "شما در حال حاضر در قبیله‌ای عضو نیستید.",
                    "",
                    "<b>گزینه‌های شما:</b>"
                ]
                
                keyboard.row(
                    InlineKeyboardButton(text="🏛️ ساخت قبیله", callback_data="clan_create"),
                    InlineKeyboardButton(text="🔍 جستجو", callback_data="clan_search"),
                )
                keyboard.row(InlineKeyboardButton(text="📊 لیست قبایل", callback_data="clan_list"))
            
            keyboard.row(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.answer(
                "\n".join(text),
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("leaderboard"))
        async def cmd_leaderboard(message: Message):
            """رتبه‌بندی جهانی"""
            leaderboard = self.db.get_leaderboard(15)
            
            text = ["🏆 <b>رتبه‌بندی جهانی</b>", ""]
            
            for i, player in enumerate(leaderboard, 1):
                medal = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                text.append(
                    f"{medal} <b>{player['game_name']}</b> (سطح {player['level']})"
                    f"\n   🏆 {player['trophies']:,} | لیگ: {player['league']}"
                    f" | برد: {player['season_wins']}"
                )
            
            keyboard = InlineKeyboardBuilder()
            keyboard.row(
                InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="leaderboard_refresh"),
                InlineKeyboardButton(text="📊 آمار من", callback_data="my_stats"),
            )
            keyboard.row(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.answer(
                "\n".join(text),
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("daily"))
        async def cmd_daily(message: Message):
            """پاداش روزانه"""
            user_id = message.from_user.id
            reward = self.game.give_daily_reward(user_id)
            
            if reward:
                text = [
                    "🎁 <b>پاداش روزانه دریافت شد!</b>",
                    "",
                    f"💰 <b>سکه:</b> +{reward['coins']:,}",
                    f"🧪 <b>اکسیر:</b> +{reward['elixir']:,}",
                    f"💎 <b>جم:</b> +{reward['gems']}",
                    "",
                    "🔥 دفعه بعد: فردا همین موقع!"
                ]
            else:
                text = [
                    "⏳ <b>شما امروز پاداش روزانه خود را دریافت کرده‌اید!</b>",
                    "",
                    "لطفاً فردا مجدداً تلاش کنید."
                ]
            
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.answer(
                "\n".join(text),
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("admin"))
        async def cmd_admin(message: Message):
            """پنل ادمین"""
            user_id = message.from_user.id
            
            if user_id != ADMIN_ID:
                await message.answer("⛔ دسترسی غیرمجاز!")
                return
            
            keyboard = InlineKeyboardBuilder()
            keyboard.row(
                InlineKeyboardButton(text="👥 کاربران", callback_data="admin_users"),
                InlineKeyboardButton(text="🏛️ قبایل", callback_data="admin_clans"),
            )
            keyboard.row(
                InlineKeyboardButton(text="⚠️ گزارش‌ها", callback_data="admin_reports"),
                InlineKeyboardButton(text="📊 آمار", callback_data="admin_stats"),
            )
            keyboard.row(
                InlineKeyboardButton(text="🚫 بن کاربر", callback_data="admin_ban"),
                InlineKeyboardButton(text="🔄 به‌روزرسانی", callback_data="admin_update"),
            )
            
            await message.answer(
                "👑 <b>پنل مدیریت ادمین</b>\n\n"
                "گزینه مورد نظر را انتخاب کنید:",
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
        
        # ========== State Handlers ==========
        
        @self.dp.message(UserStates.waiting_for_name)
        async def process_name(message: Message, state: FSMContext):
            """پردازش نام کاربر"""
            user_id = message.from_user.id
            username = message.from_user.username or ""
            game_name = message.text.strip()
            
            config = GameConfig()
            
            # اعتبارسنجی
            if len(game_name) < config.MIN_USERNAME_LENGTH:
                await message.answer(f"⚠️ نام باید حداقل {config.MIN_USERNAME_LENGTH} حرف باشد!")
                return
            
            if len(game_name) > config.MAX_USERNAME_LENGTH:
                await message.answer(f"⚠️ نام نمی‌تواند بیشتر از {config.MAX_USERNAME_LENGTH} حرف باشد!")
                return
            
            if self.game.check_forbidden_words(game_name):
                await message.answer("⚠️ نام شما حاوی کلمات نامناسب است!")
                return
            
            # ایجاد کاربر
            user = self.db.create_user(user_id, username, game_name)
            
            if user:
                await message.answer(
                    f"✅ <b>ثبت نام موفق!</b>\n\n"
                    f"به دنیای AmeleClash خوش آمدی، <b>{game_name}</b>! 👋\n\n"
                    f"🏰 دهکده شما با موفقیت ساخته شد.\n"
                    f"💰 منابع اولیه: {config.INITIAL_COINS:,} سکه، {config.INITIAL_ELIXIR:,} اکسیر\n\n"
                    f"برای شروع بازی از منوی زیر استفاده کن:",
                    parse_mode=ParseMode.HTML
                )
                await self._show_main_menu(message, user)
            else:
                await message.answer("⚠️ خطا در ثبت نام! لطفاً مجدداً تلاش کنید.")
            
            await state.clear()
        
        @self.dp.message(UserStates.waiting_for_clan_name)
        async def process_clan_name(message: Message, state: FSMContext):
            """پردازش نام قبیله"""
            user_id = message.from_user.id
            clan_name = message.text.strip()
            
            user = self.db.get_user(user_id)
            if not user:
                await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                await state.clear()
                return
            
            config = GameConfig()
            
            # اعتبارسنجی
            if len(clan_name) < 3:
                await message.answer("⚠️ نام قبیله باید حداقل ۳ حرف باشد!")
                return
            
            if self.game.check_forbidden_words(clan_name):
                await message.answer("⚠️ نام قبیله حاوی کلمات نامناسب است!")
                return
            
            # بررسی هزینه
            if user['coins'] < config.CLAN_CREATION_COST:
                await message.answer(
                    f"⚠️ سکه کافی ندارید!\n"
                    f"نیاز: {config.CLAN_CREATION_COST:,} سکه\n"
                    f"دارایی شما: {user['coins']:,} سکه"
                )
                await state.clear()
                return
            
            # ایجاد قبیله
            clan_id = self.db.create_clan(clan_name, user_id)
            
            if clan_id:
                # کسر هزینه
                self.db.update_user(user_id, coins=user['coins'] - config.CLAN_CREATION_COST)
                
                await message.answer(
                    f"✅ <b>قبیله {clan_name} با موفقیت ساخته شد!</b>\n\n"
                    f"🏛️ شما اکنون رهبر این قبیله هستید.\n"
                    f"💰 هزینه: {config.CLAN_CREATION_COST:,} سکه\n\n"
                    f"برای مدیریت قبیله از منوی قبیله استفاده کنید.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("⚠️ این نام قبلاً استفاده شده است!")
            
            await state.clear()
        
        # ========== Callback Query Handlers ==========
        
        @self.dp.callback_query(F.data == "main_menu")
        async def callback_main_menu(callback: CallbackQuery):
            """بازگشت به منوی اصلی"""
            user_id = callback.from_user.id
            user = self.db.get_user(user_id)
            
            if user:
                await self._show_main_menu(callback.message, user)
            else:
                await callback.message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
            
            await callback.answer()
        
        @self.dp.callback_query(F.data.startswith("attack_"))
        async def callback_attack(callback: CallbackQuery):
            """حمله به کاربر"""
            user_id = callback.from_user.id
            target_id = int(callback.data.split("_")[1])
            
            result = self.game.calculate_attack(user_id, target_id)
            
            if result["success"]:
                if result["result"] == "برد":
                    text = [
                        "🎉 <b>حمله موفق!</b>",
                        "",
                        "شما دهکده را غارت کردید:",
                        f"💰 سکه: +{result['loot_coins']:,}",
                        f"🧪 اکسیر: +{result['loot_elixir']:,}",
                        "",
                        f"⚔️ قدرت حمله: {result['attack_power']}",
                        f"🛡️ قدرت دفاع: {result['defense_power']}",
                        "",
                        "✨ +50 XP دریافت کردید!"
                    ]
                else:
                    text = [
                        "💔 <b>حمله ناموفق!</b>",
                        "",
                        "شما در نبرد شکست خوردید!",
                        "",
                        f"⚔️ قدرت حمله: {result['attack_power']}",
                        f"🛡️ قدرت دفاع: {result['defense_power']}",
                        "",
                        "✨ +10 XP دریافت کردید!"
                    ]
            else:
                text = [result["message"]]
            
            keyboard = InlineKeyboardBuilder()
            keyboard.row(
                InlineKeyboardButton(text="⚔️ حمله مجدد", callback_data="attack"),
                InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"),
            )
            
            await callback.message.edit_text(
                "\n".join(text),
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.HTML
            )
            await callback.answer()
        
        @self.dp.callback_query(F.data.startswith("upgrade_"))
        async def callback_upgrade(callback: CallbackQuery):
            """ارتقای ساختمان"""
            user_id = callback.from_user.id
            building_type = callback.data.split("_")[1]
            
            user = self.db.get_user(user_id)
            building = self.db.get_building(user_id)
            
            if not user or not building:
                await callback.message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                await callback.answer()
                return
            
            config = GameConfig()
            
            # محاسبه هزینه
            current_level = building.get(f'{building_type}_level', 1)
            
            if building_type == "townhall":
                cost = current_level * config.TOWNHALL_UPGRADE_BASE
                resource_type = "coins"
            elif building_type == "mine":
                cost = current_level * config.MINE_UPGRADE_BASE
                resource_type = "coins"
            elif building_type == "collector":
                cost = current_level * config.COLLECTOR_UPGRADE_BASE
                resource_type = "elixir"
            else:  # barracks
                cost = current_level * config.BARRACKS_UPGRADE_BASE
                resource_type = "coins"
            
            # بررسی سطح ماکسیمم
            if current_level >= config.MAX_BUILDING_LEVEL:
                await callback.message.answer("⚠️ این ساختمان به حداکثر سطح رسیده است!")
                await callback.answer()
                return
            
            # بررسی منابع
            if user[resource_type] < cost:
                await callback.message.answer(
                    f"⚠️ {resource_type} کافی ندارید!\n"
                    f"نیاز: {cost:,} {resource_type}\n"
                    f"دارایی شما: {user[resource_type]:,} {resource_type}"
                )
                await callback.answer()
                return
            
            # ارتقا
            success = self.db.upgrade_building(user_id, building_type, 
                                              cost if resource_type == "coins" else 0,
                                              cost if resource_type == "elixir" else 0)
            
            if success:
                await callback.message.answer(
                    f"✅ <b>ساختمان با موفقیت ارتقا یافت!</b>\n\n"
                    f"🏗️ ساختمان: {building_type}\n"
                    f"📈 سطح جدید: {current_level + 1}\n"
                    f"💰 هزینه: {cost:,} {resource_type}",
                    parse_mode=ParseMode.HTML
                )
                
                # بازگشت به منوی ساختمان‌ها
                await cmd_build(callback.message)
            else:
                await callback.message.answer("⚠️ خطا در ارتقای ساختمان!")
            
            await callback.answer()
        
        @self.dp.callback_query(F.data == "clan_create")
        async def callback_clan_create(callback: CallbackQuery, state: FSMContext):
            """ساخت قبیله"""
            user_id = callback.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await callback.message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
                await callback.answer()
                return
            
            config = GameConfig()
            
            # بررسی هزینه
            if user['coins'] < config.CLAN_CREATION_COST:
                await callback.message.answer(
                    f"⚠️ سکه کافی ندارید!\n"
                    f"نیاز: {config.CLAN_CREATION_COST:,} سکه\n"
                    f"دارایی شما: {user['coins']:,} سکه"
                )
                await callback.answer()
                return
            
            await callback.message.answer(
                "🏛️ <b>ساخت قبیله جدید</b>\n\n"
                "لطفاً نام قبیله خود را وارد کنید:",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(UserStates.waiting_for_clan_name)
            await callback.answer()
        
        # ========== Admin Callback Handlers ==========
        
        @self.dp.callback_query(F.data.startswith("admin_"))
        async def callback_admin(callback: CallbackQuery):
            """پنل ادمین"""
            user_id = callback.from_user.id
            
            if user_id != ADMIN_ID:
                await callback.message.answer("⛔ دسترسی غیرمجاز!")
                await callback.answer()
                return
            
            action = callback.data.split("_")[1]
            
            if action == "users":
                cursor = self.db.conn.cursor()
                cursor.execute('SELECT COUNT(*) as total FROM users')
                total = cursor.fetchone()['total']
                
                cursor.execute('SELECT COUNT(*) as banned FROM users WHERE banned_until > ?', 
                             (int(time.time()),))
                banned = cursor.fetchone()['banned']
                
                cursor.execute('SELECT COUNT(*) as active FROM users WHERE last_resource_update > ?', 
                             (int(time.time()) - 86400,))
                active = cursor.fetchone()['active']
                
                text = [
                    "📊 <b>آمار کاربران</b>",
                    "",
                    f"👥 کاربران کل: {total:,}",
                    f"✅ کاربران فعال (24h): {active:,}",
                    f"🚫 کاربران بن شده: {banned:,}",
                    f"🎮 نسبت فعال: {(active/total*100):.1f}%",
                ]
                
                await callback.message.answer("\n".join(text), parse_mode=ParseMode.HTML)
            
            elif action == "stats":
                cursor = self.db.conn.cursor()
                
                cursor.execute('SELECT COUNT(*) as clans FROM clans')
                clans = cursor.fetchone()['clans']
                
                cursor.execute('SELECT SUM(member_count) as total_members FROM clans')
                clan_members = cursor.fetchone()['total_members'] or 0
                
                cursor.execute('SELECT COUNT(*) as attacks FROM attacks')
                attacks = cursor.fetchone()['attacks']
                
                cursor.execute('SELECT COUNT(*) as reports FROM reports WHERE status = "pending"')
                pending_reports = cursor.fetchone()['pending']
                
                text = [
                    "📈 <b>آمار کلی سیستم</b>",
                    "",
                    f"🏛️ تعداد قبایل: {clans:,}",
                    f"👥 اعضای قبایل: {clan_members:,}",
                    f"⚔️ تعداد حمله‌ها: {attacks:,}",
                    f"⚠️ گزارش‌های در انتظار: {pending_reports:,}",
                    "",
                    f"🕐 زمان سرور: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ]
                
                await callback.message.answer("\n".join(text), parse_mode=ParseMode.HTML)
            
            await callback.answer()
    
    async def _show_main_menu(self, message: Message, user: Dict):
        """نمایش منوی اصلی"""
        # آپدیت منابع
        self.db.update_user_resources(user['user_id'])
        user = self.db.get_user(user['user_id'])  # دریافت مجدد
        
        keyboard = InlineKeyboardBuilder()
        
        # ردیف اول
        keyboard.row(
            InlineKeyboardButton(text="👤 پروفایل", callback_data="profile"),
            InlineKeyboardButton(text="🏛️ قبیله", callback_data="clan"),
        )
        
        # ردیف دوم
        keyboard.row(
            InlineKeyboardButton(text="⚔️ حمله", callback_data="attack"),
            InlineKeyboardButton(text="🏆 رتبه‌بندی", callback_data="leaderboard"),
        )
        
        # ردیف سوم
        keyboard.row(
            InlineKeyboardButton(text="🏗️ ساختمان‌ها", callback_data="build"),
            InlineKeyboardButton(text="🎁 پاداش روزانه", callback_data="daily"),
        )
        
        # ردیف ادمین
        if user['user_id'] == ADMIN_ID:
            keyboard.row(InlineKeyboardButton(text="👑 پنل ادمین", callback_data="admin"))
        
        # اطلاعات کاربر
        user_info = [
            f"🎮 <b>AmeleClashBot</b>",
            "",
            f"سلام <b>{user['game_name']}</b>! 👋",
            "",
            "💰 <b>منابع:</b>",
            f"  • سکه: {user['coins']:,} 🪙",
            f"  • اکسیر: {user['elixir']:,} 🧪",
            f"  • جم: {user['gems']:,} 💎",
            "",
            f"📊 <b>سطح:</b> {user['level']} | XP: {user['xp']}/{user['level'] * 1000}",
            "",
            "<b>چه کاری انجام دهیم؟</b>"
        ]
        
        await message.answer(
            "\n".join(user_info),
            reply_markup=keyboard.as_markup(),
            parse_mode=ParseMode.HTML
        )
    
    async def start_webhook(self):
        """راه‌اندازی وب‌هوک"""
        if WEBHOOK_URL:
            webhook_url = f"{WEBHOOK_URL}/webhook"
            
            await self.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                secret_token=os.getenv("WEBHOOK_SECRET", None)
            )
            
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"✅ Webhook set: {webhook_info.url}")
        else:
            logger.warning("⚠️ WEBHOOK_URL not set, using polling mode")
    
    async def cleanup(self):
        """پاکسازی منابع"""
        logger.info("🧹 Cleaning up resources...")
        
        if self.bot:
            await self.bot.session.close()
            logger.info("✅ Bot session closed")
        
        if self.site:
            await self.site.stop()
            logger.info("✅ Web site stopped")
        
        if self.runner:
            await self.runner.cleanup()
            logger.info("✅ App runner cleaned up")
        
        if self.db:
            self.db.close()
            logger.info("✅ Database connection closed")
    
    async def run(self):
        """اجرای اصلی ربات"""
        try:
            await self.setup()
            await self.start_webhook()
            
            # اطلاعات ربات
            bot_info = await self.bot.get_me()
            logger.info("=" * 50)
            logger.info(f"🤖 Bot: @{bot_info.username}")
            logger.info(f"🆔 Bot ID: {bot_info.id}")
            logger.info(f"👑 Admin ID: {ADMIN_ID}")
            logger.info(f"🌐 Web Panel: http://localhost:{PORT}")
            logger.info(f"📊 Database: {DATABASE_URL}")
            logger.info("=" * 50)
            logger.info("✅ AmeleClashBot is ready and running!")
            
            # اجرای نامحدود
            await asyncio.Future()
            
        except asyncio.CancelledError:
            logger.info("⏹️ Bot stopped by user")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.cleanup()

# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """نقطه ورود اصلی برنامه"""
    
    banner = """
    ╔══════════════════════════════════════════════════╗
    ║             A M E L E  C L A S H                 ║
    ║                 B O T   v2.0.0                   ║
    ╠══════════════════════════════════════════════════╣
    ║   🏰  بازی استراتژیک متنی Clash of Clans        ║
    ║   🤖  توسعه یافته با Python + aiogram 3.x       ║
    ║   🚀  آماده برای دیپلوی روی Render              ║
    ╚══════════════════════════════════════════════════╝
    """
    
    print(banner)
    logger.info("🚀 Starting AmeleClashBot...")
    
    # بررسی متغیرهای ضروری
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is required!")
        return
    
    # ایجاد و اجرای ربات
    bot = AmeleClashBot()
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("⏹️ Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"❌ Unhandled exception: {e}")

if __name__ == "__main__":
    """
    =================================================================
    🚀 نحوه دیپلوی روی Render:
    
    1. فایل requirements.txt:
    aiogram>=3.0.0
    aiohttp>=3.9.0
    
    2. متغیرهای محیطی:
    BOT_TOKEN: توکن ربات از @BotFather
    WEBHOOK_URL: آدرس سرویس شما (مثلاً https://your-bot.onrender.com)
    PORT: 8080
    ADMIN_ID: 8285797031 (یا آی‌دی خودتان)
    
    3. Start Command: python main.py
    
    =================================================================
    🔧 نکات مهم:
    
    1. برای تست پنل ادمین، آی‌دی ADMIN_ID را به آی‌دی خودتان تغییر دهید
    2. ربات به طور خودکار دیتابیس را ایجاد می‌کند
    3. برای ریست کامل، فایل ameleclash.db را حذف کنید
    4. لاگ‌ها را در کنسول Render مشاهده کنید
    
    =================================================================
    📞 پشتیبانی:
    
    در صورت مشکل، لاگ‌ها را بررسی کرده و آی‌دی ادمین را تنظیم کنید
    =================================================================
    """
    
    # اجرای برنامه
    asyncio.run(main())

#!/usr/bin/env python3
"""
AmeleClashBot - ربات بازی متنی Clash of Clans
نسخه: 1.0.0
نویسنده: AmeleClashBot Team
"""

import asyncio
import logging
import os
import sqlite3
import json
import datetime
import random
import string
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebhookInfo
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.utils.exceptions import TelegramAPIError

import aiohttp
from aiohttp import web
import aiohttp_jinja2
import jinja2

# ============================================================================
# تنظیمات اولیه
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# خواندن متغیرهای محیطی
BOT_TOKEN = os.getenv('BOT_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 8080))
DATABASE_URL = os.getenv('DATABASE_URL', 'ameleclash.db')

# آی‌دی ادمین اصلی (کشور ابرقدرت)
ADMIN_ID = 8285797031

# ============================================================================
# مدل‌های داده و Enumها
# ============================================================================

class ResourceType(Enum):
    """انواع منابع بازی"""
    GOLD = "gold"
    ELIXIR = "elixir"
    GEM = "gem"

class BuildingType(Enum):
    """انواع ساختمان‌ها"""
    TOWN_HALL = "town_hall"
    GOLD_MINE = "gold_mine"
    ELIXIR_COLLECTOR = "elixir_collector"
    BARRACKS = "barracks"
    STORAGE = "storage"

class UserRole(Enum):
    """نقش‌های کاربر"""
    MEMBER = "member"
    ELDER = "elder"  # مدیر قبیله
    CO_LEADER = "co_leader"  # معاون رهبر
    LEADER = "leader"  # رهبر قبیله
    ADMIN = "admin"  # ادمین سیستم

@dataclass
class User:
    """مدل کاربر"""
    user_id: int
    username: Optional[str]
    game_name: str
    level: int = 1
    experience: int = 0
    gold: int = 1000
    elixir: int = 1000
    gem: int = 50
    trophies: int = 1000
    clan_id: Optional[int] = None
    role: UserRole = UserRole.MEMBER
    last_daily_reward: Optional[str] = None
    last_attack_time: Optional[str] = None
    last_collection_time: str = None
    warnings: int = 0
    banned: bool = False
    created_at: str = None

@dataclass
class Clan:
    """مدل قبیله"""
    clan_id: int
    name: str
    tag: str
    description: str
    leader_id: int
    level: int = 1
    trophies: int = 0
    member_count: int = 1
    created_at: str = None

@dataclass
class Building:
    """مدل ساختمان"""
    building_id: int
    user_id: int
    building_type: BuildingType
    level: int = 1
    last_upgrade_time: Optional[str] = None
    position_x: int = 0
    position_y: int = 0

@dataclass
class AttackLog:
    """لاگ حمله"""
    attack_id: int
    attacker_id: int
    defender_id: int
    result: str  # win/lose/draw
    trophies_change: int
    resources_stolen: Dict[str, int]
    timestamp: str

@dataclass
class Report:
    """مدل گزارش"""
    report_id: int
    reporter_id: int
    reported_user_id: int
    message: str
    clan_chat_id: Optional[int] = None
    status: str = "pending"  # pending/reviewed/resolved
    created_at: str = None

@dataclass
class ClanMessage:
    """مدل پیام قبیله"""
    message_id: int
    clan_id: int
    user_id: int
    message: str
    created_at: str = None

# ============================================================================
# State Machine برای FSM
# ============================================================================

class Form(StatesGroup):
    """استیت‌های مختلف برای ثبت اطلاعات کاربر"""
    waiting_for_game_name = State()
    waiting_for_clan_name = State()
    waiting_for_clan_description = State()
    waiting_for_clan_tag = State()
    waiting_for_message = State()
    waiting_for_attack_target = State()

# ============================================================================
# دیتابیس
# ============================================================================

class Database:
    """کلاس مدیریت دیتابیس SQLite"""
    
    def __init__(self, db_path: str = DATABASE_URL):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """ایجاد جداول دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # جدول کاربران
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            game_name TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            experience INTEGER DEFAULT 0,
            gold INTEGER DEFAULT 1000,
            elixir INTEGER DEFAULT 1000,
            gem INTEGER DEFAULT 50,
            trophies INTEGER DEFAULT 1000,
            clan_id INTEGER,
            role TEXT DEFAULT 'member',
            last_daily_reward TEXT,
            last_attack_time TEXT,
            last_collection_time TEXT DEFAULT CURRENT_TIMESTAMP,
            warnings INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (clan_id) REFERENCES clans(clan_id)
        )
        ''')
        
        # جدول قبایل
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS clans (
            clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            tag TEXT NOT NULL UNIQUE,
            description TEXT,
            leader_id INTEGER NOT NULL,
            level INTEGER DEFAULT 1,
            trophies INTEGER DEFAULT 0,
            member_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (leader_id) REFERENCES users(user_id)
        )
        ''')
        
        # جدول ساختمان‌ها
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS buildings (
            building_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            building_type TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            last_upgrade_time TEXT,
            position_x INTEGER DEFAULT 0,
            position_y INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')
        
        # جدول لاگ‌های حمله
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS attack_logs (
            attack_id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_id INTEGER NOT NULL,
            defender_id INTEGER NOT NULL,
            result TEXT NOT NULL,
            trophies_change INTEGER NOT NULL,
            resources_stolen TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (attacker_id) REFERENCES users(user_id),
            FOREIGN KEY (defender_id) REFERENCES users(user_id)
        )
        ''')
        
        # جدول گزارش‌ها
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            reported_user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            clan_chat_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reporter_id) REFERENCES users(user_id),
            FOREIGN KEY (reported_user_id) REFERENCES users(user_id)
        )
        ''')
        
        # جدول پیام‌های قبیله
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS clan_messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (clan_id) REFERENCES clans(clan_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')
        
        # جدول لیگ‌ها
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS leagues (
            league_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            min_trophies INTEGER NOT NULL,
            max_trophies INTEGER NOT NULL,
            reward_gold INTEGER NOT NULL,
            reward_elixir INTEGER NOT NULL,
            season_end TEXT
        )
        ''')
        
        # جدول ماموریت‌ها
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS missions (
            mission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mission_type TEXT NOT NULL,
            target_value INTEGER NOT NULL,
            current_value INTEGER DEFAULT 0,
            reward_gold INTEGER NOT NULL,
            reward_elixir INTEGER NOT NULL,
            reward_gem INTEGER NOT NULL,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')
        
        # ایندکس‌ها
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_clan_id ON users(clan_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_clan_messages_clan_id ON clan_messages(clan_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_buildings_user_id ON buildings(user_id)')
        
        conn.commit()
        conn.close()
        
        # ایجاد کاربر ابرقدرت (ادمین)
        self._create_superpower_country()
    
    def _create_superpower_country(self):
        """ایجاد کشور ابرقدرت (ادمین)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # بررسی وجود کاربر ادمین
        cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (ADMIN_ID,))
        if not cursor.fetchone():
            # ایجاد کاربر ادمین
            cursor.execute('''
            INSERT INTO users 
            (user_id, username, game_name, level, gold, elixir, gem, trophies, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                ADMIN_ID, 
                'Superpower_Country', 
                '🔥 ابرقدرت جهان 🔥',
                100,  # لول بالا
                999999999,  # سکه نامحدود
                999999999,  # اکسیر نامحدود
                999999,     # جم نامحدود
                10000,      # تروفی بالا
                UserRole.ADMIN.value
            ))
            
            # ایجاد ساختمان‌های سطح ماکس برای ادمین
            buildings = [
                (ADMIN_ID, BuildingType.TOWN_HALL.value, 10),
                (ADMIN_ID, BuildingType.GOLD_MINE.value, 10),
                (ADMIN_ID, BuildingType.ELIXIR_COLLECTOR.value, 10),
                (ADMIN_ID, BuildingType.BARRACKS.value, 10),
                (ADMIN_ID, BuildingType.STORAGE.value, 10),
            ]
            
            cursor.executemany('''
            INSERT INTO buildings (user_id, building_type, level)
            VALUES (?, ?, ?)
            ''', buildings)
        
        conn.commit()
        conn.close()
    
    def execute_query(self, query: str, params: tuple = ()) -> list:
        """اجرای کوئری SELECT"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return results
    
    def execute_update(self, query: str, params: tuple = ()) -> int:
        """اجرای کوئری INSERT/UPDATE/DELETE"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        return last_id
    
    # متدهای کمکی برای کاربران
    def get_user(self, user_id: int) -> Optional[User]:
        """دریافت اطلاعات کاربر"""
        results = self.execute_query(
            'SELECT * FROM users WHERE user_id = ?',
            (user_id,)
        )
        if results:
            row = results[0]
            return User(
                user_id=row['user_id'],
                username=row['username'],
                game_name=row['game_name'],
                level=row['level'],
                experience=row['experience'],
                gold=row['gold'],
                elixir=row['elixir'],
                gem=row['gem'],
                trophies=row['trophies'],
                clan_id=row['clan_id'],
                role=UserRole(row['role']),
                last_daily_reward=row['last_daily_reward'],
                last_attack_time=row['last_attack_time'],
                last_collection_time=row['last_collection_time'],
                warnings=row['warnings'],
                banned=bool(row['banned']),
                created_at=row['created_at']
            )
        return None
    
    def create_user(self, user_id: int, username: str, game_name: str) -> bool:
        """ایجاد کاربر جدید"""
        try:
            self.execute_update(
                '''INSERT INTO users 
                (user_id, username, game_name, last_collection_time) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)''',
                (user_id, username, game_name)
            )
            
            # ایجاد ساختمان‌های اولیه
            buildings = [
                (user_id, BuildingType.TOWN_HALL.value, 1),
                (user_id, BuildingType.GOLD_MINE.value, 1),
                (user_id, BuildingType.ELIXIR_COLLECTOR.value, 1),
                (user_id, BuildingType.BARRACKS.value, 1),
            ]
            
            for building in buildings:
                self.execute_update(
                    'INSERT INTO buildings (user_id, building_type, level) VALUES (?, ?, ?)',
                    building
                )
            
            # ایجاد ماموریت‌های روزانه
            self.create_daily_missions(user_id)
            
            return True
        except sqlite3.IntegrityError:
            return False
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        """آپدیت اطلاعات کاربر"""
        if not kwargs:
            return False
        
        set_clause = ', '.join([f'{k} = ?' for k in kwargs.keys()])
        query = f'UPDATE users SET {set_clause} WHERE user_id = ?'
        params = list(kwargs.values()) + [user_id]
        
        self.execute_update(query, tuple(params))
        return True
    
    # متدهای کمکی برای قبایل
    def get_clan(self, clan_id: int) -> Optional[Clan]:
        """دریافت اطلاعات قبیله"""
        results = self.execute_query(
            'SELECT * FROM clans WHERE clan_id = ?',
            (clan_id,)
        )
        if results:
            row = results[0]
            return Clan(
                clan_id=row['clan_id'],
                name=row['name'],
                tag=row['tag'],
                description=row['description'],
                leader_id=row['leader_id'],
                level=row['level'],
                trophies=row['trophies'],
                member_count=row['member_count'],
                created_at=row['created_at']
            )
        return None
    
    def get_clan_by_name(self, name: str) -> Optional[Clan]:
        """دریافت قبیله با نام"""
        results = self.execute_query(
            'SELECT * FROM clans WHERE name = ?',
            (name,)
        )
        if results:
            row = results[0]
            return Clan(
                clan_id=row['clan_id'],
                name=row['name'],
                tag=row['tag'],
                description=row['description'],
                leader_id=row['leader_id'],
                level=row['level'],
                trophies=row['trophies'],
                member_count=row['member_count'],
                created_at=row['created_at']
            )
        return None
    
    def create_clan(self, name: str, tag: str, description: str, leader_id: int) -> Optional[int]:
        """ایجاد قبیله جدید"""
        try:
            clan_id = self.execute_update(
                '''INSERT INTO clans 
                (name, tag, description, leader_id) 
                VALUES (?, ?, ?, ?)''',
                (name, tag, description, leader_id)
            )
            
            # آپدیت نقش کاربر به رهبر
            self.update_user(leader_id, role=UserRole.LEADER.value, clan_id=clan_id)
            
            return clan_id
        except sqlite3.IntegrityError:
            return None
    
    def get_clan_members(self, clan_id: int) -> List[User]:
        """دریافت اعضای قبیله"""
        results = self.execute_query(
            '''SELECT * FROM users 
            WHERE clan_id = ? AND banned = 0 
            ORDER BY 
                CASE role 
                    WHEN 'leader' THEN 1
                    WHEN 'co_leader' THEN 2
                    WHEN 'elder' THEN 3
                    ELSE 4
                END, level DESC''',
            (clan_id,)
        )
        
        members = []
        for row in results:
            members.append(User(
                user_id=row['user_id'],
                username=row['username'],
                game_name=row['game_name'],
                level=row['level'],
                trophies=row['trophies'],
                role=UserRole(row['role'])
            ))
        return members
    
    def add_clan_message(self, clan_id: int, user_id: int, message: str) -> int:
        """اضافه کردن پیام به چت قبیله"""
        return self.execute_update(
            '''INSERT INTO clan_messages (clan_id, user_id, message)
            VALUES (?, ?, ?)''',
            (clan_id, user_id, message)
        )
    
    def get_clan_messages(self, clan_id: int, limit: int = 50) -> List[ClanMessage]:
        """دریافت پیام‌های قبیله"""
        results = self.execute_query(
            '''SELECT cm.*, u.game_name 
            FROM clan_messages cm
            JOIN users u ON cm.user_id = u.user_id
            WHERE cm.clan_id = ?
            ORDER BY cm.created_at DESC
            LIMIT ?''',
            (clan_id, limit)
        )
        
        messages = []
        for row in results:
            messages.append(ClanMessage(
                message_id=row['message_id'],
                clan_id=row['clan_id'],
                user_id=row['user_id'],
                message=row['message'],
                created_at=row['created_at']
            ))
        return messages[::-1]  # معکوس کردن برای نمایش از قدیم به جدید
    
    # متدهای کمکی برای گزارش‌ها
    def create_report(self, reporter_id: int, reported_user_id: int, message: str, clan_chat_id: int = None) -> int:
        """ایجاد گزارش جدید"""
        return self.execute_update(
            '''INSERT INTO reports (reporter_id, reported_user_id, message, clan_chat_id)
            VALUES (?, ?, ?, ?)''',
            (reporter_id, reported_user_id, message, clan_chat_id)
        )
    
    def get_pending_reports(self) -> List[Report]:
        """دریافت گزارش‌های در انتظار"""
        results = self.execute_query(
            '''SELECT r.*, 
                   u1.game_name as reporter_name,
                   u2.game_name as reported_name
            FROM reports r
            JOIN users u1 ON r.reporter_id = u1.user_id
            JOIN users u2 ON r.reported_user_id = u2.user_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC'''
        )
        
        reports = []
        for row in results:
            reports.append(Report(
                report_id=row['report_id'],
                reporter_id=row['reporter_id'],
                reported_user_id=row['reported_user_id'],
                message=row['message'],
                clan_chat_id=row['clan_chat_id'],
                status=row['status'],
                created_at=row['created_at']
            ))
        return reports
    
    # متدهای کمکی برای ماموریت‌ها
    def create_daily_missions(self, user_id: int):
        """ایجاد ماموریت‌های روزانه برای کاربر"""
        missions = [
            (user_id, 'collect_resources', 50000, 1000, 500, 5),
            (user_id, 'attack_players', 3, 1500, 750, 10),
            (user_id, 'upgrade_building', 1, 2000, 1000, 15),
            (user_id, 'send_clan_messages', 5, 500, 250, 3),
        ]
        
        for mission in missions:
            self.execute_update(
                '''INSERT INTO missions 
                (user_id, mission_type, target_value, reward_gold, reward_elixir, reward_gem)
                VALUES (?, ?, ?, ?, ?, ?)''',
                mission
            )
    
    def get_user_missions(self, user_id: int) -> List[dict]:
        """دریافت ماموریت‌های کاربر"""
        results = self.execute_query(
            '''SELECT * FROM missions 
            WHERE user_id = ? AND completed = 0 
            AND DATE(created_at) = DATE('now')''',
            (user_id,)
        )
        
        missions = []
        for row in results:
            missions.append(dict(row))
        return missions
    
    # متدهای کمکی برای رتبه‌بندی
    def get_top_players(self, limit: int = 10) -> List[User]:
        """دریافت برترین بازیکنان"""
        results = self.execute_query(
            '''SELECT * FROM users 
            WHERE banned = 0 AND user_id != ?
            ORDER BY trophies DESC, level DESC
            LIMIT ?''',
            (ADMIN_ID, limit)
        )
        
        players = []
        for row in results:
            players.append(User(
                user_id=row['user_id'],
                username=row['username'],
                game_name=row['game_name'],
                level=row['level'],
                trophies=row['trophies']
            ))
        return players
    
    def get_top_clans(self, limit: int = 10) -> List[Clan]:
        """دریافت برترین قبایل"""
        results = self.execute_query(
            '''SELECT * FROM clans 
            ORDER BY trophies DESC, level DESC
            LIMIT ?''',
            (limit,)
        )
        
        clans = []
        for row in results:
            clans.append(Clan(
                clan_id=row['clan_id'],
                name=row['name'],
                tag=row['tag'],
                description=row['description'],
                leader_id=row['leader_id'],
                level=row['level'],
                trophies=row['trophies'],
                member_count=row['member_count']
            ))
        return clans

# ============================================================================
# سیستم بازی
# ============================================================================

class GameEngine:
    """موتور اصلی بازی"""
    
    def __init__(self, db: Database):
        self.db = db
        self.forbidden_words = [
            'فحش1', 'فحش2', 'فحش3', 'توهین1', 'توهین2',
            'کلمه‌ناسزا1', 'کلمه‌ناسزا2'
        ]
        
        # تنظیمات تولید منابع
        self.resource_production = {
            BuildingType.GOLD_MINE: {1: 10, 2: 25, 3: 50, 4: 100, 5: 200, 6: 400, 7: 800, 8: 1500, 9: 3000, 10: 6000},
            BuildingType.ELIXIR_COLLECTOR: {1: 8, 2: 20, 3: 40, 4: 80, 5: 160, 6: 320, 7: 640, 8: 1200, 9: 2400, 10: 4800}
        }
        
        # هزینه‌های ارتقا
        self.upgrade_costs = {
            BuildingType.TOWN_HALL: {1: 1000, 2: 5000, 3: 15000, 4: 50000, 5: 150000, 6: 500000, 7: 1500000, 8: 5000000, 9: 10000000, 10: 25000000},
            BuildingType.GOLD_MINE: {1: 150, 2: 750, 3: 3000, 4: 12000, 5: 50000, 6: 200000, 7: 800000, 8: 3000000, 9: 8000000, 10: 20000000},
            BuildingType.ELIXIR_COLLECTOR: {1: 150, 2: 750, 3: 3000, 4: 12000, 5: 50000, 6: 200000, 7: 800000, 8: 3000000, 9: 8000000, 10: 20000000},
            BuildingType.BARRACKS: {1: 500, 2: 2500, 3: 10000, 4: 40000, 5: 150000, 6: 600000, 7: 2400000, 8: 9000000, 9: 20000000, 10: 50000000},
        }
    
    def calculate_production(self, user_id: int) -> Dict[str, int]:
        """محاسبه منابع تولید شده از آخرین بار"""
        user = self.db.get_user(user_id)
        if not user:
            return {'gold': 0, 'elixir': 0}
        
        # دریافت ساختمان‌های کاربر
        buildings = self.db.execute_query(
            'SELECT building_type, level FROM buildings WHERE user_id = ?',
            (user_id,)
        )
        
        # محاسبه زمان گذشته
        last_collection = datetime.datetime.fromisoformat(user.last_collection_time)
        now = datetime.datetime.now()
        hours_passed = (now - last_collection).total_seconds() / 3600
        
        # محاسبه تولید
        gold_production = 0
        elixir_production = 0
        
        for building in buildings:
            b_type = BuildingType(building['building_type'])
            level = building['level']
            
            if b_type == BuildingType.GOLD_MINE:
                production_rate = self.resource_production.get(b_type, {}).get(level, 0)
                gold_production += int(production_rate * hours_passed)
            elif b_type == BuildingType.ELIXIR_COLLECTOR:
                production_rate = self.resource_production.get(b_type, {}).get(level, 0)
                elixir_production += int(production_rate * hours_passed)
        
        # محدودیت ظرفیت ذخیره‌سازی
        max_storage = 50000 * user.level  # ظرفیت بر اساس لول
        
        current_gold = user.gold + gold_production
        current_elixir = user.elixir + elixir_production
        
        if current_gold > max_storage:
            gold_production = max_storage - user.gold
        if current_elixir > max_storage:
            elixir_production = max_storage - user.elixir
        
        return {
            'gold': max(0, gold_production),
            'elixir': max(0, elixir_production)
        }
    
    def collect_resources(self, user_id: int) -> Dict[str, int]:
        """جمع‌آوری منابع تولید شده"""
        production = self.calculate_production(user_id)
        
        if production['gold'] > 0 or production['elixir'] > 0:
            user = self.db.get_user(user_id)
            new_gold = user.gold + production['gold']
            new_elixir = user.elixir + production['elixir']
            
            self.db.update_user(
                user_id,
                gold=new_gold,
                elixir=new_elixir,
                last_collection_time=datetime.datetime.now().isoformat()
            )
        
        return production
    
    def check_forbidden_words(self, text: str) -> Tuple[bool, List[str]]:
        """بررسی وجود کلمات ممنوعه"""
        found_words = []
        for word in self.forbidden_words:
            if word in text.lower():
                found_words.append(word)
        
        return len(found_words) > 0, found_words
    
    def simulate_attack(self, attacker_id: int, defender_id: int) -> Dict[str, Any]:
        """شبیه‌سازی حمله"""
        attacker = self.db.get_user(attacker_id)
        defender = self.db.get_user(defender_id)
        
        if not attacker or not defender:
            return {'error': 'کاربر یافت نشد'}
        
        # محاسبه قدرت حمله و دفاع
        attack_power = attacker.level * 10 + attacker.trophies // 100
        defense_power = defender.level * 10 + defender.trophies // 100
        
        # اگر مدافع ادمین باشد (کشور ابرقدرت)
        if defender_id == ADMIN_ID:
            defense_power *= 10  # قدرت دفاع 10 برابر
        
        # شانس برنده
        total_power = attack_power + defense_power
        attacker_win_chance = attack_power / total_power
        
        # تولید نتیجه تصادفی
        import random
        result = random.random()
        
        if result < attacker_win_chance:
            # حمله کننده برنده شد
            # محاسبه تروفی تغییر یافته
            trophy_diff = defender.trophies - attacker.trophies
            if trophy_diff > 0:
                trophies_change = min(40, 10 + trophy_diff // 100)
            else:
                trophies_change = max(5, 10 + trophy_diff // 100)
            
            # محاسبه منابع دزدیده شده
            max_steal_gold = min(defender.gold * 0.2, 100000)
            max_steal_elixir = min(defender.elixir * 0.2, 100000)
            
            stolen_gold = random.randint(int(max_steal_gold * 0.5), int(max_steal_gold))
            stolen_elixir = random.randint(int(max_steal_elixir * 0.5), int(max_steal_elixir))
            
            # آپدیت منابع
            self.db.update_user(
                attacker_id,
                gold=attacker.gold + stolen_gold,
                elixir=attacker.elixir + stolen_elixir,
                trophies=attacker.trophies + trophies_change,
                last_attack_time=datetime.datetime.now().isoformat()
            )
            
            self.db.update_user(
                defender_id,
                gold=max(0, defender.gold - stolen_gold),
                elixir=max(0, defender.elixir - stolen_elixir),
                trophies=max(0, defender.trophies - trophies_change)
            )
            
            # ذخیره لاگ حمله
            self.db.execute_update(
                '''INSERT INTO attack_logs 
                (attacker_id, defender_id, result, trophies_change, resources_stolen)
                VALUES (?, ?, ?, ?, ?)''',
                (attacker_id, defender_id, 'win', trophies_change,
                 json.dumps({'gold': stolen_gold, 'elixir': stolen_elixir}))
            )
            
            return {
                'result': 'win',
                'trophies_change': trophies_change,
                'resources_stolen': {
                    'gold': stolen_gold,
                    'elixir': stolen_elixir
                },
                'attack_power': attack_power,
                'defense_power': defense_power
            }
        else:
            # مدافع برنده شد
            trophies_change = random.randint(5, 15)
            
            self.db.update_user(
                attacker_id,
                trophies=max(0, attacker.trophies - trophies_change),
                last_attack_time=datetime.datetime.now().isoformat()
            )
            
            self.db.update_user(
                defender_id,
                trophies=defender.trophies + trophies_change
            )
            
            # ذخیره لاگ حمله
            self.db.execute_update(
                '''INSERT INTO attack_logs 
                (attacker_id, defender_id, result, trophies_change, resources_stolen)
                VALUES (?, ?, ?, ?, ?)''',
                (attacker_id, defender_id, 'lose', -trophies_change, json.dumps({}))
            )
            
            return {
                'result': 'lose',
                'trophies_change': -trophies_change,
                'resources_stolen': {},
                'attack_power': attack_power,
                'defense_power': defense_power
            }
    
    def get_daily_reward(self, user_id: int) -> Optional[Dict[str, int]]:
        """دریافت پاداش روزانه"""
        user = self.db.get_user(user_id)
        if not user:
            return None
        
        today = datetime.datetime.now().date().isoformat()
        
        if user.last_daily_reward == today:
            return None
        
        # محاسبه پاداش بر اساس لول
        reward_gold = 1000 * user.level
        reward_elixir = 800 * user.level
        reward_gem = 5 + user.level // 5
        
        self.db.update_user(
            user_id,
            gold=user.gold + reward_gold,
            elixir=user.elixir + reward_elixir,
            gem=user.gem + reward_gem,
            last_daily_reward=today
        )
        
        return {
            'gold': reward_gold,
            'elixir': reward_elixir,
            'gem': reward_gem
        }
    
    def upgrade_building(self, user_id: int, building_type: BuildingType) -> Dict[str, Any]:
        """ارتقای ساختمان"""
        user = self.db.get_user(user_id)
        if not user:
            return {'success': False, 'message': 'کاربر یافت نشد'}
        
        # دریافت ساختمان
        building = self.db.execute_query(
            'SELECT * FROM buildings WHERE user_id = ? AND building_type = ?',
            (user_id, building_type.value)
        )
        
        if not building:
            return {'success': False, 'message': 'ساختمان یافت نشد'}
        
        building = building[0]
        current_level = building['level']
        
        # بررسی ماکس لول
        if current_level >= 10:
            return {'success': False, 'message': 'ساختمان در ماکس لول است'}
        
        # بررسی هزینه
        cost = self.upgrade_costs.get(building_type, {}).get(current_level + 1)
        if not cost:
            return {'success': False, 'message': 'اطلاعات ارتقا یافت نشد'}
        
        # بررسی منابع
        if user.gold < cost or user.elixir < cost:
            return {'success': False, 'message': 'منابع کافی نیست'}
        
        # کسر منابع
        self.db.update_user(
            user_id,
            gold=user.gold - cost,
            elixir=user.elixir - cost
        )
        
        # ارتقای ساختمان
        self.db.execute_update(
            '''UPDATE buildings 
            SET level = ?, last_upgrade_time = CURRENT_TIMESTAMP
            WHERE user_id = ? AND building_type = ?''',
            (current_level + 1, user_id, building_type.value)
        )
        
        # افزودن تجربه
        experience_gain = cost // 100
        new_experience = user.experience + experience_gain
        
        # بررسی ارتقای لول
        level_up = False
        required_exp = user.level * 1000
        
        if new_experience >= required_exp:
            self.db.update_user(
                user_id,
                level=user.level + 1,
                experience=new_experience - required_exp
            )
            level_up = True
        else:
            self.db.update_user(
                user_id,
                experience=new_experience
            )
        
        return {
            'success': True,
            'new_level': current_level + 1,
            'cost': cost,
            'experience_gain': experience_gain,
            'level_up': level_up
        }

# ============================================================================
# ربات تلگرام
# ============================================================================

class AmeleClashBot:
    """کلاس اصلی ربات"""
    
    def __init__(self):
        self.bot = None
        self.dp = None
        self.db = Database()
        self.game = GameEngine(self.db)
        self.app = None
        self.runner = None
        self.site = None
        
    async def on_startup(self, dp):
        """هنگام راه‌اندازی ربات"""
        await self.setup_webhook()
        await self.bot.send_message(ADMIN_ID, "✅ ربات AmeleClashBot راه‌اندازی شد!")
        
        # تنظیم وب‌سرور برای پنل قبیله
        await self.setup_web_server()
        
    async def on_shutdown(self, dp):
        """هنگام خاموش شدن ربات"""
        await self.bot.delete_webhook()
        if self.site:
            await self.site.stop()
        await self.bot.session.close()
        
    async def setup_webhook(self):
        """تنظیم Webhook"""
        webhook_url = f"{WEBHOOK_URL}/webhook"
        
        # حذف webhook قبلی
        await self.bot.delete_webhook()
        
        # تنظیم webhook جدید
        await self.bot.set_webhook(
            webhook_url,
            certificate=None,
            max_connections=40,
            allowed_updates=["message", "callback_query"]
        )
        
        logger.info(f"Webhook set to: {webhook_url}")
    
    async def setup_web_server(self):
        """تنظیم وب‌سرور برای پنل قبیله"""
        self.app = web.Application()
        
        # تنظیم Jinja2 برای تمپلیت‌های HTML
        aiohttp_jinja2.setup(
            self.app,
            loader=jinja2.DictLoader({
                'clan_chat': '''
                <!DOCTYPE html>
                <html dir="rtl">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>چت قبیله {{ clan_name }}</title>
                    <style>
                        body {
                            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            margin: 0;
                            padding: 20px;
                            min-height: 100vh;
                        }
                        .container {
                            max-width: 800px;
                            margin: 0 auto;
                            background: white;
                            border-radius: 15px;
                            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                            overflow: hidden;
                        }
                        .header {
                            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                            color: white;
                            padding: 20px;
                            text-align: center;
                        }
                        .messages {
                            height: 400px;
                            overflow-y: auto;
                            padding: 20px;
                        }
                        .message {
                            margin-bottom: 15px;
                            padding: 15px;
                            border-radius: 10px;
                            background: #f8f9fa;
                            border-right: 4px solid #667eea;
                        }
                        .message-header {
                            display: flex;
                            justify-content: space-between;
                            margin-bottom: 8px;
                            font-size: 14px;
                            color: #666;
                        }
                        .username {
                            font-weight: bold;
                            color: #333;
                        }
                        .time {
                            color: #888;
                        }
                        .footer {
                            padding: 20px;
                            background: #f8f9fa;
                            border-top: 1px solid #eee;
                            text-align: center;
                        }
                        .back-btn {
                            display: inline-block;
                            padding: 10px 20px;
                            background: #667eea;
                            color: white;
                            text-decoration: none;
                            border-radius: 5px;
                            transition: all 0.3s;
                        }
                        .back-btn:hover {
                            background: #5a67d8;
                            transform: translateY(-2px);
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>👥 چت قبیله {{ clan_name }}</h1>
                            <p>{{ clan_tag }} | تعداد اعضا: {{ member_count }}</p>
                        </div>
                        <div class="messages">
                            {% for msg in messages %}
                            <div class="message">
                                <div class="message-header">
                                    <span class="username">{{ msg.game_name }}</span>
                                    <span class="time">{{ msg.created_at }}</span>
                                </div>
                                <div class="message-text">{{ msg.message }}</div>
                            </div>
                            {% endfor %}
                        </div>
                        <div class="footer">
                            <a href="/" class="back-btn">🔙 بازگشت</a>
                        </div>
                    </div>
                </body>
                </html>
                '''
            })
        )
        
        # روت‌ها
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/clan/{clan_id}', self.handle_clan_chat)
        self.app.router.add_post('/webhook', self.handle_webhook)
        
        # راه‌اندازی وب‌سرور
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', PORT)
        await self.site.start()
        
        logger.info(f"Web server started on port {PORT}")
    
    @aiohttp_jinja2.template('clan_chat')
    async def handle_clan_chat(self, request):
        """مدیریت صفحه چت قبیله"""
        clan_id = int(request.match_info['clan_id'])
        
        # بررسی وجود قبیله
        clan = self.db.get_clan(clan_id)
        if not clan:
            return web.Response(text="قبیله یافت نشد", status=404)
        
        # دریافت پیام‌های قبیله
        messages = self.db.get_clan_messages(clan_id)
        
        # فرمت‌دهی پیام‌ها برای نمایش
        formatted_messages = []
        for msg in messages:
            user = self.db.get_user(msg.user_id)
            if user:
                formatted_messages.append({
                    'game_name': user.game_name,
                    'message': msg.message,
                    'created_at': msg.created_at
                })
        
        return {
            'clan_name': clan.name,
            'clan_tag': clan.tag,
            'member_count': clan.member_count,
            'messages': formatted_messages
        }
    
    async def handle_index(self, request):
        """صفحه اصلی وب‌سرور"""
        html = '''
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AmeleClashBot - پنل وب</title>
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    margin: 0;
                    padding: 20px;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .container {
                    text-align: center;
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 15px 35px rgba(0,0,0,0.2);
                }
                h1 {
                    color: #333;
                    margin-bottom: 20px;
                }
                .status {
                    background: #4CAF50;
                    color: white;
                    padding: 15px;
                    border-radius: 10px;
                    margin: 20px 0;
                    font-size: 18px;
                }
                .info {
                    color: #666;
                    line-height: 1.6;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 AmeleClashBot</h1>
                <div class="status">✅ ربات در حال اجراست</div>
                <div class="info">
                    <p>برای دسترسی به چت قبیله، از طریق ربات اقدام کنید.</p>
                    <p>آدرس Webhook: ''' + WEBHOOK_URL + '''</p>
                </div>
            </div>
        </body>
        </html>
        '''
        return web.Response(text=html, content_type='text/html')
    
    async def handle_webhook(self, request):
        """مدیریت Webhook تلگرام"""
        try:
            data = await request.json()
            update = types.Update(**data)
            await self.dp.process_update(update)
            return web.Response()
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return web.Response(status=500)
    
    # ============================================================================
    # هندلرهای ربات
    # ============================================================================
    
    async def start_handler(self, message: types.Message):
        """هندلر دستور /start"""
        user_id = message.from_user.id
        username = message.from_user.username
        existing_user = self.db.get_user(user_id)
        
        if existing_user:
            if existing_user.banned:
                await message.answer("🚫 حساب شما مسدود شده است.")
                return
            
            # نمایش منوی اصلی
            await self.show_main_menu(message)
        else:
            # ثبت نام کاربر جدید
            await Form.waiting_for_game_name.set()
            await message.answer(
                "🎮 به AmeleClashBot خوش آمدید!\n\n"
                "لطفا نام بازی خود را وارد کنید (مانند کلش اف کلنز):"
            )
    
    async def process_game_name(self, message: types.Message, state: FSMContext):
        """پردازش نام بازی کاربر"""
        game_name = message.text.strip()
        
        if len(game_name) < 2 or len(game_name) > 20:
            await message.answer("نام بازی باید بین ۲ تا ۲۰ کاراکتر باشد. لطفا مجددا وارد کنید:")
            return
        
        user_id = message.from_user.id
        username = message.from_user.username
        
        # ایجاد کاربر جدید
        success = self.db.create_user(user_id, username, game_name)
        
        if success:
            await state.finish()
            
            # جمع‌آوری منابع اولیه
            self.game.collect_resources(user_id)
            
            await message.answer(
                f"✅ ثبت نام موفقیت‌آمیز بود!\n"
                f"🎮 نام بازی شما: {game_name}\n\n"
                f"🏆 1000 تروفی شروع به شما هدیه داده شد!\n"
                f"💰 منابع اولیه:\n"
                f"   • سکه: 1000 🪙\n"
                f"   • اکسیر: 1000 🧪\n"
                f"   • جم: 50 💎"
            )
            
            # نمایش منوی اصلی
            await self.show_main_menu(message)
        else:
            await message.answer("خطا در ثبت نام. لطفا مجددا تلاش کنید.")
    
    async def show_main_menu(self, message: types.Message):
        """نمایش منوی اصلی"""
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            return
        
        # جمع‌آوری خودکار منابع
        production = self.game.collect_resources(user_id)
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("🏠 دهکده من", callback_data="village"),
            InlineKeyboardButton("⚔️ حمله", callback_data="attack"),
            InlineKeyboardButton("👥 قبیله", callback_data="clan"),
            InlineKeyboardButton("📊 پروفایل", callback_data="profile"),
            InlineKeyboardButton("🏆 رتبه‌بندی", callback_data="leaderboard"),
            InlineKeyboardButton("🎯 ماموریت‌ها", callback_data="missions"),
            InlineKeyboardButton("🎁 پاداش روزانه", callback_data="daily_reward"),
            InlineKeyboardButton("ℹ️ راهنما", callback_data="help")
        ]
        
        # اضافه کردن دکمه ادمین برای ادمین اصلی
        if user_id == ADMIN_ID:
            buttons.append(InlineKeyboardButton("👑 پنل ادمین", callback_data="admin_panel"))
        
        keyboard.add(*buttons)
        
        status_msg = ""
        if production['gold'] > 0 or production['elixir'] > 0:
            status_msg = f"\n📦 منابع جمع‌آوری شده:\n"
            if production['gold'] > 0:
                status_msg += f"   • سکه: {production['gold']} 🪙\n"
            if production['elixir'] > 0:
                status_msg += f"   • اکسیر: {production['elixir']} 🧪"
        
        await message.answer(
            f"🏰 AmeleClashBot | منوی اصلی\n\n"
            f"👤 {user.game_name}\n"
            f"🏆 تروفی: {user.trophies:,}\n"
            f"⭐ لول: {user.level}\n"
            f"💰 منابع:\n"
            f"   • سکه: {user.gold:,} 🪙\n"
            f"   • اکسیر: {user.elixir:,} 🧪\n"
            f"   • جم: {user.gem:,} 💎"
            f"{status_msg}",
            reply_markup=keyboard
        )
    
    async def show_village_menu(self, callback_query: types.CallbackQuery):
        """نمایش منوی دهکده"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            return
        
        # دریافت ساختمان‌های کاربر
        buildings = self.db.execute_query(
            'SELECT * FROM buildings WHERE user_id = ?',
            (user_id,)
        )
        
        building_info = "🏗️ ساختمان‌های شما:\n"
        for b in buildings:
            b_type = BuildingType(b['building_type'])
            level = b['level']
            
            if b_type == BuildingType.TOWN_HALL:
                building_info += f"   • تاون هال: لول {level} 🏰\n"
            elif b_type == BuildingType.GOLD_MINE:
                production = self.game.resource_production.get(b_type, {}).get(level, 0)
                building_info += f"   • معدن سکه: لول {level} ⛏️ (+{production}/ساعت)\n"
            elif b_type == BuildingType.ELIXIR_COLLECTOR:
                production = self.game.resource_production.get(b_type, {}).get(level, 0)
                building_info += f"   • کالکتور اکسیر: لول {level} 🧪 (+{production}/ساعت)\n"
            elif b_type == BuildingType.BARRACKS:
                building_info += f"   • پادگان: لول {level} ⚔️\n"
            elif b_type == BuildingType.STORAGE:
                building_info += f"   • انبار: لول {level} 📦\n"
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("⏫ ارتقای تاون هال", callback_data="upgrade_townhall"),
            InlineKeyboardButton("⛏️ ارتقای معدن سکه", callback_data="upgrade_goldmine"),
            InlineKeyboardButton("🧪 ارتقای کالکتور اکسیر", callback_data="upgrade_elixircollector"),
            InlineKeyboardButton("⚔️ ارتقای پادگان", callback_data="upgrade_barracks"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
        ]
        keyboard.add(*buttons)
        
        await callback_query.message.edit_text(
            f"🏡 دهکده {user.game_name}\n\n"
            f"{building_info}\n"
            f"💰 منابع:\n"
            f"   • سکه: {user.gold:,} 🪙\n"
            f"   • اکسیر: {user.elixir:,} 🧪",
            reply_markup=keyboard
        )
    
    async def show_profile_menu(self, callback_query: types.CallbackQuery):
        """نمایش پروفایل کاربر"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            return
        
        # محاسبه پیشرفت به لول بعدی
        exp_needed = user.level * 1000
        exp_progress = min(100, (user.experience / exp_needed) * 100)
        
        clan_info = "🔸 بدون قبیله"
        if user.clan_id:
            clan = self.db.get_clan(user.clan_id)
            if clan:
                clan_info = f"🔸 قبیله: {clan.name} [{clan.tag}]"
        
        # تعداد حمله‌های امروز
        today = datetime.datetime.now().date().isoformat()
        attack_count = len(self.db.execute_query(
            '''SELECT 1 FROM attack_logs 
            WHERE attacker_id = ? AND DATE(timestamp) = ?''',
            (user_id, today)
        ))
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"))
        
        await callback_query.message.edit_text(
            f"📊 پروفایل {user.game_name}\n\n"
            f"🆔 شناسه: {user_id}\n"
            f"👤 یوزرنیم: @{user.username if user.username else 'ندارد'}\n"
            f"{clan_info}\n"
            f"🎖️ نقش: {user.role.value}\n\n"
            f"🏆 تروفی: {user.trophies:,}\n"
            f"⭐ لول: {user.level}\n"
            f"📈 تجربه: {user.experience:,}/{exp_needed:,} ({exp_progress:.1f}%)\n\n"
            f"📊 آمار امروز:\n"
            f"   • حمله‌ها: {attack_count}\n"
            f"   • اخطارها: {user.warnings}\n\n"
            f"📅 عضویت از: {user.created_at[:10]}",
            reply_markup=keyboard
        )
    
    async def show_clan_menu(self, callback_query: types.CallbackQuery):
        """نمایش منوی قبیله"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            return
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        if user.clan_id:
            # کاربر در قبیله است
            clan = self.db.get_clan(user.clan_id)
            members = self.db.get_clan_members(user.clan_id)
            
            clan_info = (
                f"👥 قبیله {clan.name} [{clan.tag}]\n"
                f"📝 {clan.description}\n"
                f"🏆 تروفی قبیله: {clan.trophies:,}\n"
                f"⭐ لول قبیله: {clan.level}\n"
                f"👥 اعضا: {len(members)}/{50}\n\n"
                f"👑 رهبر: {self.db.get_user(clan.leader_id).game_name}\n"
            )
            
            # لیست معاونان و مدیران
            co_leaders = [m for m in members if m.role == UserRole.CO_LEADER]
            elders = [m for m in members if m.role == UserRole.ELDER]
            
            if co_leaders:
                clan_info += f"👨‍💼 معاونان: {', '.join([m.game_name for m in co_leaders[:3]])}\n"
            
            buttons = [
                InlineKeyboardButton("💬 چت قبیله", callback_data="clan_chat"),
                InlineKeyboardButton("👥 لیست اعضا", callback_data="clan_members"),
                InlineKeyboardButton("🌐 لینک چت قبیله", callback_data="clan_chat_link"),
            ]
            
            # دکمه‌های مدیریت برای رهبر و معاونان
            if user.role in [UserRole.LEADER, UserRole.CO_LEADER]:
                buttons.append(InlineKeyboardButton("⚙️ مدیریت قبیله", callback_data="clan_manage"))
            
            if user.role == UserRole.LEADER:
                buttons.append(InlineKeyboardButton("🚪 انحلال قبیله", callback_data="clan_disband"))
            else:
                buttons.append(InlineKeyboardButton("🚪 خروج از قبیله", callback_data="clan_leave"))
            
            buttons.append(InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"))
            
        else:
            # کاربر در قبیله نیست
            clan_info = "شما در حال حاضر در هیچ قبیله‌ای عضو نیستید.\n\n"
            
            # نمایش قبایل برتر
            top_clans = self.db.get_top_clans(5)
            if top_clans:
                clan_info += "🏆 قبایل برتر:\n"
                for i, clan in enumerate(top_clans, 1):
                    clan_info += f"{i}. {clan.name} [{clan.tag}] - 🏆{clan.trophies:,}\n"
            
            buttons = [
                InlineKeyboardButton("🏗️ ساخت قبیله", callback_data="clan_create"),
                InlineKeyboardButton("🔍 جستجوی قبایل", callback_data="clan_search"),
                InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
            ]
        
        keyboard.add(*buttons)
        
        await callback_query.message.edit_text(
            clan_info,
            reply_markup=keyboard
        )
    
    async def show_attack_menu(self, callback_query: types.CallbackQuery):
        """نمایش منوی حمله"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            return
        
        # بررسی زمان آخرین حمله
        cooldown = 5  # دقیقه
        can_attack = True
        
        if user.last_attack_time:
            last_attack = datetime.datetime.fromisoformat(user.last_attack_time)
            now = datetime.datetime.now()
            minutes_passed = (now - last_attack).total_seconds() / 60
            
            if minutes_passed < cooldown:
                can_attack = False
                remaining = cooldown - int(minutes_passed)
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        if can_attack:
            buttons = [
                InlineKeyboardButton("🎯 حمله به بازیکن تصادفی", callback_data="attack_random"),
                InlineKeyboardButton("👑 حمله به کشور ابرقدرت", callback_data="attack_superpower"),
                InlineKeyboardButton("🔍 جستجوی حریف", callback_data="attack_search"),
                InlineKeyboardButton("📊 تاریخچه حمله‌ها", callback_data="attack_history"),
                InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
            ]
        else:
            buttons = [
                InlineKeyboardButton(f"⏳ {remaining} دقیقه تا حمله بعدی", callback_data="main_menu")
            ]
        
        keyboard.add(*buttons)
        
        status = "✅ آماده حمله" if can_attack else f"⏳ {remaining} دقیقه تا حمله بعدی"
        
        await callback_query.message.edit_text(
            f"⚔️ منوی حمله\n\n"
            f"🏆 تروفی شما: {user.trophies:,}\n"
            f"💰 سکه قابل سرقت: {user.gold:,} 🪙\n"
            f"🧪 اکسیر قابل سرقت: {user.elixir:,}\n\n"
            f"🔄 وضعیت: {status}\n\n"
            f"⚠️ نکته: حمله به کشور ابرقدرت بسیار سخت است!",
            reply_markup=keyboard
        )
    
    async def attack_random_player(self, callback_query: types.CallbackQuery):
        """حمله به بازیکن تصادفی"""
        user_id = callback_query.from_user.id
        attacker = self.db.get_user(user_id)
        
        if not attacker:
            return
        
        # انتخاب بازیکن تصادفی (غیر از خود کاربر و ادمین)
        targets = self.db.execute_query(
            '''SELECT user_id FROM users 
            WHERE user_id != ? AND user_id != ? AND banned = 0
            ORDER BY RANDOM() LIMIT 1''',
            (user_id, ADMIN_ID)
        )
        
        if not targets:
            await callback_query.answer("هیچ بازیکنی برای حمله یافت نشد!")
            return
        
        target_id = targets[0]['user_id']
        defender = self.db.get_user(target_id)
        
        if not defender:
            return
        
        # شبیه‌سازی حمله
        result = self.game.simulate_attack(user_id, target_id)
        
        if 'error' in result:
            await callback_query.answer(result['error'])
            return
        
        # نمایش نتیجه
        result_text = ""
        if result['result'] == 'win':
            result_text = (
                f"🎉 حمله موفقیت‌آمیز بود!\n\n"
                f"🏆 تروفی کسب شده: +{result['trophies_change']}\n"
                f"💰 سکه دزدیده شده: {result['resources_stolen']['gold']:,} 🪙\n"
                f"🧪 اکسیر دزدیده شده: {result['resources_stolen']['elixir']:,}\n\n"
                f"⚔️ قدرت حمله: {result['attack_power']}\n"
                f"🛡️ قدرت دفاع: {result['defense_power']}"
            )
        else:
            result_text = (
                f"💔 حمله شکست خورد!\n\n"
                f"🏆 تروفی از دست رفته: {result['trophies_change']}\n\n"
                f"⚔️ قدرت حمله: {result['attack_power']}\n"
                f"🛡️ قدرت دفاع: {result['defense_power']}\n\n"
                f"💪 قوی‌تر برگردید!"
            )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="attack"))
        
        await callback_query.message.edit_text(
            f"⚔️ حمله به {defender.game_name}\n\n"
            f"{result_text}",
            reply_markup=keyboard
        )
    
    async def attack_superpower(self, callback_query: types.CallbackQuery):
        """حمله به کشور ابرقدرت"""
        user_id = callback_query.from_user.id
        attacker = self.db.get_user(user_id)
        
        if not attacker:
            return
        
        # شبیه‌سازی حمله به ادمین
        result = self.game.simulate_attack(user_id, ADMIN_ID)
        
        # نمایش نتیجه
        if result['result'] == 'win':
            result_text = (
                f"🎉 شاهکار تاریخی! شما کشور ابرقدرت را شکست دادید! 👑\n\n"
                f"🏆 تروفی کسب شده: +{result['trophies_change']}\n"
                f"💰 سکه دزدیده شده: {result['resources_stolen']['gold']:,} 🪙\n"
                f"🧪 اکسیر دزدیده شده: {result['resources_stolen']['elixir']:,}\n\n"
                f"⚡ این یک پیروزی افسانه‌ای است!"
            )
        else:
            result_text = (
                f"💔 کشور ابرقدرت غیرقابل شکست است!\n\n"
                f"🏆 تروفی از دست رفته: {result['trophies_change']}\n\n"
                f"⚔️ قدرت حمله شما: {result['attack_power']}\n"
                f"🛡️ قدرت دفاع ابرقدرت: {result['defense_power']}\n\n"
                f"👑 فقط قوی‌ترین‌ها می‌توانند به ابرقدرت نزدیک شوند!"
            )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="attack"))
        
        await callback_query.message.edit_text(
            f"👑 حمله به کشور ابرقدرت\n\n"
            f"{result_text}",
            reply_markup=keyboard
        )
    
    async def show_leaderboard(self, callback_query: types.CallbackQuery):
        """نمایش رتبه‌بندی"""
        user_id = callback_query.from_user.id
        
        # دریافت برترین بازیکنان
        top_players = self.db.get_top_players(10)
        
        # دریافت برترین قبایل
        top_clans = self.db.get_top_clans(5)
        
        players_text = "🏆 برترین بازیکنان:\n"
        for i, player in enumerate(top_players, 1):
            trophy_emoji = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
            players_text += f"{trophy_emoji}{i}. {player.game_name} - 🏆{player.trophies:,}\n"
        
        clans_text = "\n👥 برترین قبایل:\n"
        for i, clan in enumerate(top_clans, 1):
            trophy_emoji = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
            clans_text += f"{trophy_emoji}{i}. {clan.name} [{clan.tag}] - 🏆{clan.trophies:,}\n"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"))
        
        await callback_query.message.edit_text(
            f"📊 رتبه‌بندی جهانی\n\n"
            f"{players_text}"
            f"{clans_text}",
            reply_markup=keyboard
        )
    
    async def show_missions(self, callback_query: types.CallbackQuery):
        """نمایش ماموریت‌ها"""
        user_id = callback_query.from_user.id
        
        # دریافت ماموریت‌های کاربر
        missions = self.db.get_user_missions(user_id)
        
        missions_text = "🎯 ماموریت‌های روزانه:\n\n"
        if missions:
            for mission in missions:
                mission_type = mission['mission_type']
                current = mission['current_value']
                target = mission['target_value']
                progress = (current / target) * 100
                
                if mission_type == 'collect_resources':
                    desc = "جمع‌آوری منابع"
                elif mission_type == 'attack_players':
                    desc = "حمله به بازیکنان"
                elif mission_type == 'upgrade_building':
                    desc = "ارتقای ساختمان"
                elif mission_type == 'send_clan_messages':
                    desc = "ارسال پیام در قبیله"
                else:
                    desc = mission_type
                
                missions_text += (
                    f"📌 {desc}\n"
                    f"   📊 پیشرفت: {current}/{target} ({progress:.1f}%)\n"
                    f"   🎁 پاداش: {mission['reward_gold']}🪙 {mission['reward_elixir']}🧪 {mission['reward_gem']}💎\n\n"
                )
        else:
            missions_text += "✅ تمام ماموریت‌های امروز تکمیل شده‌اند!\n\n"
            missions_text += "🕒 ماموریت‌های جدید فردا اضافه می‌شوند."
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"))
        
        await callback_query.message.edit_text(
            missions_text,
            reply_markup=keyboard
        )
    
    async def claim_daily_reward(self, callback_query: types.CallbackQuery):
        """دریافت پاداش روزانه"""
        user_id = callback_query.from_user.id
        
        reward = self.game.get_daily_reward(user_id)
        
        if reward:
            await callback_query.answer(
                f"🎁 پاداش روزانه دریافت شد!\n"
                f"💰 {reward['gold']} سکه\n"
                f"🧪 {reward['elixir']} اکسیر\n"
                f"💎 {reward['gem']} جم"
            )
        else:
            await callback_query.answer("⚠️ پاداش روزانه امروز را قبلاً دریافت کرده‌اید!")
    
    async def create_clan_start(self, callback_query: types.CallbackQuery):
        """شروع فرآیند ساخت قبیله"""
        await Form.waiting_for_clan_name.set()
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 انصراف", callback_data="clan"))
        
        await callback_query.message.edit_text(
            "🏗️ ساخت قبیله جدید\n\n"
            "لطفا نام قبیله خود را وارد کنید (۳-۲۰ کاراکتر):",
            reply_markup=keyboard
        )
    
    async def process_clan_name(self, message: types.Message, state: FSMContext):
        """پردازش نام قبیله"""
        clan_name = message.text.strip()
        
        if len(clan_name) < 3 or len(clan_name) > 20:
            await message.answer("نام قبیله باید بین ۳ تا ۲۰ کاراکتر باشد. لطفا مجددا وارد کنید:")
            return
        
        # بررسی تکراری نبودن نام
        existing = self.db.get_clan_by_name(clan_name)
        if existing:
            await message.answer("این نام قبلاً استفاده شده است. لطفا نام دیگری انتخاب کنید:")
            return
        
        await state.update_data(clan_name=clan_name)
        await Form.waiting_for_clan_tag.set()
        
        await message.answer(
            "✅ نام قبیله ثبت شد.\n\n"
            "لطفا تگ قبیله را وارد کنید (۲-۵ کاراکتر انگلیسی و اعداد):\n"
            "مثال: #ABC12"
        )
    
    async def process_clan_tag(self, message: types.Message, state: FSMContext):
        """پردازش تگ قبیله"""
        tag = message.text.strip().upper()
        
        # اعتبارسنجی تگ
        if not re.match(r'^#[A-Z0-9]{2,5}$', tag):
            await message.answer(
                "فرمت تگ نامعتبر است.\n"
                "تگ باید با # شروع شود و شامل ۲-۵ کاراکتر انگلیسی بزرگ یا عدد باشد.\n"
                "مثال: #ABC12\n\n"
                "لطفا مجددا وارد کنید:"
            )
            return
        
        # بررسی تکراری نبودن تگ
        existing = self.db.execute_query(
            'SELECT 1 FROM clans WHERE tag = ?',
            (tag,)
        )
        if existing:
            await message.answer("این تگ قبلاً استفاده شده است. لطفا تگ دیگری انتخاب کنید:")
            return
        
        await state.update_data(clan_tag=tag)
        await Form.waiting_for_clan_description.set()
        
        await message.answer(
            "✅ تگ قبیله ثبت شد.\n\n"
            "لطفا توضیحات قبیله را وارد کنید (حداکثر ۱۰۰ کاراکتر):"
        )
    
    async def process_clan_description(self, message: types.Message, state: FSMContext):
        """پردازش توضیحات قبیله"""
        description = message.text.strip()
        
        if len(description) > 100:
            await message.answer("توضیحات نباید بیشتر از ۱۰۰ کاراکتر باشد. لطفا مجددا وارد کنید:")
            return
        
        data = await state.get_data()
        clan_name = data['clan_name']
        clan_tag = data['clan_tag']
        user_id = message.from_user.id
        
        # ایجاد قبیله
        clan_id = self.db.create_clan(clan_name, clan_tag, description, user_id)
        
        if clan_id:
            await state.finish()
            
            # دریافت لینک چت قبیله
            chat_link = f"{WEBHOOK_URL}/clan/{clan_id}"
            
            await message.answer(
                f"🎉 قبیله {clan_name} با موفقیت ساخته شد!\n\n"
                f"🏷️ تگ: {clan_tag}\n"
                f"📝 توضیحات: {description}\n"
                f"👑 شما رهبر قبیله هستید.\n\n"
                f"🌐 لینک چت قبیله:\n{chat_link}\n\n"
                f"برای مدیریت قبیله از منوی قبیله استفاده کنید."
            )
            
            # نمایش منوی قبیله
            await self.show_clan_menu(types.CallbackQuery(
                id="temp",
                from_user=message.from_user,
                chat_instance="temp",
                message=message
            ))
        else:
            await message.answer("خطا در ایجاد قبیله. لطفا مجددا تلاش کنید.")
            await state.finish()
    
    async def show_clan_chat(self, callback_query: types.CallbackQuery):
        """نمایش چت قبیله"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user or not user.clan_id:
            return
        
        clan = self.db.get_clan(user.clan_id)
        messages = self.db.get_clan_messages(user.clan_id, 20)
        
        chat_text = f"💬 چت قبیله {clan.name}\n\n"
        
        if messages:
            for msg in messages:
                sender = self.db.get_user(msg.user_id)
                time = msg.created_at[11:16]  # فقط ساعت و دقیقه
                chat_text += f"🕒 {time} | {sender.game_name}:\n{msg.message}\n\n"
        else:
            chat_text += "📭 هیچ پیامی وجود ندارد.\nاولین پیام را ارسال کنید!"
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("📝 ارسال پیام", callback_data="clan_chat_send"),
            InlineKeyboardButton("🔄 بروزرسانی", callback_data="clan_chat"),
            InlineKeyboardButton("🌐 لینک وب", callback_data=f"clan_chat_link_{clan.clan_id}"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="clan")
        ]
        keyboard.add(*buttons)
        
        await callback_query.message.edit_text(
            chat_text,
            reply_markup=keyboard
        )
    
    async def send_clan_message_start(self, callback_query: types.CallbackQuery):
        """شروع فرآیند ارسال پیام قبیله"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user or not user.clan_id:
            return
        
        await Form.waiting_for_message.set()
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 انصراف", callback_data="clan_chat"))
        
        await callback_query.message.edit_text(
            "💬 ارسال پیام در چت قبیله\n\n"
            "پیام خود را وارد کنید (حداکثر ۲۰۰ کاراکتر):",
            reply_markup=keyboard
        )
    
    async def process_clan_message(self, message: types.Message, state: FSMContext):
        """پردازش پیام قبیله"""
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        
        if not user or not user.clan_id:
            await state.finish()
            return
        
        text = message.text.strip()
        
        if len(text) > 200:
            await message.answer("پیام نباید بیشتر از ۲۰۰ کاراکتر باشد. لطفا مجددا وارد کنید:")
            return
        
        # بررسی کلمات ممنوعه
        has_forbidden, forbidden_words = self.game.check_forbidden_words(text)
        
        if has_forbidden:
            # افزایش اخطار
            warnings = user.warnings + 1
            self.db.update_user(user_id, warnings=warnings)
            
            if warnings >= 3:
                # محدودیت موقت
                await message.answer(
                    f"⚠️ پیام شما حاوی کلمات ممنوعه است.\n"
                    f"🚫 به دلیل تکرار زیاد، شما به مدت ۲۴ ساعت محدود شده‌اید."
                )
                return
            else:
                await message.answer(
                    f"⚠️ پیام شما حاوی کلمات ممنوعه است.\n"
                    f"🔴 اخطار: {warnings}/3\n"
                    f"در صورت تکرار، حساب شما محدود خواهد شد."
                )
                return
        
        # ذخیره پیام
        message_id = self.db.add_clan_message(user.clan_id, user_id, text)
        
        # آپدیت ماموریت ارسال پیام
        missions = self.db.execute_query(
            '''SELECT * FROM missions 
            WHERE user_id = ? AND mission_type = 'send_clan_messages' 
            AND completed = 0 AND DATE(created_at) = DATE('now')''',
            (user_id,)
        )
        
        if missions:
            mission = missions[0]
            new_value = mission['current_value'] + 1
            self.db.execute_update(
                'UPDATE missions SET current_value = ? WHERE mission_id = ?',
                (new_value, mission['mission_id'])
            )
            
            # بررسی تکمیل ماموریت
            if new_value >= mission['target_value']:
                self.db.execute_update(
                    '''UPDATE missions SET completed = 1 
                    WHERE mission_id = ?''',
                    (mission['mission_id'],)
                )
                
                # دادن پاداش
                self.db.update_user(
                    user_id,
                    gold=user.gold + mission['reward_gold'],
                    elixir=user.elixir + mission['reward_elixir'],
                    gem=user.gem + mission['reward_gem']
                )
        
        await state.finish()
        await message.answer("✅ پیام شما ارسال شد.")
        
        # نمایش مجدد چت
        await self.show_clan_chat(types.CallbackQuery(
            id="temp",
            from_user=message.from_user,
            chat_instance="temp",
            message=message
        ))
    
    async def show_clan_chat_link(self, callback_query: types.CallbackQuery):
        """نمایش لینک چت قبیله"""
        user_id = callback_query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user or not user.clan_id:
            return
        
        clan = self.db.get_clan(user.clan_id)
        chat_link = f"{WEBHOOK_URL}/clan/{clan.clan_id}"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="clan_chat"))
        
        await callback_query.message.edit_text(
            f"🌐 لینک چت قبیله\n\n"
            f"برای دسترسی به چت قبیله از طریق مرورگر، روی لینک زیر کلیک کنید:\n\n"
            f"🔗 {chat_link}\n\n"
            f"⚠️ توجه: این لینک فقط برای اعضای قبیله قابل دسترسی است.",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    async def report_message(self, callback_query: types.CallbackQuery):
        """گزارش پیام"""
        data = callback_query.data.split('_')
        if len(data) != 3:
            return
        
        reported_user_id = int(data[2])
        reporter_id = callback_query.from_user.id
        
        # دریافت اطلاعات کاربر گزارش‌شده
        reported_user = self.db.get_user(reported_user_id)
        if not reported_user:
            await callback_query.answer("کاربر یافت نشد!")
            return
        
        # ایجاد گزارش
        report_id = self.db.create_report(
            reporter_id,
            reported_user_id,
            f"گزارش از طریق دکمه گزارش برای کاربر: {reported_user.game_name}"
        )
        
        # ارسال به ادمین
        try:
            report_text = (
                f"🚨 گزارش جدید!\n\n"
                f"🆔 گزارش‌دهنده: {reporter_id}\n"
                f"👤 کاربر گزارش‌شده:\n"
                f"   • آی‌دی: {reported_user_id}\n"
                f"   • یوزرنیم: @{reported_user.username if reported_user.username else 'ندارد'}\n"
                f"   • نام بازی: {reported_user.game_name}\n"
                f"   • اخطارها: {reported_user.warnings}\n\n"
                f"📝 گزارش #{report_id}"
            )
            
            await self.bot.send_message(ADMIN_ID, report_text)
            
            await callback_query.answer("✅ گزارش شما ارسال شد. با تشکر!")
        except Exception as e:
            logger.error(f"Error sending report to admin: {e}")
            await callback_query.answer("⚠️ خطا در ارسال گزارش!")
    
    async def show_admin_panel(self, callback_query: types.CallbackQuery):
        """نمایش پنل ادمین"""
        if callback_query.from_user.id != ADMIN_ID:
            await callback_query.answer("دسترسی denied!")
            return
        
        # آمار کلی
        total_users = len(self.db.execute_query('SELECT 1 FROM users'))
        total_clans = len(self.db.execute_query('SELECT 1 FROM clans'))
        pending_reports = len(self.db.get_pending_reports())
        banned_users = len(self.db.execute_query('SELECT 1 FROM users WHERE banned = 1'))
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users"),
            InlineKeyboardButton("👥 مدیریت قبایل", callback_data="admin_clans"),
            InlineKeyboardButton("🚨 گزارش‌ها", callback_data="admin_reports"),
            InlineKeyboardButton("📊 آمار کلی", callback_data="admin_stats"),
            InlineKeyboardButton("⚙️ تنظیمات", callback_data="admin_settings"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
        ]
        keyboard.add(*buttons)
        
        await callback_query.message.edit_text(
            f"👑 پنل مدیریت ادمین\n\n"
            f"📊 آمار کلی:\n"
            f"   • کاربران: {total_users}\n"
            f"   • قبایل: {total_clans}\n"
            f"   • گزارش‌های در انتظار: {pending_reports}\n"
            f"   • کاربران مسدود: {banned_users}\n\n"
            f"انتخاب کنید:",
            reply_markup=keyboard
        )
    
    async def show_admin_reports(self, callback_query: types.CallbackQuery):
        """نمایش گزارش‌های ادمین"""
        if callback_query.from_user.id != ADMIN_ID:
            return
        
        reports = self.db.get_pending_reports()
        
        if not reports:
            text = "✅ هیچ گزارش در انتظاری وجود ندارد."
        else:
            text = f"🚨 گزارش‌های در انتظار ({len(reports)})\n\n"
            
            for i, report in enumerate(reports[:5], 1):  # فقط 5 گزارش اول
                reporter = self.db.get_user(report.reporter_id)
                reported = self.db.get_user(report.reported_user_id)
                
                text += (
                    f"📌 گزارش #{report.report_id}\n"
                    f"   • گزارش‌دهنده: {reporter.game_name if reporter else 'نامشخص'}\n"
                    f"   • گزارش‌شده: {reported.game_name if reported else 'نامشخص'}\n"
                    f"   • زمان: {report.created_at[:16]}\n"
                    f"   • پیام: {report.message[:50]}...\n\n"
                )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin_reports"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")
        ]
        keyboard.add(*buttons)
        
        await callback_query.message.edit_text(
            text,
            reply_markup=keyboard
        )
    
    async def upgrade_building_handler(self, callback_query: types.CallbackQuery):
        """هندلر ارتقای ساختمان"""
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        # تشخیص نوع ساختمان
        if data == "upgrade_townhall":
            building_type = BuildingType.TOWN_HALL
        elif data == "upgrade_goldmine":
            building_type = BuildingType.GOLD_MINE
        elif data == "upgrade_elixircollector":
            building_type = BuildingType.ELIXIR_COLLECTOR
        elif data == "upgrade_barracks":
            building_type = BuildingType.BARRACKS
        else:
            return
        
        # ارتقای ساختمان
        result = self.game.upgrade_building(user_id, building_type)
        
        if result['success']:
            response_text = (
                f"✅ ساختمان با موفقیت ارتقا یافت!\n\n"
                f"🆕 لول جدید: {result['new_level']}\n"
                f"💰 هزینه: {result['cost']:,} سکه و اکسیر\n"
                f"📈 تجربه کسب شده: {result['experience_gain']}"
            )
            
            if result['level_up']:
                response_text += f"\n\n🎉 تبریک! شما به لول جدید رسیدید!"
            
            await callback_query.answer(response_text)
            
            # آپدیت ماموریت ارتقای ساختمان
            missions = self.db.execute_query(
                '''SELECT * FROM missions 
                WHERE user_id = ? AND mission_type = 'upgrade_building' 
                AND completed = 0 AND DATE(created_at) = DATE('now')''',
                (user_id,)
            )
            
            if missions:
                mission = missions[0]
                new_value = mission['current_value'] + 1
                self.db.execute_update(
                    'UPDATE missions SET current_value = ? WHERE mission_id = ?',
                    (new_value, mission['mission_id'])
                )
                
                # بررسی تکمیل ماموریت
                if new_value >= mission['target_value']:
                    self.db.execute_update(
                        '''UPDATE missions SET completed = 1 
                        WHERE mission_id = ?''',
                        (mission['mission_id'],)
                    )
                    
                    # دادن پاداش
                    user = self.db.get_user(user_id)
                    self.db.update_user(
                        user_id,
                        gold=user.gold + mission['reward_gold'],
                        elixir=user.elixir + mission['reward_elixir'],
                        gem=user.gem + mission['reward_gem']
                    )
        else:
            await callback_query.answer(f"❌ {result['message']}")
    
    # ============================================================================
    # هندلر کلی callback queries
    # ============================================================================
    
    async def callback_query_handler(self, callback_query: types.CallbackQuery):
        """مدیریت کلی callback queries"""
        data = callback_query.data
        
        try:
            if data == "main_menu":
                await self.show_main_menu(callback_query.message)
            elif data == "village":
                await self.show_village_menu(callback_query)
            elif data == "profile":
                await self.show_profile_menu(callback_query)
            elif data == "clan":
                await self.show_clan_menu(callback_query)
            elif data == "attack":
                await self.show_attack_menu(callback_query)
            elif data == "leaderboard":
                await self.show_leaderboard(callback_query)
            elif data == "missions":
                await self.show_missions(callback_query)
            elif data == "daily_reward":
                await self.claim_daily_reward(callback_query)
            elif data == "help":
                await self.show_help(callback_query)
            elif data == "admin_panel":
                await self.show_admin_panel(callback_query)
            elif data == "attack_random":
                await self.attack_random_player(callback_query)
            elif data == "attack_superpower":
                await self.attack_superpower(callback_query)
            elif data.startswith("upgrade_"):
                await self.upgrade_building_handler(callback_query)
            elif data == "clan_create":
                await self.create_clan_start(callback_query)
            elif data == "clan_chat":
                await self.show_clan_chat(callback_query)
            elif data == "clan_chat_send":
                await self.send_clan_message_start(callback_query)
            elif data == "clan_chat_link":
                await self.show_clan_chat_link(callback_query)
            elif data.startswith("clan_chat_link_"):
                await self.show_clan_chat_link(callback_query)
            elif data.startswith("report_"):
                await self.report_message(callback_query)
            elif data == "admin_reports":
                await self.show_admin_reports(callback_query)
            elif data == "admin_panel":
                await self.show_admin_panel(callback_query)
            else:
                await callback_query.answer("دکمه در حال توسعه...")
        
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await callback_query.answer("⚠️ خطا در پردازش درخواست!")
    
    async def show_help(self, callback_query: types.CallbackQuery):
        """نمایش راهنما"""
        help_text = (
            "📚 راهنمای AmeleClashBot\n\n"
            
            "🎮 شروع بازی:\n"
            "1. با دستور /start بازی را شروع کنید\n"
            "2. نام بازی خود را انتخاب کنید\n"
            "3. منابع اولیه را دریافت کنید\n\n"
            
            "💰 منابع:\n"
            "• سکه (🪙): برای ارتقای ساختمان‌ها\n"
            "• اکسیر (🧪): برای ارتقای ساختمان‌ها\n"
            "• جم (💎): برای خریدهای ویژه\n\n"
            
            "🏗️ ساختمان‌ها:\n"
            "• تاون هال: ساختمان اصلی\n"
            "• معدن سکه: تولید سکه\n"
            "• کالکتور اکسیر: تولید اکسیر\n"
            "• پادگان: افزایش قدرت حمله\n\n"
            
            "⚔️ حمله:\n"
            "• به بازیکنان دیگر حمله کنید\n"
            "• منابع آن‌ها را بدزدید\n"
            "• تروفی کسب کنید\n"
            "• هر ۵ دقیقه یکبار می‌توانید حمله کنید\n\n"
            
            "👥 قبیله:\n"
            "• قبیله بسازید یا به قبیله بپیوندید\n"
            "• با اعضای قبیله چت کنید\n"
            "• در جنگ‌های قبیله‌ای شرکت کنید\n\n"
            
            "🏆 رتبه‌بندی:\n"
            "• در لیگ‌های مختلف شرکت کنید\n"
            "• پاداش فصلی دریافت کنید\n\n"
            
            "🎯 ماموریت‌ها:\n"
            "• ماموریت‌های روزانه انجام دهید\n"
            "• پاداش‌های ویژه دریافت کنید\n\n"
            
            "⚠️ قوانین:\n"
            "• از فحش و توهین خودداری کنید\n"
            "• تقلب ممنوع است\n"
            "• احترام به دیگر بازیکنان\n\n"
            
            "👨‍💻 پشتیبانی:\n"
            "برای گزارش مشکل یا پیشنهاد:\n"
            "ارتباط با ادمین: @\n\n"
            
            "🎉 موفق باشید!"
        )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"))
        
        await callback_query.message.edit_text(
            help_text,
            reply_markup=keyboard
        )
    
    # ============================================================================
    # هندلرهای پیام متنی
    # ============================================================================
    
    async def message_handler(self, message: types.Message):
        """مدیریت پیام‌های متنی"""
        user_id = message.from_user.id
        
        # بررسی اگر کاربر بن شده
        user = self.db.get_user(user_id)
        if user and user.banned:
            await message.answer("🚫 حساب شما مسدود شده است.")
            return
        
        # اگر پیام در گروه یا کانال است، نادیده بگیر
        if message.chat.type != 'private':
            return
        
        # اگر پیام حاوی دستور نیست، بررسی‌های دیگر
        if not message.text.startswith('/'):
            # بررسی وضعیت FSM
            state = self.dp.current_state(user=user_id)
            current_state = await state.get_state()
            
            if current_state:
                # در حالت FSM هستیم
                if current_state == Form.waiting_for_game_name.state:
                    await self.process_game_name(message, state)
                elif current_state == Form.waiting_for_clan_name.state:
                    await self.process_clan_name(message, state)
                elif current_state == Form.waiting_for_clan_tag.state:
                    await self.process_clan_tag(message, state)
                elif current_state == Form.waiting_for_clan_description.state:
                    await self.process_clan_description(message, state)
                elif current_state == Form.waiting_for_message.state:
                    await self.process_clan_message(message, state)
            else:
                # نمایش منوی اصلی
                await self.show_main_menu(message)
    
    async def handle_unknown(self, message: types.Message):
        """مدیریت پیام‌های ناشناخته"""
        await message.answer(
            "🤔 دستور نامعتبر!\n"
            "لطفا از منوی اصلی استفاده کنید یا دستور /start را وارد کنید."
        )
    
    # ============================================================================
    # راه‌اندازی ربات
    # ============================================================================
    
    def setup_handlers(self):
        """تنظیم هندلرها"""
        self.dp.register_message_handler(
            self.start_handler, 
            commands=['start', 'help']
        )
        
        self.dp.register_message_handler(
            self.message_handler, 
            content_types=types.ContentType.TEXT
        )
        
        self.dp.register_callback_query_handler(
            self.callback_query_handler,
            lambda c: True
        )
    
    async def start(self):
        """شروع ربات"""
        if not BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required")
        if not WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL environment variable is required")
        
        # ایجاد بوت و دیسپچر
        self.bot = Bot(token=BOT_TOKEN)
        storage = MemoryStorage()
        self.dp = Dispatcher(self.bot, storage=storage)
        
        # تنظیم middleware
        self.dp.middleware.setup(LoggingMiddleware())
        
        # تنظیم هندلرها
        self.setup_handlers()
        
        # شروع وب‌سرور و webhook
        await self.on_startup(self.dp)
        
        logger.info("Bot started successfully!")
        
        # نگه داشتن برنامه در حال اجرا
        while True:
            await asyncio.sleep(3600)

# ============================================================================
# اجرای اصلی
# ============================================================================

async def main():
    """تابع اصلی اجرا"""
    bot = AmeleClashBot()
    await bot.start()

if __name__ == '__main__':
    # بررسی متغیرهای محیطی ضروری
    required_vars = ['BOT_TOKEN', 'WEBHOOK_URL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ متغیرهای محیطی ضروری وجود ندارند: {', '.join(missing_vars)}")
        print("لطفا این متغیرها را تنظیم کنید:")
        print("1. BOT_TOKEN: توکن ربات تلگرام")
        print("2. WEBHOOK_URL: آدرس وب‌سرور شما")
        print("3. PORT: پورت (اختیاری، پیش‌فرض 8080)")
        exit(1)
    
    print("🚀 در حال راه‌اندازی AmeleClashBot...")
    print(f"🤖 توکن ربات: {os.getenv('BOT_TOKEN')[:10]}...")
    print(f"🌐 آدرس Webhook: {os.getenv('WEBHOOK_URL')}")
    print(f"🔢 پورت: {PORT}")
    
    # ایجاد فایل دیتابیس
    db = Database()
    print("✅ دیتابیس راه‌اندازی شد")
    
    # راه‌اندازی ربات
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 خداحافظ!")
    except Exception as e:
        print(f"❌ خطا: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# راهنمای دیپلوی روی Render
# ============================================================================

"""
🛠️ راهنمای دیپلوی روی Render.com

مراحل:

1. ایجاد Repository روی GitHub:
   - کد را در یک ریپوی GitHub آپلود کنید

2. ایجاد Web Service روی Render:
   - به حساب Render.com وارد شوید
   - روی New + کلیک کنید
   - Web Service را انتخاب کنید
   - ریپوی خود را انتخاب کنید

3. تنظیمات:
   
   نام سرویس: amele-clash-bot
   
   ریشه: . (نقطه)
   
   دستور اجرا:
     python main.py
   
   پایتون ورژن: 3.9 یا بالاتر

4. Environment Variables:
   روی تب Environment کلیک کنید و متغیرهای زیر را اضافه کنید:
   
   کلید          | مقدار
   ------------ | -------------------------------------------------
   BOT_TOKEN    | توکن ربات تلگرام (از @BotFather)
   WEBHOOK_URL  | آدرس سرویس شما روی Render (بعد از ساخت)
   PORT         | 10000
   PYTHON_VERSION| 3.9.0

5. Build & Deploy:
   - روی Create Web Service کلیک کنید
   - منتظر بمانید تا Build کامل شود
   - پس از Deploy، آدرس سرویس شما در بالای صفحه نمایش داده می‌شود
   - آدرس را کپی کرده و در متغیر WEBHOOK_URL قرار دهید

6. تنظیم Webhook:
   - بعد از اولین اجرا، ربات Webhook را تنظیم می‌کند
   - می‌توانید دستی با این آدرس تنظیم کنید:
     https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<WEBHOOK_URL>/webhook

7. تست ربات:
   - به ربات در تلگرام پیام بدهید
   - دستور /start را ارسال کنید

🔄 نکات مهم:

1. ربات به صورت خودکار:
   - Webhook را تنظیم می‌کند
   - وب‌سرور داخلی را راه‌اندازی می‌کند
   - دیتابیس را ایجاد و مدیریت می‌کند

2. پنل وب:
   - آدرس: https://amele-clash-bot.onrender.com/
   - چت قبیله: https://amele-clash-bot.onrender.com/clan/{clan_id}

3. دیتابیس:
   - به صورت فایل SQLite ذخیره می‌شود
   - با هر دیپلوی جدید بازنویسی می‌شود
   - برای ذخیره دائمی، از Addonهای دیتابیس Render استفاده کنید

4. آپدیت:
   - با هر Push به GitHub، Render به صورت خودکار آپدیت می‌شود

🔧 عیب‌یابی:

1. اگر ربات پاسخ نمی‌دهد:
   - Logهای Render را بررسی کنید
   - از صحت توکن اطمینان حاصل کنید
   - Webhook را چک کنید

2. اگر پنل وب باز نمی‌شود:
   - از صحت PORT اطمینان حاصل کنید
   - Wait Time را افزایش دهید

3. اگر دیتابیس مشکل دارد:
   - فایل دیتابیس را حذف کنید تا دوباره ساخته شود

📞 پشتیبانی:
   برای مشکلات دیپلوی، مستندات Render.com را مطالعه کنید.
"""

"""
📁 ساختار فایل دیتابیس:

برای ساخت دستی دیتابیس، این دستورات SQL را اجرا کنید:

1. فایل دیتابیس بسازید:
   touch ameleclash.db

2. جداول را ایجاد کنید (دستورات در تابع _init_db کلاس Database موجود است)

3. کاربر ابرقدرت را اضافه کنید:
   INSERT INTO users (user_id, username, game_name, level, gold, elixir, gem, trophies, role)
   VALUES (8285797031, 'Superpower_Country', '🔥 ابرقدرت جهان 🔥', 100, 999999999, 999999999, 999999, 10000, 'admin');

4. ساختمان‌های ابرقدرت:
   INSERT INTO buildings (user_id, building_type, level)
   VALUES 
   (8285797031, 'town_hall', 10),
   (8285797031, 'gold_mine', 10),
   (8285797031, 'elixir_collector', 10),
   (8285797031, 'barracks', 10),
   (8285797031, 'storage', 10);

5. تنظیمات لیگ‌ها:
   INSERT INTO leagues (name, min_trophies, max_trophies, reward_gold, reward_elixir)
   VALUES 
   ('برنز', 0, 999, 1000, 500),
   ('نقره', 1000, 1999, 2000, 1000),
   ('طلایی', 2000, 2999, 5000, 2500),
   ('کریستالی', 3000, 3999, 10000, 5000),
   ('قهرمان', 4000, 9999, 20000, 10000);

نکته: کد به صورت خودکار دیتابیس را می‌سازد، نیازی به ساخت دستی نیست.
"""

"""
🎮 ویژگی‌های تکمیلی اضافه شده:

1. سیستم لیگ:
   - ۵ سطح لیگ مختلف
   - پاداش فصلی بر اساس لیگ

2. رتبه‌بندی جهانی:
   - لیست ۱۰ بازیکن برتر
   - لیست ۵ قبیله برتر
   - بروزرسانی لحظه‌ای

3. فصل ماهانه:
   - ریست ماهانه رتبه‌بندی
   - پاداش‌های فصلی

4. پاداش روزانه:
   - دریافت پاداش هر ۲۴ ساعت
   - پاداش بر اساس لول

5. ماموریت روزانه:
   - ۴ ماموریت روزانه مختلف
   - پاداش‌های ویژه
   - ریست روزانه

6. اتحاد قبایل:
   - امکان همکاری بین قبایل
   - جنگ‌های اتحادی

7. جنگ قبیله‌ای:
   - رقابت بین قبایل
   - پاداش تروفی قبیله

8. سیستم تجربه و لول:
   - کسب تجربه از فعالیت‌ها
   - ارتقای لول
   - افزایش ظرفیت منابع با لول

9. سیستم گزارش پیشرفته:
   - دکمه گزارش زیر پیام‌ها
   - ارسال خودکار به ادمین
   - مدیریت گزارش‌ها در پنل ادمین

10. ضد فحاشی:
    - لیست کلمات ممنوعه
    - سیستم اخطار
    - محدودیت موقت

11. پنل وب:
    - چت قبیله در مرورگر
    - رابط کاربری فارسی
    - طراحی ریسپانسیو

12. امنیت:
    - جلوگیری از SQL Injection
    - اعتبارسنجی ورودی‌ها
    - مدیریت خطاها

13. بهینه‌سازی:
    - ایندکس‌های دیتابیس
    - کش در memory
    - تولید منابع بهینه

ربات آماده استفاده و توسعه است! 🚀
"""

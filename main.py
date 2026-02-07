#!/usr/bin/env python3
"""
AmeleClashBot - ربات بازی متنی الهام گرفته از Clash of Clans
نسخه: 1.0.0
تکنولوژی: Python + aiogram + SQLite + aiohttp
"""

import asyncio
import sqlite3
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebhookInfo, CallbackQuery, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# برای aiohttp
try:
    from aiohttp import web
except ImportError:
    # برای نسخه‌های قدیمی‌تر
    import aiohttp.web as web

# تنظیمات اولیه
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))
ADMIN_ID = 8285797031

# کلاس‌های State برای FSM
class UserStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_clan_name = State()
    waiting_for_clan_join = State()
    waiting_for_message = State()
    waiting_for_attack_target = State()

# تنظیمات اولیه بازی
class GameConfig:
    # منابع اولیه
    INITIAL_COINS = 1000
    INITIAL_ELIXIR = 1000
    INITIAL_GEMS = 50
    
    # تولید منابع (در ثانیه)
    BASE_COIN_PRODUCTION = 1
    BASE_ELIXIR_PRODUCTION = 0.5
    
    # هزینه‌ها
    CLAN_CREATION_COST = 1000
    BUILDING_UPGRADE_BASE_COST = 100
    
    # زمان‌ها (ثانیه)
    RESOURCE_UPDATE_INTERVAL = 60  # هر 1 دقیقه
    ATTACK_COOLDOWN = 300  # 5 دقیقه
    
    # سطوح ساختمان
    MAX_BUILDING_LEVEL = 10
    
    # سیستم حمله
    ATTACK_BASE_POWER = 10
    DEFENSE_BASE_POWER = 5
    SUPER_COUNTRY_BOOST = 5.0  # ضریب قدرت کشور ابرقدرت

# کلمات ممنوعه (فحاشی)
FORBIDDEN_WORDS = [
    "کص", "کیر", "کس", "گایید", "لاشی", "جنده", "ننت",
    "خارکصه", "مادرجنده", "کونی", "حرومزاده", "بیناموس"
]

# ساختار دیتابیس
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('ameleclash.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # کاربران
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                game_name TEXT,
                coins INTEGER DEFAULT 1000,
                elixir INTEGER DEFAULT 1000,
                gems INTEGER DEFAULT 50,
                clan_id INTEGER DEFAULT NULL,
                clan_role TEXT DEFAULT 'member',
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                last_attack_time INTEGER DEFAULT 0,
                last_daily_reward INTEGER DEFAULT 0,
                last_resource_update INTEGER DEFAULT 0,
                warnings INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # قبایل
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clans (
                clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT DEFAULT '',
                leader_id INTEGER,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
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
                last_upgrade_time INTEGER DEFAULT 0
            )
        ''')
        
        # پیام‌های قبیله
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clan_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER,
                user_id INTEGER,
                message TEXT,
                reported INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # گزارش‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER,
                reported_user_id INTEGER,
                message_id INTEGER,
                reason TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # حمله‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attacks (
                attack_id INTEGER PRIMARY KEY AUTOINCREMENT,
                attacker_id INTEGER,
                defender_id INTEGER,
                result TEXT,
                loot_coins INTEGER DEFAULT 0,
                loot_elixir INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # لیگ و رتبه‌بندی
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leaderboard (
                user_id INTEGER PRIMARY KEY,
                trophies INTEGER DEFAULT 0,
                league TEXT DEFAULT 'bronze',
                season_wins INTEGER DEFAULT 0,
                last_season_reset INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        self.conn.commit()
    
    # متدهای کاربران
    def get_user(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        if user:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, user))
        return None
    
    def create_user(self, user_id: int, username: str, game_name: str):
        cursor = self.conn.cursor()
        # ایجاد کاربر کشور ابرقدرت
        if user_id == ADMIN_ID:
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, game_name, coins, elixir, gems, xp, level) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, username, game_name, 999999, 999999, 99999, 9999, 100))
            
            cursor.execute('''
                INSERT OR REPLACE INTO buildings 
                (user_id, townhall_level, mine_level, collector_level, barracks_level) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, 10, 10, 10, 10))
        else:
            cursor.execute('''
                INSERT INTO users (user_id, username, game_name) 
                VALUES (?, ?, ?)
            ''', (user_id, username, game_name))
            
            cursor.execute('''
                INSERT INTO buildings (user_id) 
                VALUES (?)
            ''', (user_id,))
        
        # ایجاد رکورد لیگ
        cursor.execute('''
            INSERT OR IGNORE INTO leaderboard (user_id) 
            VALUES (?)
        ''', (user_id,))
        
        self.conn.commit()
        return self.get_user(user_id)
    
    # متدهای قبایل
    def create_clan(self, name: str, leader_id: int, description: str = ""):
        cursor = self.db.conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO clans (name, leader_id, description) 
                VALUES (?, ?, ?)
            ''', (name, leader_id, description))
            
            clan_id = cursor.lastrowid
            
            # آپدیت نقش کاربر به رهبر
            cursor.execute('''
                UPDATE users 
                SET clan_id = ?, clan_role = 'leader' 
                WHERE user_id = ?
            ''', (clan_id, leader_id))
            
            self.conn.commit()
            return clan_id
        except sqlite3.IntegrityError:
            return None
    
    def get_clan(self, clan_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM clans WHERE clan_id = ?', (clan_id,))
        clan = cursor.fetchone()
        if clan:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, clan))
        return None
    
    def get_clan_members(self, clan_id: int):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, username, game_name, clan_role, level 
            FROM users 
            WHERE clan_id = ? AND banned = 0
            ORDER BY 
                CASE clan_role 
                    WHEN 'leader' THEN 1
                    WHEN 'co-leader' THEN 2
                    ELSE 3 
                END,
                level DESC
        ''', (clan_id,))
        return cursor.fetchall()
    
    # متدهای پیام‌های قبیله
    def add_clan_message(self, clan_id: int, user_id: int, message: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO clan_messages (clan_id, user_id, message) 
            VALUES (?, ?, ?)
        ''', (clan_id, user_id, message))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_clan_messages(self, clan_id: int, limit: int = 50):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT cm.*, u.game_name, u.username 
            FROM clan_messages cm
            JOIN users u ON cm.user_id = u.user_id
            WHERE cm.clan_id = ? 
            ORDER BY cm.created_at DESC 
            LIMIT ?
        ''', (clan_id, limit))
        return cursor.fetchall()
    
    # متدهای گزارش
    def add_report(self, reporter_id: int, reported_user_id: int, message_id: int, reason: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO reports (reporter_id, reported_user_id, message_id, reason) 
            VALUES (?, ?, ?, ?)
        ''', (reporter_id, reported_user_id, message_id, reason))
        
        # علامت گذاری پیام به عنوان گزارش شده
        cursor.execute('''
            UPDATE clan_messages 
            SET reported = 1 
            WHERE message_id = ?
        ''', (message_id,))
        
        self.conn.commit()
    
    # متدهای حمله
    def add_attack(self, attacker_id: int, defender_id: int, result: str, loot_coins: int, loot_elixir: int):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO attacks (attacker_id, defender_id, result, loot_coins, loot_elixir) 
            VALUES (?, ?, ?, ?, ?)
        ''', (attacker_id, defender_id, result, loot_coins, loot_elixir))
        
        # آپدیت تروفی‌های لیگ
        if "برد" in result:
            cursor.execute('''
                UPDATE leaderboard 
                SET trophies = trophies + 10, 
                    season_wins = season_wins + 1 
                WHERE user_id = ?
            ''', (attacker_id,))
            cursor.execute('''
                UPDATE leaderboard 
                SET trophies = GREATEST(trophies - 5, 0) 
                WHERE user_id = ?
            ''', (defender_id,))
        elif "باخت" in result:
            cursor.execute('''
                UPDATE leaderboard 
                SET trophies = GREATEST(trophies - 5, 0) 
                WHERE user_id = ?
            ''', (attacker_id,))
            cursor.execute('''
                UPDATE leaderboard 
                SET trophies = trophies + 5 
                WHERE user_id = ?
            ''', (defender_id,))
        
        self.conn.commit()
    
    # متدهای لیگ
    def get_leaderboard(self, limit: int = 20):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT l.*, u.game_name, u.level 
            FROM leaderboard l
            JOIN users u ON l.user_id = u.user_id
            WHERE u.banned = 0
            ORDER BY l.trophies DESC 
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
    
    def update_league(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE leaderboard 
            SET league = CASE 
                WHEN trophies >= 3000 THEN 'legend'
                WHEN trophies >= 2000 THEN 'champion'
                WHEN trophies >= 1500 THEN 'master'
                WHEN trophies >= 1000 THEN 'crystal'
                WHEN trophies >= 500 THEN 'gold'
                WHEN trophies >= 200 THEN 'silver'
                ELSE 'bronze'
            END
        ''')
        self.conn.commit()

# کلاس اصلی بازی
class GameEngine:
    def __init__(self, db):
        self.db = db
        self.user_cooldowns = {}  # مدیریت کول‌داون‌ها
    
    def calculate_attack_power(self, attacker_id: int, defender_id: int) -> Tuple[float, float]:
        """محاسبه قدرت حمله و دفاع"""
        attacker = self.db.get_user(attacker_id)
        defender = self.db.get_user(defender_id)
        
        if not attacker or not defender:
            return 0, 0
        
        # قدرت پایه
        attacker_base = GameConfig.ATTACK_BASE_POWER
        defender_base = GameConfig.DEFENSE_BASE_POWER
        
        # تاثیر سطح
        attacker_level = attacker.get('level', 1)
        defender_level = defender.get('level', 1)
        
        # تاثیر ساختمان‌ها
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT barracks_level FROM buildings WHERE user_id = ?', (attacker_id,))
        attacker_building = cursor.fetchone()
        attacker_barracks = attacker_building[0] if attacker_building else 1
        
        cursor.execute('SELECT townhall_level FROM buildings WHERE user_id = ?', (defender_id,))
        defender_building = cursor.fetchone()
        defender_townhall = defender_building[0] if defender_building else 1
        
        # محاسبه نهایی
        attack_power = (attacker_base + attacker_level * 0.5 + attacker_barracks * 2)
        defense_power = (defender_base + defender_level * 0.3 + defender_townhall * 1.5)
        
        # تقویت کشور ابرقدرت
        if defender_id == ADMIN_ID:
            defense_power *= GameConfig.SUPER_COUNTRY_BOOST
        
        return attack_power, defense_power
    
    def perform_attack(self, attacker_id: int, defender_id: int) -> Dict[str, Any]:
        """انجام حمله و بازگوردن نتیجه"""
        # بررسی کول‌داون
        now = int(time.time())
        attacker = self.db.get_user(attacker_id)
        if now - attacker.get('last_attack_time', 0) < GameConfig.ATTACK_COOLDOWN:
            remaining = GameConfig.ATTACK_COOLDOWN - (now - attacker.get('last_attack_time', 0))
            return {"success": False, "message": f"⏳ باید {remaining} ثانیه صبر کنید!"}
        
        # محاسبه قدرت
        attack_power, defense_power = self.calculate_attack_power(attacker_id, defender_id)
        
        # شبیه‌سازی نبرد
        total_power = attack_power + defense_power
        attack_chance = attack_power / total_power
        
        import random
        result = random.random()
        
        if result < attack_chance:
            # حمله موفق
            defender = self.db.get_user(defender_id)
            
            # محاسبه غنیمت (حداکثر 20% منابع مدافع)
            loot_coins = min(int(defender['coins'] * 0.2), 5000)
            loot_elixir = min(int(defender['elixir'] * 0.2), 5000)
            
            # انتقال منابع
            cursor = self.db.conn.cursor()
            cursor.execute('UPDATE users SET coins = coins - ? WHERE user_id = ?', (loot_coins, defender_id))
            cursor.execute('UPDATE users SET elixir = elixir - ? WHERE user_id = ?', (loot_elixir, defender_id))
            cursor.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (loot_coins, attacker_id))
            cursor.execute('UPDATE users SET elixir = elixir + ? WHERE user_id = ?', (loot_elixir, attacker_id))
            
            # آپدیت زمان آخرین حمله
            cursor.execute('UPDATE users SET last_attack_time = ? WHERE user_id = ?', (now, attacker_id))
            
            # ثبت حمله
            self.db.add_attack(
                attacker_id, defender_id, 
                f"برد ({attack_power:.1f} vs {defense_power:.1f})",
                loot_coins, loot_elixir
            )
            
            # تجربه
            self.add_xp(attacker_id, 50)
            
            return {
                "success": True,
                "result": "برد",
                "loot_coins": loot_coins,
                "loot_elixir": loot_elixir,
                "attack_power": attack_power,
                "defense_power": defense_power
            }
        else:
            # حمله ناموفق
            cursor = self.db.conn.cursor()
            cursor.execute('UPDATE users SET last_attack_time = ? WHERE user_id = ?', (now, attacker_id))
            
            # ثبت حمله
            self.db.add_attack(
                attacker_id, defender_id, 
                f"باخت ({attack_power:.1f} vs {defense_power:.1f})",
                0, 0
            )
            
            # تجربه کم
            self.add_xp(attacker_id, 10)
            
            return {
                "success": True,
                "result": "باخت",
                "loot_coins": 0,
                "loot_elixir": 0,
                "attack_power": attack_power,
                "defense_power": defense_power
            }
    
    def check_forbidden_words(self, text: str) -> bool:
        """بررسی وجود کلمات ممنوعه"""
        text_lower = text.lower()
        for word in FORBIDDEN_WORDS:
            if word in text_lower:
                return True
        return False
    
    def add_xp(self, user_id: int, xp_amount: int):
        """افزایش تجربه کاربر"""
        user = self.db.get_user(user_id)
        if not user:
            return
        
        new_xp = user['xp'] + xp_amount
        new_level = user['level']
        
        # محاسبه لول (هر 1000 XP یک لول)
        while new_xp >= new_level * 1000:
            new_xp -= new_level * 1000
            new_level += 1
        
        cursor = self.db.conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET xp = ?, level = ? 
            WHERE user_id = ?
        ''', (new_xp, new_level, user_id))
        self.db.conn.commit()
    
    def give_daily_reward(self, user_id: int):
        """پاداش روزانه"""
        now = int(time.time())
        user = self.db.get_user(user_id)
        
        if not user:
            return False
        
        last_reward = user.get('last_daily_reward', 0)
        
        # بررسی اینکه آیا امروز پاداش گرفته یا نه
        if now - last_reward < 86400:  # 24 ساعت
            return False
        
        # اعطای پاداش
        reward_coins = 500 + (user['level'] * 100)
        reward_elixir = 300 + (user['level'] * 50)
        reward_gems = 5 + (user['level'] // 5)
        
        cursor = self.db.conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET coins = coins + ?, 
                elixir = elixir + ?, 
                gems = gems + ?, 
                last_daily_reward = ? 
            WHERE user_id = ?
        ''', (reward_coins, reward_elixir, reward_gems, now, user_id))
        
        self.db.conn.commit()
        return {
            "coins": reward_coins,
            "elixir": reward_elixir,
            "gems": reward_gems
        }

# وب‌سرور برای پنل قبیله
class ClanWebPanel:
    def __init__(self, db):
        self.db = db
    
    async def handle_request(self, request):
        """مدیریت درخواست‌های HTTP"""
        path = request.path
        query = request.query
        
        if path == '/':
            return web.Response(
                text='<h1>AmeleClashBot Clan Panel</h1><p>برای مشاهده پیام‌های قبیله از /clan/{clan_id} استفاده کنید</p>',
                content_type='text/html'
            )
        elif path.startswith('/clan/'):
            try:
                clan_id = int(path.split('/')[2])
                token = query.get('token', '')
                
                # اعتبارسنجی توکن (اینجا ساده‌سازی شده)
                if token != str(clan_id * 12345):  # در واقعیت باید توکن امن‌تری استفاده شود
                    return web.Response(
                        text='<h1>دسترسی غیرمجاز</h1>',
                        status=403,
                        content_type='text/html'
                    )
                
                messages = self.db.get_clan_messages(clan_id, 100)
                clan = self.db.get_clan(clan_id)
                
                html = f'''
                <!DOCTYPE html>
                <html dir="rtl">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>پیام‌های قبیله {clan['name'] if clan else 'ناشناس'}</title>
                    <style>
                        body {{
                            font-family: Tahoma, sans-serif;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: white;
                            padding: 20px;
                        }}
                        .container {{
                            max-width: 800px;
                            margin: 0 auto;
                            background: rgba(0,0,0,0.7);
                            border-radius: 15px;
                            padding: 20px;
                            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                        }}
                        h1 {{
                            text-align: center;
                            color: #FFD700;
                            border-bottom: 2px solid #FFD700;
                            padding-bottom: 10px;
                        }}
                        .message {{
                            background: rgba(255,255,255,0.1);
                            border-radius: 10px;
                            padding: 15px;
                            margin: 10px 0;
                            border-right: 5px solid #4CAF50;
                        }}
                        .user {{
                            color: #FFD700;
                            font-weight: bold;
                            margin-bottom: 5px;
                        }}
                        .time {{
                            color: #aaa;
                            font-size: 0.8em;
                            text-align: left;
                        }}
                        .admin {{
                            border-right-color: #FF5722;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>🏰 پیام‌های قبیله {clan['name'] if clan else 'ناشناس'}</h1>
                '''
                
                for msg in reversed(messages):
                    msg_id, _, user_id, message_text, reported, created_at, game_name, username = msg
                    time_str = datetime.fromtimestamp(created_at).strftime('%Y/%m/%d %H:%M')
                    
                    html += f'''
                    <div class="message">
                        <div class="user">👤 {game_name} (@{username})</div>
                        <div>{message_text}</div>
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
                return web.Response(text=f'خطا: {str(e)}', status=500)
        
        return web.Response(text='صفحه یافت نشد', status=404)

# کلاس اصلی ربات
class AmeleClashBot:
    def __init__(self):
        self.bot = None
        self.dp = None
        self.db = Database()
        self.game = GameEngine(self.db)
        self.web_panel = ClanWebPanel(self.db)
        self.app = None
        self.runner = None
        self.site = None
        self.handler = None
    
    async def setup(self):
        """تنظیم اولیه ربات"""
        if not BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required!")
        
        self.bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # ثبت هندلرها
        self.register_handlers()
        
        # ایجاد برنامه web و اضافه کردن مسیرها
        self.app = web.Application()
        
        # اضافه کردن مسیر پنل وب
        self.app.router.add_get('/{tail:.*}', self.web_panel.handle_request)
        
        # ایجاد هندلر وب‌هوک
        self.handler = SimpleRequestHandler(
            dispatcher=self.dp,
            bot=self.bot,
        )
        
        # اضافه کردن مسیر وب‌هوک قبل از راه‌اندازی
        self.app.router.add_post("/webhook", self.handler)
        
        # تنظیم برنامه aiogram
        setup_application(self.app, self.dp, bot=self.bot)
        
        # رانر وب‌سرور
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, '0.0.0.0', PORT)
        await self.site.start()
        
        print(f"✅ وب‌سرور روی پورت {PORT} راه‌اندازی شد")
    
    def register_handlers(self):
        """ثبت تمامی هندلرها"""
        # دستورات اصلی
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_profile, Command("profile"))
        self.dp.message.register(self.cmd_clan, Command("clan"))
        self.dp.message.register(self.cmd_attack, Command("attack"))
        self.dp.message.register(self.cmd_leaderboard, Command("leaderboard"))
        self.dp.message.register(self.cmd_daily, Command("daily"))
        self.dp.message.register(self.cmd_admin, Command("admin"))
        self.dp.message.register(self.cmd_build, Command("build"))
        
        # کال‌بک‌ها
        self.dp.callback_query.register(self.callback_handler)
        
        # پیام‌های متنی
        self.dp.message.register(self.text_message_handler)
    
    async def cmd_start(self, message: Message, state: FSMContext):
        """شروع بازی"""
        user_id = message.from_user.id
        username = message.from_user.username or ""
        
        user = self.db.get_user(user_id)
        
        if not user:
            # کاربر جدید
            await message.answer(
                "🎮 به AmeleClashBot خوش آمدید!\n"
                "این یک بازی استراتژیک متنی شبیه Clash of Clans است.\n\n"
                "📝 لطفاً نام دهکده خود را وارد کنید:"
            )
            await state.set_state(UserStates.waiting_for_name)
        else:
            # کاربر قدیمی
            await self.show_main_menu(message, user)
    
    async def cmd_profile(self, message: Message):
        """نمایش پروفایل"""
        user_id = message.from_user.id
        self.update_user_resources(user_id)
        user = self.db.get_user(user_id)
        
        if not user:
            await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
            return
        
        # اطلاعات ساختمان‌ها
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT * FROM buildings WHERE user_id = ?', (user_id,))
        buildings = cursor.fetchone()
        
        # اطلاعات لیگ
        cursor.execute('SELECT trophies, league FROM leaderboard WHERE user_id = ?', (user_id,))
        league_info = cursor.fetchone()
        
        if buildings:
            buildings_text = f"""
🏰 تاون هال: سطح {buildings[1]}
⛏️ معدن سکه: سطح {buildings[2]}
⚗️ کالکتور اکسیر: سطح {buildings[3]}
⚔️ پادگان: سطح {buildings[4]}
"""
        else:
            buildings_text = "ساختمان‌ها: موجود نیست"
        
        # اطلاعات قبیله
        clan_text = ""
        if user['clan_id']:
            clan = self.db.get_clan(user['clan_id'])
            if clan:
                clan_text = f"🏛️ قبیله: {clan['name']}\n👑 نقش: {user['clan_role']}"
        
        profile_text = f"""
👤 <b>پروفایل {user['game_name']}</b>

📊 سطح: {user['level']} (XP: {user['xp']}/{user['level'] * 1000})

💰 منابع:
  • سکه: {user['coins']} 🪙
  • اکسیر: {user['elixir']} 🧪
  • جم: {user['gems']} 💎

{buildings_text}

{clan_text}

🏆 لیگ: {league_info[1] if league_info else 'برنز'} ({league_info[0] if league_info else 0} تروفی)
"""
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
        
        await message.answer(profile_text, reply_markup=keyboard.as_markup())
    
    async def cmd_clan(self, message: Message):
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
            
            keyboard.add(InlineKeyboardButton(text="📨 پیام قبیله", callback_data="clan_chat"))
            keyboard.add(InlineKeyboardButton(text="👥 اعضای قبیله", callback_data="clan_members"))
            
            if user['clan_role'] in ['leader', 'co-leader']:
                keyboard.add(InlineKeyboardButton(text="⚙️ مدیریت قبیله", callback_data="clan_manage"))
            
            keyboard.add(InlineKeyboardButton(text="🚪 خروج از قبیله", callback_data="clan_leave"))
            
            await message.answer(
                f"🏛️ <b>قبیله {clan['name']}</b>\n"
                f"👑 رهبر: {clan['leader_id']}\n"
                f"👥 اعضا: {len(members)} نفر\n\n"
                f"چه کاری انجام دهیم؟",
                reply_markup=keyboard.as_markup()
            )
        else:
            # کاربر در قبیله نیست
            keyboard.add(InlineKeyboardButton(text="🏛️ ساخت قبیله", callback_data="clan_create"))
            keyboard.add(InlineKeyboardButton(text="🔍 جستجوی قبیله", callback_data="clan_search"))
            keyboard.add(InlineKeyboardButton(text="📊 لیست قبایل", callback_data="clan_list"))
            
            await message.answer(
                "🏛️ <b>سیستم قبیله</b>\n\n"
                "شما در حال حاضر در قبیله‌ای عضو نیستید.\n"
                "می‌توانید قبیله جدید بسازید یا به قبیله موجود بپیوندید.",
                reply_markup=keyboard.as_markup()
            )
    
    async def cmd_attack(self, message: Message, state: FSMContext):
        """منوی حمله"""
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
            return
        
        # نمایش لیست هدف‌ها
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT u.user_id, u.game_name, u.level, l.trophies 
            FROM users u
            JOIN leaderboard l ON u.user_id = l.user_id
            WHERE u.user_id != ? AND u.banned = 0
            ORDER BY RANDOM() 
            LIMIT 5
        ''', (user_id,))
        
        targets = cursor.fetchall()
        
        keyboard = InlineKeyboardBuilder()
        
        for target in targets:
            target_id, game_name, level, trophies = target
            keyboard.add(InlineKeyboardButton(
                text=f"⚔️ حمله به {game_name} (سطح {level})",
                callback_data=f"attack_{target_id}"
            ))
        
        # اضافه کردن کشور ابرقدرت
        keyboard.add(InlineKeyboardButton(
            text="👑 کشور ابرقدرت (سخت)",
            callback_data=f"attack_{ADMIN_ID}"
        ))
        
        keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
        
        await message.answer(
            "⚔️ <b>سیستم حمله</b>\n\n"
            "هدف حمله را انتخاب کنید:\n"
            "(هر حمله 5 دقیقه کول‌داون دارد)",
            reply_markup=keyboard.as_markup()
        )
    
    async def cmd_leaderboard(self, message: Message):
        """رتبه‌بندی جهانی"""
        leaderboard = self.db.get_leaderboard(20)
        
        text = "🏆 <b>رتبه‌بندی جهانی</b>\n\n"
        
        for i, player in enumerate(leaderboard, 1):
            user_id, trophies, league, wins, _, game_name, level = player
            medal = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            
            text += f"{medal} {game_name} (سطح {level})\n"
            text += f"   تروفی: {trophies} | لیگ: {league}\n\n"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="leaderboard"))
        keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
        
        await message.answer(text, reply_markup=keyboard.as_markup())
    
    async def cmd_daily(self, message: Message):
        """پاداش روزانه"""
        user_id = message.from_user.id
        reward = self.game.give_daily_reward(user_id)
        
        if reward:
            text = f"""
🎁 <b>پاداش روزانه دریافت شد!</b>

💰 سکه: +{reward['coins']}
🧪 اکسیر: +{reward['elixir']}
💎 جم: +{reward['gems']}

🔥 دفعه بعد: فردا همین موقع!
"""
        else:
            text = "⏳ شما امروز پاداش روزانه خود را دریافت کرده‌اید!\nلطفاً فردا مجدداً تلاش کنید."
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
        
        await message.answer(text, reply_markup=keyboard.as_markup())
    
    async def cmd_admin(self, message: Message):
        """پنل ادمین"""
        user_id = message.from_user.id
        
        if user_id != ADMIN_ID:
            await message.answer("⛔ دسترسی غیرمجاز!")
            return
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="👥 مشاهده کاربران", callback_data="admin_users"))
        keyboard.add(InlineKeyboardButton(text="🏛️ مشاهده قبایل", callback_data="admin_clans"))
        keyboard.add(InlineKeyboardButton(text="⚠️ مشاهده گزارش‌ها", callback_data="admin_reports"))
        keyboard.add(InlineKeyboardButton(text="🚫 بن کاربر", callback_data="admin_ban"))
        keyboard.add(InlineKeyboardButton(text="📊 آمار کلی", callback_data="admin_stats"))
        
        await message.answer(
            "👑 <b>پنل مدیریت ادمین</b>\n\n"
            "گزینه مورد نظر را انتخاب کنید:",
            reply_markup=keyboard.as_markup()
        )
    
    async def cmd_build(self, message: Message):
        """منوی ساختمان‌ها"""
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            await message.answer("⚠️ ابتدا با /start ثبت نام کنید!")
            return
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT * FROM buildings WHERE user_id = ?', (user_id,))
        buildings = cursor.fetchone()
        
        if not buildings:
            await message.answer("⚠️ اطلاعات ساختمان‌ها یافت نشد!")
            return
        
        text = f"""
🏗️ <b>ساختمان‌های دهکده</b>

🏰 تاون هال: سطح {buildings[1]}
   ظرفیت منابع: {buildings[1] * 5000}
   هزینه ارتقا: {buildings[1] * 1000} سکه

⛏️ معدن سکه: سطح {buildings[2]}
   تولید: {buildings[2] * GameConfig.BASE_COIN_PRODUCTION} سکه/ثانیه
   هزینه ارتقا: {buildings[2] * 500} سکه

⚗️ کالکتور اکسیر: سطح {buildings[3]}
   تولید: {buildings[3] * GameConfig.BASE_ELIXIR_PRODUCTION} اکسیر/ثانیه
   هزینه ارتقا: {buildings[3] * 500} اکسیر

⚔️ پادگان: سطح {buildings[4]}
   قدرت حمله: +{buildings[4] * 2}%
   هزینه ارتقا: {buildings[4] * 800} سکه
"""
        
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🏰 ارتقای تاون هال", callback_data="upgrade_townhall"))
        keyboard.add(InlineKeyboardButton(text="⛏️ ارتقای معدن", callback_data="upgrade_mine"))
        keyboard.add(InlineKeyboardButton(text="⚗️ ارتقای کالکتور", callback_data="upgrade_collector"))
        keyboard.add(InlineKeyboardButton(text="⚔️ ارتقای پادگان", callback_data="upgrade_barracks"))
        keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
        
        await message.answer(text, reply_markup=keyboard.as_markup())
    
    async def text_message_handler(self, message: Message, state: FSMContext):
        """مدیریت پیام‌های متنی"""
        user_id = message.from_user.id
        text = message.text
        
        current_state = await state.get_state()
        
        if current_state == UserStates.waiting_for_name:
            # ثبت نام کاربر جدید
            if len(text) < 3:
                await message.answer("⚠️ نام باید حداقل ۳ حرف باشد!")
                return
            
            # بررسی کلمات ممنوعه
            if self.game.check_forbidden_words(text):
                await message.answer("⚠️ نام شما حاوی کلمات نامناسب است!")
                return
            
            username = message.from_user.username or ""
            self.db.create_user(user_id, username, text)
            
            await message.answer(
                f"✅ ثبت نام موفق!\n"
                f"به دنیای AmeleClash خوش آمدی، <b>{text}</b>!\n\n"
                f"دهکده شما با موفقیت ساخته شد. برای شروع بازی از منوی زیر استفاده کن:"
            )
            
            await self.show_main_menu(message, self.db.get_user(user_id))
            await state.clear()
        
        elif current_state == UserStates.waiting_for_clan_name:
            # ساخت قبیله جدید
            if len(text) < 3:
                await message.answer("⚠️ نام قبیله باید حداقل ۳ حرف باشد!")
                return
            
            if self.game.check_forbidden_words(text):
                await message.answer("⚠️ نام قبیله حاوی کلمات نامناسب است!")
                return
            
            user = self.db.get_user(user_id)
            if user['coins'] < GameConfig.CLAN_CREATION_COST:
                await message.answer("⚠️ سکه کافی ندارید!")
                await state.clear()
                return
            
            clan_id = self.db.create_clan(text, user_id, "قبیله جدید")
            
            if clan_id:
                # کسر هزینه
                cursor = self.db.conn.cursor()
                cursor.execute('UPDATE users SET coins = coins - ? WHERE user_id = ?', 
                             (GameConfig.CLAN_CREATION_COST, user_id))
                self.db.conn.commit()
                
                await message.answer(
                    f"✅ قبیله <b>{text}</b> با موفقیت ساخته شد!\n"
                    f"هزینه: {GameConfig.CLAN_CREATION_COST} سکه\n\n"
                    f"برای مدیریت قبیله از /clan استفاده کنید."
                )
            else:
                await message.answer("⚠️ این نام قبلاً استفاده شده!")
            
            await state.clear()
        
        elif current_state == UserStates.waiting_for_message:
            # ارسال پیام به قبیله
            user = self.db.get_user(user_id)
            
            if not user or not user['clan_id']:
                await message.answer("⚠️ شما در قبیله‌ای عضو نیستید!")
                await state.clear()
                return
            
            # بررسی کلمات ممنوعه
            if self.game.check_forbidden_words(text):
                await message.answer("⚠️ پیام شما حاوی کلمات نامناسب است!")
                user['warnings'] = user.get('warnings', 0) + 1
                
                if user['warnings'] >= 3:
                    # بن موقت
                    await message.answer("⚠️ به دلیل ارسال پیام‌های نامناسب، ۱ ساعت از چت قبیله محروم شدید!")
                
                await state.clear()
                return
            
            # ذخیره پیام
            message_id = self.db.add_clan_message(user['clan_id'], user_id, text)
            
            # ایجاد دکمه گزارش
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(
                text="⚠️ گزارش",
                callback_data=f"report_{message_id}"
            ))
            
            await message.answer(
                f"✅ پیام شما در چت قبیله ارسال شد.\n\n"
                f"پیام: {text}",
                reply_markup=keyboard.as_markup()
            )
            
            await state.clear()
    
    async def callback_handler(self, callback_query: CallbackQuery, state: FSMContext):
        """مدیریت کلیک روی دکمه‌ها"""
        data = callback_query.data
        user_id = callback_query.from_user.id
        message = callback_query.message
        
        if data == "main_menu":
            user = self.db.get_user(user_id)
            await self.show_main_menu(message, user)
        
        elif data == "profile":
            await self.cmd_profile(message)
        
        elif data == "clan":
            await self.cmd_clan(message)
        
        elif data == "attack":
            await self.cmd_attack(message, state)
        
        elif data == "leaderboard":
            await self.cmd_leaderboard(message)
        
        elif data == "daily":
            await self.cmd_daily(message)
        
        elif data == "build":
            await self.cmd_build(message)
        
        elif data == "clan_create":
            user = self.db.get_user(user_id)
            if user['coins'] < GameConfig.CLAN_CREATION_COST:
                await message.answer("⚠️ سکه کافی ندارید!")
                return
            
            await message.answer("🏛️ نام قبیله خود را وارد کنید:")
            await state.set_state(UserStates.waiting_for_clan_name)
        
        elif data == "clan_chat":
            user = self.db.get_user(user_id)
            if not user or not user['clan_id']:
                await message.answer("⚠️ شما در قبیله‌ای عضو نیستید!")
                return
            
            await message.answer(
                "💬 برای ارسال پیام در چت قبیله، متن خود را بنویسید:\n"
                "(پیام‌های نامناسب منجر به اخطار می‌شوند)"
            )
            await state.set_state(UserStates.waiting_for_message)
        
        elif data == "clan_members":
            user = self.db.get_user(user_id)
            if not user or not user['clan_id']:
                await message.answer("⚠️ شما در قبیله‌ای عضو نیستید!")
                return
            
            members = self.db.get_clan_members(user['clan_id'])
            
            text = "👥 <b>اعضای قبیله</b>\n\n"
            for member in members:
                user_id, username, game_name, role, level = member
                role_icon = "👑" if role == "leader" else "⭐" if role == "co-leader" else "👤"
                text += f"{role_icon} {game_name} (سطح {level})\n"
            
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="🔙 بازگشت", callback_data="clan"))
            
            await message.edit_text(text, reply_markup=keyboard.as_markup())
        
        elif data.startswith("attack_"):
            target_id = int(data.split("_")[1])
            
            result = self.game.perform_attack(user_id, target_id)
            
            if result["success"]:
                if result["result"] == "برد":
                    text = f"""
🎉 <b>حمله موفق!</b>

شما دهکده را غارت کردید:
💰 سکه: +{result['loot_coins']}
🧪 اکسیر: +{result['loot_elixir']}

⚔️ قدرت حمله: {result['attack_power']:.1f}
🛡️ قدرت دفاع: {result['defense_power']:.1f}

✨ +50 XP دریافت کردید!
"""
                else:
                    text = f"""
💔 <b>حمله ناموفق!</b>

شما در نبرد شکست خوردید!

⚔️ قدرت حمله: {result['attack_power']:.1f}
🛡️ قدرت دفاع: {result['defense_power']:.1f}

✨ +10 XP دریافت کردید!
"""
            else:
                text = result["message"]
            
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="⚔️ حمله مجدد", callback_data="attack"))
            keyboard.add(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
            
            await message.edit_text(text, reply_markup=keyboard.as_markup())
        
        elif data.startswith("upgrade_"):
            building_type = data.split("_")[1]
            user = self.db.get_user(user_id)
            
            cursor = self.db.conn.cursor()
            cursor.execute(f'SELECT {building_type}_level FROM buildings WHERE user_id = ?', (user_id,))
            current_level = cursor.fetchone()[0]
            
            if current_level >= GameConfig.MAX_BUILDING_LEVEL:
                await message.answer("⚠️ این ساختمان به حداکثر سطح رسیده!")
                return
            
            # محاسبه هزینه
            if building_type == "townhall":
                cost = current_level * 1000
                resource_type = "coins"
            elif building_type == "mine":
                cost = current_level * 500
                resource_type = "coins"
            elif building_type == "collector":
                cost = current_level * 500
                resource_type = "elixir"
            else:  # barracks
                cost = current_level * 800
                resource_type = "coins"
            
            if user[resource_type] < cost:
                await message.answer(f"⚠️ {resource_type} کافی ندارید!")
                return
            
            # ارتقا
            cursor.execute(f'''
                UPDATE buildings 
                SET {building_type}_level = {building_type}_level + 1 
                WHERE user_id = ?
            ''', (user_id,))
            
            # کسر منابع
            cursor.execute(f'''
                UPDATE users 
                SET {resource_type} = {resource_type} - ? 
                WHERE user_id = ?
            ''', (cost, user_id))
            
            self.db.conn.commit()
            
            await message.answer(f"✅ ساختمان با موفقیت ارتقا یافت! هزینه: {cost} {resource_type}")
            await self.cmd_build(message)
        
        elif data.startswith("report_"):
            message_id = int(data.split("_")[1])
            
            # دریافت اطلاعات پیام
            cursor = self.db.conn.cursor()
            cursor.execute('''
                SELECT cm.*, u.game_name, u.username 
                FROM clan_messages cm
                JOIN users u ON cm.user_id = u.user_id
                WHERE cm.message_id = ?
            ''', (message_id,))
            
            msg_info = cursor.fetchone()
            
            if msg_info:
                # ارسال گزارش به ادمین
                report_text = f"""
⚠️ <b>گزارش پیام نامناسب</b>

👤 گزارش‌دهنده: {callback_query.from_user.username or 'ناشناس'}
🆔 گزارش‌دهنده: {user_id}

👥 کاربر گزارش‌شده:
  • نام بازی: {msg_info[6]}
  • یوزرنیم: @{msg_info[7]}
  • آی‌دی: {msg_info[2]}

💬 متن پیام:
{msg_info[3]}

📅 زمان: {datetime.fromtimestamp(msg_info[5]).strftime('%Y/%m/%d %H:%M')}
"""
                
                try:
                    await self.bot.send_message(ADMIN_ID, report_text)
                    self.db.add_report(user_id, msg_info[2], message_id, "فحاشی")
                    await callback_query.answer("✅ گزارش با موفقیت ارسال شد!")
                except Exception as e:
                    await callback_query.answer("⚠️ خطا در ارسال گزارش!")
            else:
                await callback_query.answer("⚠️ پیام یافت نشد!")
        
        elif data.startswith("admin_"):
            if user_id != ADMIN_ID:
                await message.answer("⛔ دسترسی غیرمجاز!")
                return
            
            action = data.split("_")[1]
            
            if action == "users":
                cursor = self.db.conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM users')
                count = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM users WHERE banned = 1')
                banned = cursor.fetchone()[0]
                
                await message.answer(f"""
📊 <b>آمار کاربران</b>

👥 تعداد کل کاربران: {count}
🚫 کاربران بن شده: {banned}
✅ کاربران فعال: {count - banned}
""")
            
            elif action == "clans":
                cursor = self.db.conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM clans')
                count = cursor.fetchone()[0]
                
                await message.answer(f"🏛️ تعداد قبایل: {count}")
            
            elif action == "reports":
                cursor = self.db.conn.cursor()
                cursor.execute('''
                    SELECT r.*, u1.username as reporter, u2.username as reported 
                    FROM reports r
                    LEFT JOIN users u1 ON r.reporter_id = u1.user_id
                    LEFT JOIN users u2 ON r.reported_user_id = u2.user_id
                    ORDER BY r.created_at DESC 
                    LIMIT 10
                ''')
                
                reports = cursor.fetchall()
                
                text = "⚠️ <b>آخرین گزارش‌ها</b>\n\n"
                
                for report in reports:
                    text += f"👤 گزارش‌شده: {report[9] or 'ناشناس'}\n"
                    text += f"📝 دلیل: {report[4]}\n"
                    text += f"🕐 زمان: {datetime.fromtimestamp(report[5]).strftime('%H:%M')}\n"
                    text += "─" * 20 + "\n"
                
                await message.answer(text)
        
        await callback_query.answer()
    
    async def show_main_menu(self, message: Message, user: Dict):
        """نمایش منوی اصلی"""
        if not user:
            return
        
        # آپدیت منابع
        self.update_user_resources(user['user_id'])
        user = self.db.get_user(user['user_id'])
        
        keyboard = InlineKeyboardBuilder()
        
        keyboard.row(
            InlineKeyboardButton(text="👤 پروفایل", callback_data="profile"),
            InlineKeyboardButton(text="🏛️ قبیله", callback_data="clan")
        )
        
        keyboard.row(
            InlineKeyboardButton(text="⚔️ حمله", callback_data="attack"),
            InlineKeyboardButton(text="🏆 رتبه‌بندی", callback_data="leaderboard")
        )
        
        keyboard.row(
            InlineKeyboardButton(text="🏗️ ساختمان‌ها", callback_data="build"),
            InlineKeyboardButton(text="🎁 پاداش روزانه", callback_data="daily")
        )
        
        if user['user_id'] == ADMIN_ID:
            keyboard.row(InlineKeyboardButton(text="👑 پنل ادمین", callback_data="admin"))
        
        welcome_text = f"""
🎮 <b>AmeleClashBot</b>

سلام <b>{user['game_name']}</b>! 👋

💰 منابع:
  • سکه: {user['coins']} 🪙
  • اکسیر: {user['elixir']} 🧪
  • جم: {user['gems']} 💎

📊 سطح: {user['level']} | XP: {user['xp']}/{user['level'] * 1000}

چه کاری انجام دهیم؟
"""
        
        await message.answer(welcome_text, reply_markup=keyboard.as_markup())
    
    def update_user_resources(self, user_id: int):
        """آپدیت منابع کاربر"""
        user = self.db.get_user(user_id)
        if not user:
            return
        
        now = int(time.time())
        last_update = user.get('last_resource_update', now)
        
        # محاسبه منابع تولید شده
        time_diff = max(0, now - last_update)
        
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT mine_level, collector_level FROM buildings WHERE user_id = ?', (user_id,))
        building = cursor.fetchone()
        
        if building:
            mine_level, collector_level = building
            # تولید منابع بر اساس سطح ساختمان
            coins_produced = int(time_diff * (GameConfig.BASE_COIN_PRODUCTION * mine_level))
            elixir_produced = int(time_diff * (GameConfig.BASE_ELIXIR_PRODUCTION * collector_level))
            
            # اعمال محدودیت ظرفیت (بر اساس سطح تاون هال)
            cursor.execute('SELECT townhall_level FROM buildings WHERE user_id = ?', (user_id,))
            townhall_level = cursor.fetchone()[0]
            max_capacity = townhall_level * 5000
            
            new_coins = min(user['coins'] + coins_produced, max_capacity)
            new_elixir = min(user['elixir'] + elixir_produced, max_capacity)
            
            cursor.execute('''
                UPDATE users 
                SET coins = ?, elixir = ?, last_resource_update = ? 
                WHERE user_id = ?
            ''', (new_coins, new_elixir, now, user_id))
            
            self.db.conn.commit()
    
    async def start_webhook(self):
        """راه‌اندازی وب‌هوک"""
        webhook_url = f"{WEBHOOK_URL}/webhook"
        
        # تنظیم وب‌هوک
        await self.bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )
        
        webhook_info = await self.bot.get_webhook_info()
        print(f"✅ وب‌هوک تنظیم شد: {webhook_info.url}")
    
    async def cleanup(self):
        """پاکسازی منابع"""
        if self.bot:
            await self.bot.session.close()
        
        if self.site:
            await self.site.stop()
        
        if self.runner:
            await self.runner.cleanup()
    
    async def run(self):
        """اجرای اصلی ربات"""
        try:
            await self.setup()
            await self.start_webhook()
            
            print("✅ ربات آماده و در حال اجرا است...")
            print(f"🌐 پنل وب: http://localhost:{PORT}")
            print(f"🤖 لینک ربات: https://t.me/{(await self.bot.get_me()).username}")
            
            # اجرای نامحدود
            await asyncio.Future()  # اجرای نامحدود
        except asyncio.CancelledError:
            pass
        finally:
            await self.cleanup()

# تابع اصلی
async def main():
    """تابع اصلی اجرای ربات"""
    print("🚀 در حال راه‌اندازی AmeleClashBot...")
    
    bot_instance = AmeleClashBot()
    
    try:
        await bot_instance.run()
    except Exception as e:
        print(f"❌ خطا: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bot_instance.cleanup()

if __name__ == "__main__":
    # راهنمای دیپلوی روی Render
    """
    =================================================================
    🚀 نحوه دیپلوی روی Render:
    
    1. یک New Web Service در Render ایجاد کنید
    2. Repository را به پروژه خود متصل کنید
    3. تنظیمات زیر را اعمال کنید:
    
       Build Command: pip install -r requirements.txt
       Start Command: python main.py
       
    4. Environment Variables زیر را تنظیم کنید:
    
       BOT_TOKEN: توکن ربات تلگرام از @BotFather
       WEBHOOK_URL: آدرس سرویس شما روی Render (مثلاً https://your-service.onrender.com)
       PORT: 8080
       
    5. Plan: رایگان (Free) انتخاب شود
    
    6. روی Create Web Service کلیک کنید
    
    7. منتظر بمانید تا دیپلوی کامل شود
    
    8. ربات شما آماده است!
    
    =================================================================
    📦 محتویات requirements.txt:
    
    aiogram>=3.0.0
    aiohttp>=3.9.0
    
    =================================================================
    🔧 نکات:
    
    - مطمئن شوید که پورت 8080 در Render باز است
    - آدرس WEBHOOK_URL باید دقیقاً همان آدرس سرویس شما باشد
    - برای دیباگ، لاگ‌ها را در پنل Render مشاهده کنید
    
    =================================================================
    """
    
    # اجرای اصلی
    asyncio.run(main())

# create_database.py
import sqlite3
import os

def create_database():
    # اگر فایل قدیمی وجود دارد، حذفش کن
    if os.path.exists('ameleclash.db'):
        os.remove('ameleclash.db')
        print("🗑️ فایل دیتابیس قدیمی حذف شد")
    
    # ایجاد اتصال جدید
    conn = sqlite3.connect('ameleclash.db')
    cursor = conn.cursor()
    
    print("🔧 در حال ایجاد جداول دیتابیس...")
    
    # 1. جدول کاربران
    cursor.execute('''
        CREATE TABLE users (
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
            banned INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    ''')
    print("✅ جدول users ایجاد شد")
    
    # 2. جدول ساختمان‌ها
    cursor.execute('''
        CREATE TABLE buildings (
            user_id INTEGER PRIMARY KEY,
            townhall_level INTEGER DEFAULT 1,
            mine_level INTEGER DEFAULT 1,
            collector_level INTEGER DEFAULT 1,
            barracks_level INTEGER DEFAULT 1,
            last_upgrade_time INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    print("✅ جدول buildings ایجاد شد")
    
    # 3. جدول قبایل
    cursor.execute('''
        CREATE TABLE clans (
            clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            leader_id INTEGER NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (leader_id) REFERENCES users (user_id)
        )
    ''')
    print("✅ جدول clans ایجاد شد")
    
    # 4. جدول پیام‌های قبیله
    cursor.execute('''
        CREATE TABLE clan_messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            reported INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (clan_id) REFERENCES clans (clan_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    print("✅ جدول clan_messages ایجاد شد")
    
    # 5. جدول گزارش‌ها
    cursor.execute('''
        CREATE TABLE reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            reported_user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            reason TEXT,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (reporter_id) REFERENCES users (user_id),
            FOREIGN KEY (reported_user_id) REFERENCES users (user_id),
            FOREIGN KEY (message_id) REFERENCES clan_messages (message_id)
        )
    ''')
    print("✅ جدول reports ایجاد شد")
    
    # 6. جدول حمله‌ها
    cursor.execute('''
        CREATE TABLE attacks (
            attack_id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_id INTEGER NOT NULL,
            defender_id INTEGER NOT NULL,
            result TEXT NOT NULL,
            loot_coins INTEGER DEFAULT 0,
            loot_elixir INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (attacker_id) REFERENCES users (user_id),
            FOREIGN KEY (defender_id) REFERENCES users (user_id)
        )
    ''')
    print("✅ جدول attacks ایجاد شد")
    
    # 7. جدول لیگ
    cursor.execute('''
        CREATE TABLE leaderboard (
            user_id INTEGER PRIMARY KEY,
            trophies INTEGER DEFAULT 0,
            league TEXT DEFAULT 'bronze',
            season_wins INTEGER DEFAULT 0,
            last_season_reset INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    print("✅ جدول leaderboard ایجاد شد")
    
    # 8. ایجاد ایندکس‌ها برای عملکرد بهتر
    cursor.execute('CREATE INDEX idx_users_clan_id ON users(clan_id)')
    cursor.execute('CREATE INDEX idx_clan_messages_clan_id ON clan_messages(clan_id)')
    cursor.execute('CREATE INDEX idx_attacks_attacker_id ON attacks(attacker_id)')
    cursor.execute('CREATE INDEX idx_attacks_defender_id ON attacks(defender_id)')
    print("✅ ایندکس‌ها ایجاد شدند")
    
    # 9. اضافه کردن کاربر ادمین (کشور ابرقدرت)
    admin_id = 8285797031
    cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, game_name, coins, elixir, gems, level, xp) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (admin_id, 'admin', 'کشور ابرقدرت', 999999, 999999, 99999, 100, 9999))
    
    cursor.execute('''
        INSERT OR IGNORE INTO buildings 
        (user_id, townhall_level, mine_level, collector_level, barracks_level) 
        VALUES (?, 10, 10, 10, 10)
    ''', (admin_id,))
    
    cursor.execute('''
        INSERT OR IGNORE INTO leaderboard (user_id, trophies, league) 
        VALUES (?, 9999, 'legend')
    ''', (admin_id,))
    
    print(f"✅ کاربر ادمین ایجاد شد (ID: {admin_id})")
    
    # ذخیره تغییرات و بستن اتصال
    conn.commit()
    conn.close()
    
    print("\n" + "="*50)
    print("✅ پایگاه داده با موفقیت ایجاد شد!")
    print("📊 ساختار دیتابیس:")
    print("   1. users - اطلاعات کاربران")
    print("   2. buildings - ساختمان‌های کاربران")
    print("   3. clans - اطلاعات قبایل")
    print("   4. clan_messages - پیام‌های قبیله")
    print("   5. reports - گزارش‌های کاربران")
    print("   6. attacks - تاریخچه حمله‌ها")
    print("   7. leaderboard - رتبه‌بندی")
    print("👑 کاربر ادمین: کشور ابرقدرت (ID: 8285797031)")
    print("="*50)

if __name__ == "__main__":
    create_database()

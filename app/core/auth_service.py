# filename: app/core/auth_service.py
import os
import sqlite3
import hashlib
import binascii
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from jose import jwt, JWTError
from app.core.app_constants import DEFAULT_AUTH_CREDENTIALS, PROJECT_ROOT

# === 配置 ===
CURRENT_FILE = os.path.abspath(__file__)
CORE_DIR = os.path.dirname(CURRENT_FILE)
APP_DIR = os.path.dirname(CORE_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "user_data.db")
SECRET_FILE = os.path.join(PROJECT_ROOT, ".secret.key")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 

class AuthService:
    def __init__(self):
        self.secret_key = self._load_or_generate_key()
        self._init_db()

    def _load_or_generate_key(self):
        """加载或生成持久化的加密密钥"""
        if os.path.exists(SECRET_FILE):
            try:
                with open(SECRET_FILE, "r") as f:
                    key = f.read().strip()
                    if key: return key
            except: pass
        
        # 生成新的强随机密钥 (32 bytes hex)
        new_key = secrets.token_hex(32)
        try:
            with open(SECRET_FILE, "w") as f:
                f.write(new_key)
            # 在 Windows 上尝试隐藏文件 (可选)
            if os.name == 'nt':
                os.system(f'attrib +h "{SECRET_FILE}"')
        except:
            print("⚠️ 警告: 无法写入密钥文件，本次运行将使用临时密钥。")
        
        return new_key

    def _init_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (username TEXT PRIMARY KEY, 
                          password_hash TEXT, 
                          salt TEXT, 
                          role TEXT, 
                          display_name TEXT,
                          created_at TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS audit_logs
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          username TEXT,
                          action TEXT,
                          ip TEXT,
                          timestamp TEXT)''')
            
            # 初始化默认用户
            for username, info in DEFAULT_AUTH_CREDENTIALS.items():
                self._create_user_if_not_exists(c, username, info["password"], info["role"], info["display_name"])
            conn.commit()

    def _create_user_if_not_exists(self, cursor, username, pwd, role, name):
        cursor.execute("SELECT 1 FROM users WHERE username=?", (username,))
        if not cursor.fetchone():
            salt = os.urandom(16).hex()
            pwd_hash = self._hash_password(pwd, salt)
            cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", 
                           (username, pwd_hash, salt, role, name, datetime.now().isoformat()))
            print(f"🔒 [Auth] 初始化用户: {username} ({role})")

    # === [New] 管理接口 ===
    def get_all_users(self) -> List[dict]:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT username, role, display_name, created_at FROM users")
            return [{"username": r[0], "role": r[1], "name": r[2], "created_at": r[3]} for r in c.fetchall()]

    def create_user(self, username, password, role, name):
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM users WHERE username=?", (username,))
            if c.fetchone(): return False, "用户已存在"
            
            salt = os.urandom(16).hex()
            pwd_hash = self._hash_password(password, salt)
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", 
                      (username, pwd_hash, salt, role, name, datetime.now().isoformat()))
            conn.commit()
            return True, "创建成功"

    def delete_user(self, username):
        if username == "admin": return False, "不能删除超级管理员"
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM users WHERE username=?", (username,))
            conn.commit()
            return True, "删除成功"

    # === 密码学方法 ===
    def _hash_password(self, password: str, salt: str) -> str:
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 100000)
        return binascii.hexlify(dk).decode()

    def verify_password(self, username: str, plain_password: str) -> bool:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("SELECT password_hash, salt FROM users WHERE username=?", (username,))
                row = c.fetchone()
                
                if not row: return False
                
                stored_hash, salt = row
                computed_hash = self._hash_password(plain_password, salt)
                
                return stored_hash == computed_hash
        except Exception as e:
            print(f"Auth Error: {e}")
            return False

    def get_user_role(self, username: str):
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT role, display_name FROM users WHERE username=?", (username,))
            row = c.fetchone()
            return {"role": row[0], "name": row[1]} if row else None

    # === JWT Token ===
    def create_access_token(self, data: dict):
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self.secret_key, algorithm=ALGORITHM)

    def decode_token(self, token: str) -> Optional[dict]:
        try:
            return jwt.decode(token, self.secret_key, algorithms=[ALGORITHM])
        except JWTError: return None

    # === 审计 ===
    def log_action(self, username, action, ip="Unknown"):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.cursor().execute("INSERT INTO audit_logs (username, action, ip, timestamp) VALUES (?, ?, ?, ?)",
                                      (username, action, ip, datetime.now().isoformat()))
        except: pass

auth = AuthService()
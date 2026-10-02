# filename: tools/user_manager.py
import sys
import os
import argparse

# 将项目根目录加入路径，以便导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.auth_service import auth, DB_PATH
import sqlite3
import datetime

def list_users():
    print(f"\n📋 当前用户列表 ({DB_PATH}):")
    print("-" * 60)
    print(f"{'Username':<15} {'Role':<10} {'Name':<20} {'Created At'}")
    print("-" * 60)
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT username, role, display_name, created_at FROM users")
        for row in c.fetchall():
            print(f"{row[0]:<15} {row[1]:<10} {row[2]:<20} {row[3]}")
    print("-" * 60 + "\n")

def add_user(username, password, role, name):
    print(f"➕ 正在添加用户: {username} ...")
    
    # 检查是否存在
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE username=?", (username,))
        if c.fetchone():
            print(f"❌ 错误: 用户名 '{username}' 已存在！")
            return

        # 使用 auth_service 的加密逻辑
        salt = os.urandom(16).hex()
        pwd_hash = auth._hash_password(password, salt)
        
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", 
                  (username, pwd_hash, salt, role, name, datetime.datetime.now().isoformat()))
        conn.commit()
        print(f"✅ 用户 '{username}' 创建成功！")

def delete_user(username):
    if username == "admin":
        print("❌ 无法删除超级管理员！")
        return
        
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE username=?", (username,))
        if c.rowcount > 0:
            conn.commit()
            print(f"🗑️ 用户 '{username}' 已删除。")
        else:
            print(f"⚠️ 用户 '{username}' 不存在。")

def main():
    parser = argparse.ArgumentParser(description="AI Bridge 用户管理工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # List
    subparsers.add_parser("list", help="列出所有用户")

    # Add
    add_parser = subparsers.add_parser("add", help="添加新用户")
    add_parser.add_argument("username", help="登录账号")
    add_parser.add_argument("password", help="登录密码")
    add_parser.add_argument("--role", default="user", choices=["developer", "vip", "user", "guest"], help="角色权    限")
    add_parser.add_argument("--name", default="新用户", help="显示昵称")

    # Delete
    del_parser = subparsers.add_parser("del", help="删除用户")
    del_parser.add_argument("username", help="要删除的账号")

    args = parser.parse_args()

    if args.command == "list":
        list_users()
    elif args.command == "add":
        add_user(args.username, args.password, args.role, args.name)
    elif args.command == "del":
        delete_user(args.username)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
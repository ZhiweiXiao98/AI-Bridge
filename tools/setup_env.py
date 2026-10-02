
import subprocess
import sys

def setup():
    print("🔄 Starting Environment Setup (Inside Docker)...")
    try:
        # 升级 pip
        print("⬆️ Upgrading pip...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "--no-cache-dir"], check=True)
        
        # 安装 pytest requests
        pkgs = ["pytest", "requests"]
        print(f"📦 Installing: {', '.join(pkgs)}...")
        subprocess.run([sys.executable, "-m", "pip", "install"] + pkgs + ["--no-cache-dir"], check=True)
        
        print("\n✅ Installation Complete!")
        
        # 列出包
        res = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True)
        print("\n📊 Installed Packages:")
        print(res.stdout)
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Setup Failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    setup()

# create_icons.py (工具脚本)
import os
from PIL import Image # 需要安装 Pillow: pip install Pillow

def create_placeholder_icon(name, color):
    # 确保目录存在
    path = "assets/icons"
    if not os.path.exists(path):
        os.makedirs(path)
    
    # 创建一个 64x64 的纯色图片
    img = Image.new('RGBA', (64, 64), color)
    file_path = os.path.join(path, f"{name}.png")
    img.save(file_path)
    print(f"✅ 已创建图标: {file_path}")

if __name__ == "__main__":
    # 创建不同颜色的占位图
    create_placeholder_icon("chat", (100, 149, 237, 255))   # 蓝色
    create_placeholder_icon("draw", (255, 105, 180, 255))   # 粉色
    create_placeholder_icon("video", (147, 112, 219, 255))  # 紫色
    create_placeholder_icon("music", (60, 179, 113, 255))   # 绿色
    create_placeholder_icon("settings", (128, 128, 128, 255)) # 灰色
    print("\n🎉 图标创建完成！请在 assets/icons 目录下查看。")
    print("👉 后续你可以用自己的精美 PNG 图标替换这些文件。")

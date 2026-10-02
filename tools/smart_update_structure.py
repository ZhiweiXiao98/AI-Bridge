# filename: tools/smart_update_structure.py
import os
import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_MD = os.path.join(PROJECT_ROOT, "docs", "PROJECT_STRUCTURE_DUMP.md")

# 维护者定义的“灵魂备注库”：确保每一个核心文件都有小白能懂的解释
KNOWLEDGE_BASE = {
    # 核心大脑
    "app/core/agent_manager.py": "🧠 智脑决策：负责分析 AI 的回复，决定是该改代码、跑测试还是回滚文件。",
    "app/core/auth_service.py": "🔐 安全门禁：负责用户的登录校验、密码加密以及权限管理。",
    "app/core/config.py": "⚙️ 配置中心：负责读取软件的各种开关设置（如端口、路径等）。",
    "app/core/connection_manager.py": "🔌 通讯枢纽：专门盯着谁在线，负责把消息精准地发给每一个人。",
    "app/core/docker_manager.py": "🐳 沙盒指挥官：管理 Docker 容器，让代码在隔离的‘实验室’里安全运行。",
    "app/core/self_update.py": "🔄 进化专家：负责下载最新补丁，让软件实现‘在线自我升级’。",
    "app/core/worker.py": "🧵 核心动力机：软件的主引擎，协调浏览器控制和后台任务的主循环。",
    "app/core/engine/conversation_engine.py": "🧠 记忆索引：通过指纹算法，让软件记住当前的对话进度和位置。",
    "app/core/utils/error_reporter.py": "🚨 故障分析员：当程序出异常时，负责收集日志并生成诊断报告。",
    "app/core/remote_worker.py": "🧵 远程工作者：负责处理来自服务器的异步指令和心跳包。",
    "app/core/git_manager.py": "📁 仓库管家：负责代码的自动备份、提交和清理旧分支。",

    # 业务服务
    "app/core/services/file_service.py": "📂 文件管家：负责代码的物理保存，存之前会检查语法是否有错。",
    "app/core/services/scheduler_service.py": "📋 任务指挥：管理任务队列，确保各项操作按顺序排队执行。",
    "app/core/services/state_service.py": "💾 状态记录器：把聊天进度、窗口位置等实时保存到硬盘，防止丢失。",
    "app/core/services/tool_router_service.py": "🚦 指令分发：智能判断 AI 给出的代码是该保存，还是该进沙盒跑。",
    "app/core/services/update_service.py": "📦 更新分发商：负责把最新的代码补丁整理好发给客户端。",
    "app/core/services/context_pack_service.py": "📦 上下文打包：负责把相关的代码文件压缩，喂给 AI 进行分析。",

    # 操控驱动
    "app/core/driver/connection.py": "🔗 浏览器连线员：建立软件与 Chrome 浏览器之间的秘密通讯渠道。",
    "app/core/driver/interaction.py": "🖱️ 模拟操作手：像真手一样点击按钮、打字、粘贴图片和滚动页面。",
    "app/core/driver/parser.py": "🧹 内容清洗员：专门从杂乱的网页代码中提取出干净的代码段。",

    # UI 界面
    "app/ui/main_window.py": "🏗️ 软件主外壳：界面的总框架，负责侧边栏和全屏遮罩动画。",
    "app/ui/styles.qss": "🎨 皮肤：定义了软件所有按钮、背景的颜色和圆角样式。",
    "app/ui/components/chat.py": "💬 聊天气泡：定义了对话框中文字和代码块的精美外观。",
    "app/ui/components/editor.py": "🖍️ 代码编辑器：提供了一个带颜色高亮、行号的内置代码窗口。",
    "app/ui/components/input.py": "⌨️ 增强输入框：支持快捷键和附件拖拽的输入组件。",
    "app/ui/components/overlay.py": "🎭 全屏遮罩：在加载或出错时，给软件盖上一层保护帘并显示提示。",
    "app/ui/pages/chat/page.py": "🖼️ 聊天主版面：软件的核心对话界面，把所有组件粘合在一起。",
    "app/ui/pages/chat/input_area.py": "⌨️ 打字区：集成了发送按钮、图片粘贴预览和附件上传进度。",
    "app/ui/pages/chat/message_area.py": "📜 消息滚动区：负责聊天历史的顺滑加载和自动滚到底部。",
    "app/ui/pages/console_page.py": "🛠️ 管理员控制台：查看服务器运行日志和用户管理的专业界面。",
}

def generate_structure():
    print("🕵️ 实地测绘开始：正在递归扫描物理文件夹...")
    
    sections = {
        "🚀 入口启动 (Launchers)": [],
        "🧠 系统大脑 (App Core)": [],
        "🧩 后台服务 (Services)": [],
        "⚙️ 模拟操控 (Driver)": [],
        "🖼️ 交互界面 (UI & Pages)": [],
        "🛠️ 辅助与运维 (Tools & Ops)": [],
        "🧪 自动化体检 (Testing)": []
    }

    # 真正的递归扫描，不漏掉任何一个文件
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # 忽略掉无关目录
        dirs[:] = [d for d in dirs if d not in {
            '.git', '__pycache__', '.venv', 'node_modules', '_docker_env', 'dist', 'build',
            '.worktrees', '.spectrai-worktrees', '.agents', '.codex', '.claude',
            '.trae', '.codebuddy', '.workbuddy', '.config', '.pytest_cache',
            'knowledge_bases', '_knowledge_base', '_knowledge_base_v2',
            '_knowledge_base_v2_corrupted', '_test_chroma_db', 'logs', 'export',
            'temp_uploads', 'ai对话截图', '导出HTML',
        }]
        
        for file in files:
            if file.startswith('.') or file in {"Thumbs.db", "FULL_PROJECT_CONTEXT.txt", "PROJECT_STRUCTURE_DUMP.md"}:
                continue
                
            full_path = os.path.join(root, file).replace("\\", "/")
            rel_path = os.path.relpath(full_path, PROJECT_ROOT).replace("\\", "/")
            
            # 根据知识库获取描述，如果没有则赋予一个基于路径的逻辑描述
            desc = KNOWLEDGE_BASE.get(rel_path)
            if not desc:
                if rel_path.startswith("tests/"): desc = "🧪 自动化体检：负责测试特定功能是否依然运行正常。"
                elif rel_path.startswith("tools/"): desc = "🔧 辅助工具：帮助开发者管理环境、用户或同步文档。"
                elif rel_path.endswith(".py"): desc = "项目逻辑组件。"
                elif rel_path.endswith(".ini"): desc = "配置文件：存储本地的界面记忆和参数。"
                elif rel_path.endswith(".db"): desc = "数据金库：存储用户信息和操作日志的数据库。"
                else: desc = "资源文件。"

            row = f"| `{rel_path}` | {desc} |"

            # 归类
            if rel_path.startswith(('start_', 'server.py', 'boot_')):
                sections["🚀 入口启动 (Launchers)"].append(row)
            elif "app/core/services" in rel_path:
                sections["🧩 后台服务 (Services)"].append(row)
            elif "app/core/driver" in rel_path:
                sections["⚙️ 模拟操控 (Driver)"].append(row)
            elif "app/core" in rel_path:
                sections["🧠 系统大脑 (App Core)"].append(row)
            elif "app/ui" in rel_path:
                sections["🖼️ 交互界面 (UI & Pages)"].append(row)
            elif "tests/" in rel_path:
                sections["🧪 自动化体检 (Testing)"].append(row)
            else:
                sections["🛠️ 辅助与运维 (Tools & Ops)"].append(row)

    # 组装 Markdown
    md = [
        "# AI Bridge 文件扫描结果",
        f"> **最后同步**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "> 自动生成的辅助清单。当前模块职责请看 [项目结构导航](项目结构导航.md)。",
        "\n---"
    ]

    for title, items in sections.items():
        if items:
            md.append(f"\n## {title}")
            md.append("| 文件路径 | 它扮演什么角色？(大白话解析) |")
            md.append("| :--- | :--- |")
            md.extend(sorted(items))

    # 物理写入
    os.makedirs(os.path.dirname(TARGET_MD), exist_ok=True)
    with open(TARGET_MD, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    
    print(f"✅ 实地测绘完成。共计记录 {sum(len(v) for v in sections.values())} 个文件。")

if __name__ == "__main__":
    generate_structure()

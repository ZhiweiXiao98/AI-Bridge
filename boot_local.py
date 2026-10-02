"""AI Bridge 完整本地客户端：原生界面 + 本地 Worker + 内置 Pi 运行时。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


def select_startup_mode(explicit, saved, smoke=False):
    mode = explicit or ("api" if smoke else saved)
    return mode if mode in {"api", "browser"} else "api"


def _stdio(home: Path):
    # --windowed 冻结程序没有控制台，旧核心仍有 print 调用。
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            stream = open(home / "local-startup.log", "a", encoding="utf-8", buffering=1)
            setattr(sys, name, stream)
        elif hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    started_at = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("api", "browser"), default=None)
    smoke_options = parser.add_mutually_exclusive_group()
    smoke_options.add_argument("--local-smoke-test", action="store_true", help="只使用本机模拟模型验证完整链路")
    smoke_options.add_argument("--local-browser-smoke-test", action="store_true", help="使用独立 Chrome 和本机模拟网页验证浏览器模式")
    smoke_options.add_argument("--local-resume-smoke-test", action="store_true", help="仅重开先前自检产生的专用数据")
    smoke_options.add_argument("--local-native-smoke-test", action="store_true", help="仅验证冻结程序的原生主窗口启动与退出")
    args = parser.parse_args(argv)
    smoke = args.local_smoke_test or args.local_resume_smoke_test or args.local_browser_smoke_test or args.local_native_smoke_test
    if args.local_smoke_test or args.local_browser_smoke_test or args.local_native_smoke_test:
        supplied_home = os.environ.get("AI_BRIDGE_LOCAL_HOME")
        if not supplied_home:
            parser.error("自检必须通过 AI_BRIDGE_LOCAL_HOME 指定一个新的空目录，不能使用真实用户数据")
        test_home = Path(supplied_home).expanduser()
        if test_home.exists() and any(test_home.iterdir()):
            parser.error("自检数据目录不是空目录；请指定新的空目录，保留已有会话和配置")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if args.local_resume_smoke_test:
        supplied_home = os.environ.get("AI_BRIDGE_LOCAL_HOME")
        if not supplied_home or not (Path(supplied_home) / "local-smoke.json").is_file():
            parser.error("恢复自检只能使用上一轮完整自检的专用数据目录")
    from app.core.local_paths import configure_local_paths
    home = configure_local_paths()
    _stdio(home)
    if args.local_native_smoke_test:
        from app.core.local_gui_probe import initial_report, write_report
        # Leave a safe stage marker even if loading the native QPA plugin aborts.
        write_report(home, initial_report())

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    app = QApplication([sys.argv[0]])
    app.setOrganizationName("AIBridge")
    app.setApplicationName("AI-Bridge-Local")
    lock = QLockFile(str(home / ".local-client.lock"))
    if not lock.tryLock(100):
        if not smoke:
            QMessageBox.information(None, "AI Bridge 已在运行", "同一数据目录已有本地客户端，请切回已打开的窗口。")
        return 2

    worker = window = browser_fixture = None
    native_old_hook = None
    native_failures = []
    splash = QLabel("AI Bridge\n正在加载本地核心与界面…")
    splash.setWindowTitle("启动完整本地客户端")
    splash.setMinimumSize(420, 100)
    splash.show()
    app.processEvents()
    try:
        if args.local_native_smoke_test:
            # Catch startup slots before constructing/showing the main window,
            # including event processing inside its initialization helpers.
            native_old_hook = sys.excepthook
            sys.excepthook = lambda *_: native_failures.append(True)
        from app.core.config import ConfigManager
        # ConfigManager 的导入会生成默认配置；单独标识首次本地配置，保留所有现有设置。
        marker = home / ".local-initialized"
        if not marker.exists():
            config = ConfigManager.load()
            config["startup_mode"] = "api"
            # 后台建议可能调用模型，新安装由用户在设置中主动开启。
            config["subagent"] = {**config.get("subagent", {}), "enabled": False}
            ConfigManager.save(config)
            marker.write_text("1\n", encoding="utf-8")

        saved_mode = ConfigManager.load().get("startup_mode", "api")
        args.mode = select_startup_mode(args.mode, saved_mode, smoke)
        if args.local_native_smoke_test:
            args.mode = "api"  # Never launch Chrome or call a model in this probe.
        if args.local_browser_smoke_test:
            from app.core.local_selftest import prepare_browser_selftest
            browser_fixture = prepare_browser_selftest(home)
            args.mode = "browser"

        from app.core.project_context import ProjectContext
        context = ProjectContext.initialize()
        workspace = home / "workspace"
        workspace.mkdir(exist_ok=True)
        if not args.local_smoke_test:
            context.restore_last_project()
        if context.get_project_root() == str(home):
            context.switch_to(str(workspace))

        from app.core.worker import WorkerThread
        from app.ui.main_window import MainWindow
        worker = WorkerThread(startup_mode=args.mode)
        # 初始化本地数据源不发送模型请求；随后由同一个 Worker 接受 UI 控制。
        if args.mode == "api":
            worker._init_api_source()
            if worker.api_source is None:
                raise RuntimeError("本地 API 核心初始化失败，请查看 local-startup.log")
        window = MainWindow(worker_core=worker, user_profile={"role": "developer", "username": "本地用户"})
        window.chat_page.on_mode_switch(args.mode)
        window.setWindowTitle("AI Bridge · 完整本地客户端")
        def remember_mode(mode):
            if not smoke and mode in {"api", "browser"}:
                saved = ConfigManager.load()
                saved["startup_mode"] = mode
                ConfigManager.save(saved)
        worker.mode_changed_signal.connect(remember_mode)
        remember_mode(args.mode)
        window.show()
        splash.close()
        if args.local_native_smoke_test:
            from app.core.local_gui_probe import run_native_smoke
            result = run_native_smoke(app, window, worker, home, started_at, failures=native_failures)
            return 0 if result["passed"] else 1
        app.processEvents()

        if smoke:
            from app.core.local_selftest import run_selftest, run_resume_selftest
            # Qt 槽中的未处理异常默认只打印，必须使自检失败，不能误报界面已通过。
            failures = []
            old_hook = sys.excepthook
            def capture_exception(kind, value, tb):
                failures.append(f"{kind.__name__}: {value}")
                old_hook(kind, value, tb)
            sys.excepthook = capture_exception
            try:
                if args.local_browser_smoke_test:
                    from app.core.local_selftest import run_browser_selftest
                    result = run_browser_selftest(app, window, worker, home, browser_fixture)
                else:
                    runner = run_selftest if args.local_smoke_test else run_resume_selftest
                    result = runner(app, window, worker, home)
                window.close()
                app.processEvents()
                if failures:
                    raise RuntimeError("界面自检发现未处理异常：" + "; ".join(failures))
            finally:
                sys.excepthook = old_hook
            import json
            report_name = ("local-browser-smoke.json" if args.local_browser_smoke_test else
                           "local-smoke.json" if args.local_smoke_test else "local-resume-smoke.json")
            (home / report_name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0

        # 首次配置仍直接使用现有设置页，不引入远程地址或额外应用账号。
        from app.core.api_mode_config import APIModeConfigManager
        profiles = APIModeConfigManager.load().get("profiles", {})
        configured = any(p.get("api_key") for p in profiles.values())
        if args.mode == "browser":
            window.statusBar().showMessage("浏览器模式：在连接设置中填写目标网站，使用专用 Chrome 窗口登录。", 0)
        elif not configured:
            window.statusBar().showMessage("本地核心已就绪。请在设置中填写模型服务、地址和密钥，然后新建 Pi 对话。", 0)
        help_menu = window.menuBar().addMenu("本地运行")
        action = help_menu.addAction("运行环境与使用说明")
        def show_environment():
            from app.core.agent_runtime.registry import runtime_options
            pi = next(item for item in runtime_options() if item["id"] == "pi")
            QMessageBox.information(window, "完整本地客户端", (
                "界面、会话、文件工具和 Pi 调度均在这台电脑运行，无需 AI Bridge 远程服务器。\n\n"
                f"Pi：{'可用' if pi['available'] else pi['reason']}\n"
                f"数据目录：{home}\n\n"
                "模型：在设置中配置自己的 API 服务；只有发送请求才调用模型，可能产生提供商费用。\n"
                "网页模式：使用已安装的 Chrome 和独立资料目录；在连接设置中指定网站，必要时明确允许获取官方匹配驱动。网页账号请自行登录。\n"
                "Docker 沙箱：需要用户安装并启动 Docker 和准备沙箱镜像；应用不会自动下载或启动 Docker。\n"
                "知识检索：已包含 RAG 引擎，首次使用向量模型时需要下载模型。\n"
                "开发工具：项目 Python、Git、Rhino 由需要这些能力的用户另外配置。\n"
                "后台建议：新安装默认关闭，可在设置中主动开启。"
            ))
        action.triggered.connect(show_environment)
        app.aboutToQuit.connect(worker.stop_worker)
        exit_code = app.exec()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        splash.close()
        if not smoke:
            QMessageBox.critical(None, "本地客户端启动失败", f"{type(exc).__name__}: {exc}\n\n请检查安装完整性。日志在：{home / 'local-startup.log'}")
        return 1
    finally:
        if native_old_hook is not None:
            sys.excepthook = native_old_hook
        if worker is not None:
            worker.stop_worker()
        if browser_fixture is not None:
            browser_fixture.close()
        lock.unlock()

    if exit_code == 42:
        command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen(command + ["--mode", worker.mode], env=env, cwd=str(home))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

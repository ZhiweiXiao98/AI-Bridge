"""完整安装包离线自检；仅显式 --local-smoke-test 启用，不调用外部模型。"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import threading
import time


def wait_for(app, predicate, message, timeout=30, failure_reason=None, timeout_detail=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if failure_reason is not None:
            failure = failure_reason()
            if failure:
                raise RuntimeError("本地自检提前失败：" + str(failure))
        if predicate():
            return
        time.sleep(0.02)
    detail = str(timeout_detail() or "") if timeout_detail is not None else ""
    raise RuntimeError("本地自检超时：" + message + ("；" + detail if detail else ""))


class FixtureProvider(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.requests = []
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(3)


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        if size > 2_000_000:
            self.send_error(413)
            return
        request = json.loads(self.rfile.read(size))
        messages = request.get("messages", [])
        self.server.requests.append(messages)
        user = next((str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"), "")
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        has_tool_result = any(m.get("role") == "tool" for m in messages[last_user + 1:])
        want_tool = any(x in user for x in ("读取", "拒绝", "取消")) and not has_tool_result
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        def emit(delta, finish=None):
            packet = {"id": "local-selftest", "object": "chat.completion.chunk", "created": 1,
                      "model": "local-fixture", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
            self.wfile.flush()
        if want_tool:
            args = ({"operation": "read_file", "path": "selftest.txt"} if "读取" in user else
                    {"operation": "write_file", "path": "must-not-exist.txt", "content": "denied"})
            emit({"role": "assistant", "tool_calls": [{"index": 0, "id": "selftest-call",
                  "type": "function", "function": {"name": "file_operations", "arguments": json.dumps(args)}}]})
            emit({}, "tool_calls")
        else:
            emit({"role": "assistant", "content": "本地模拟模型已完成，未连接外部服务"})
            emit({}, "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run_selftest(app, window, worker, home: Path):
    """真实 Pi SDK、真实文件工具、真实 Qt 审批对话框；模型响应由本机 HTTP fixture 提供。"""
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QMessageBox
    from app.core.api_mode_config import APIModeConfigManager
    from app.core.agent_runtime.registry import runtime_options
    from app.core.project_context import ProjectContext
    from app.core.conversation_store import ConversationStore
    from app.core.local_paths import resource_root
    from app.core.agent_runtime.paths import node_executable
    import subprocess
    import importlib

    core_imports = ["chromadb", "fastembed", "onnxruntime", "docker", "selenium",
                    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"]
    for module in core_imports:
        importlib.import_module(module)
    if window.embedded_browser_panel.render_mode == "fallback":
        raise RuntimeError("完整本地包的 Qt WebEngine 未能加载；不能用静默降级冒充通过")

    if hasattr(worker, "_request_send"):
        raise RuntimeError("自检错误地使用了远程 Worker")
    pi = next(item for item in runtime_options() if item["id"] == "pi")
    if not pi["available"]:
        raise RuntimeError("Pi 不可用：" + pi["reason"])
    skills = worker.agent.skills_manager
    if not skills.get_skill_instance("file_operations"):
        raise RuntimeError("完整文件工具未随应用加载")
    if not window.plugin_loader.plugins:
        raise RuntimeError("内置面板插件未随应用加载")
    project = Path(ProjectContext.get().get_project_root())
    (project / "selftest.txt").write_text("AI Bridge 本地文件工具自检\n", encoding="utf-8")
    provider = FixtureProvider()
    config = APIModeConfigManager.load()
    original = json.loads(json.dumps(config))
    profile = config["profiles"][config["active_profile"]]
    profile.update(api_key="local-fixture-not-a-secret", model="local-fixture", provider="openai_compatible",
                   base_url=f"http://127.0.0.1:{provider.server_port}/v1", supports_tools=True,
                   tool_calling_mode="native_tools", tool_capability={"status": "supported", "protocol": "native_tools"})
    APIModeConfigManager.save(config)
    worker.api_source.reload_runtime_config()
    page = window.chat_page
    page.on_mode_switch("api")
    if worker.mode != "api" or page.current_mode != "api" or page.session_tabs.currentIndex() != 1:
        raise RuntimeError("本地核心与界面模式不一致")
    terminals = []
    worker.api_round_state_signal.connect(lambda payload: terminals.append(payload) if payload.get("state") in {"finalized", "failed", "cancelled"} else None)

    def send(text):
        previous = len(terminals)
        result = worker.api_send(text)
        if not isinstance(result, dict) or result.get("ok") is not True:
            detail = result.get("error") if isinstance(result, dict) else "Pi 未返回请求接受确认"
            raise RuntimeError("本地自检发送被拒绝：" + str(detail or "未知错误"))
        return previous, result.get("request_id")

    def approval_ended_early(marker):
        previous, request_id = marker
        matching = [item for item in terminals[previous:] if item.get("request_id") == request_id]
        if matching:
            terminal = matching[-1]
            return (f"Pi 在工具审批前已结束，state={terminal.get('state')}，"
                    f"message={terminal.get('message') or terminal.get('error') or '无错误详情'}；"
                    f"本机模拟模型收到请求数={len(provider.requests)}")
        return None

    try:
        worker.api_new_conversation("完整本地自检", runtime="pi")
        app.processEvents()
        store = worker.api_source.conv_store
        conversation = store.active_id
        previous = send("本地自检读取")
        wait_for(app, lambda: page._api_approval_dialog is not None, "等待真实工具审批界面",
                 failure_reason=lambda: approval_ended_early(previous))
        if (project / "must-not-exist.txt").exists():
            raise RuntimeError("审批前不应执行写入")
        page._api_approval_dialog.button(QMessageBox.StandardButton.Yes).click()
        wait_for(app, lambda: not worker.agent_runtime_bridge.is_running and terminals, "批准工具后完成对话")
        if not terminals or terminals[-1]["state"] != "finalized":
            raise RuntimeError("Pi 未完成真实工具往返：" + repr(terminals[-1:]))
        history = store.get_display_messages(conversation)
        if not any(m.get("role") == "tool" and "本地文件工具自检" in str(m) for m in history):
            raise RuntimeError("Pi 工具结果没有进入会话历史")
        session = store.get_runtime_session(conversation)["session_path"]
        if not Path(session).is_file():
            raise RuntimeError("Pi 未保存原生会话")

        send("本地自检恢复")
        wait_for(app, lambda: not worker.agent_runtime_bridge.is_running and len(terminals) >= 2, "从原生会话继续")
        if store.get_runtime_session(conversation)["session_path"] != session:
            raise RuntimeError("续聊没有恢复同一原生会话")
        if sum(m.get("role") == "user" for m in provider.requests[-1]) < 2:
            raise RuntimeError("续聊未携带上轮历史")

        previous = send("本地自检拒绝")
        wait_for(app, lambda: page._api_approval_dialog is not None, "拒绝工具审批",
                 failure_reason=lambda: approval_ended_early(previous))
        page._api_approval_dialog.button(QMessageBox.StandardButton.No).click()
        wait_for(app, lambda: not worker.agent_runtime_bridge.is_running and len(terminals) >= 3, "拒绝后结束")
        if (project / "must-not-exist.txt").exists():
            raise RuntimeError("被拒绝的文件工具仍发生了写入")

        previous = send("本地自检取消")
        wait_for(app, lambda: page._api_approval_dialog is not None, "取消待批准请求",
                 failure_reason=lambda: approval_ended_early(previous))
        page._stop_api_request()
        wait_for(app, lambda: not worker.agent_runtime_bridge.is_running and len(terminals) >= 4, "取消请求与 Pi 退出")
        if (project / "must-not-exist.txt").exists() or ProjectContext.get()._runtime_leases:
            raise RuntimeError("取消后存在写入或未释放项目锁")
        reopened = ConversationStore(str(store.storage_dir))
        if not reopened.get_display_messages(conversation):
            raise RuntimeError("重新打开会话存储失败")
        report = {"mode": "local-worker", "remote_server_required": False,
                  "provider": "仅本机模拟模型，未测试真实收费 API", "python": platform.python_version(),
                  "qt": qVersion(), "node": subprocess.check_output([node_executable(), "--version"], text=True).strip(),
                  "pi_version": "0.99.1", "resource_root": str(resource_root()),
                  "skills": len(skills.skill_instances), "plugins": len(window.plugin_loader.plugins),
                  "selftest_conversation_id": conversation, "selftest_session_path": session,
                  "core_imports": core_imports, "embedding_model_not_downloaded": True,
                  "checks": ["本地Worker与完整主窗口", "真实Pi SDK对话", "真实Qt工具批准", "真实文件工具结果",
                             "原生会话保存及续聊", "工具拒绝不写文件", "工具取消不写文件", "项目锁释放", "历史重开"],
                  "optional_external_services": {"docker": "未连接，不自动拉镜像", "chrome": "未连接", "rag_models": "未下载", "real_provider": "未调用"}}
        worker.stop_worker()
        if worker.isRunning() or worker.agent_runtime_bridge.is_running:
            raise RuntimeError("退出后本地 Worker/Pi 仍在运行")
        report["checks"].append("Worker与Pi清理完成")
        return report
    finally:
        APIModeConfigManager.save(original)
        provider.close()


def run_resume_selftest(app, window, worker, home: Path):
    """第二个真实应用进程只重开上一轮专用会话，不启动模型服务或发送请求。"""
    from app.core.api_mode_config import APIModeConfigManager
    previous = json.loads((home / "local-smoke.json").read_text(encoding="utf-8"))
    if previous.get("provider") != "仅本机模拟模型，未测试真实收费 API":
        raise RuntimeError("恢复自检证据不是本机模拟测试，已停止")
    conversation = previous["selftest_conversation_id"]
    session = previous["selftest_session_path"]
    store = worker.api_source.conv_store
    wait_for(app, lambda: conversation in window.chat_page._api_conversations_by_id, "应用重启后的会话列表")
    if store.active_id != conversation or not store.get_display_messages(conversation):
        raise RuntimeError("应用重启没有恢复先前会话")
    if store.get_runtime_session(conversation).get("session_path") != session or not Path(session).is_file():
        raise RuntimeError("应用重启后的 Pi 原生会话指针不匹配")
    if any(profile.get("api_key") for profile in APIModeConfigManager.load().get("profiles", {}).values()):
        raise RuntimeError("模拟配置未恢复为空密钥")
    worker.stop_worker()
    if worker.isRunning() or worker.agent_runtime_bridge.is_running:
        raise RuntimeError("恢复自检结束后仍有任务运行")
    return {"mode": "local-worker", "conversation_id": conversation,
            "checks": ["应用重启后原会话可见", "应用重启后历史和Pi会话一致", "模拟模型配置已清除", "恢复自检退出完成"]}


def prepare_browser_selftest(home: Path):
    """仅在显式浏览器自检且新的隔离 HOME 内调用，测试路径不用于正常启动。"""
    import os
    from app.core.browser_fixture import BrowserFixture
    from app.core.config import ConfigManager
    paths = {}
    for key, name in (("chrome_binary", "AI_BRIDGE_TEST_CHROME"),
                      ("chromedriver_path", "AI_BRIDGE_TEST_CHROMEDRIVER")):
        path = Path(os.environ.get(name, ""))
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError("浏览器自检需要显式、已核验来源的程序路径：" + name)
        paths[key] = str(path)
    fixture = BrowserFixture(chunk_delay=0.15, initial_delay=0.6, chunk_size=3).start()
    try:
        config = ConfigManager.load()
        config.update(paths, browser_start_url=fixture.url, browser_source="external_chrome",
                      browser_headless=True, browser_allow_driver_download=False, startup_mode="browser")
        ConfigManager.save(config)
        return fixture
    except Exception:
        fixture.close()
        raise


def browser_selftest_probe(page, worker, fixture, stream_snapshot_count=0):
    """只输出隔离自检的计数和布尔值，不输出页面、消息、会话或路径。"""
    counts = fixture.snapshot()
    cached = page._browser_all_messages
    rendered = [getattr(bubble, "current_data", {}) for bubble in page.browser_msg_area.bubbles_cache]
    def has_final(messages):
        return "分块输出已完成" in json.dumps(messages, ensure_ascii=False, default=lambda _: "<non-json>")
    return {
        "fixture_counts": {key: counts.get(key, 0) for key in (
            "page_ready_count", "request_count", "chunk_count", "response_count", "cancel_count",
            "session_switch_count", "new_chat_count", "clear_count")},
        "last_restored_message_count": (fixture.page_ready_events[-1].get("restored_message_count", 0)
                                        if fixture.page_ready_events else 0),
        "worker_mode": worker.mode if worker.mode in {"api", "browser"} else "unknown",
        "ui_mode": page.current_mode if page.current_mode in {"api", "browser"} else "unknown",
        "worker_message_count": len(worker.last_messages_snapshot),
        "ui_cached_message_count": len(cached), "rendered_bubble_count": len(rendered),
        "final_marker_cached": has_final(cached), "final_marker_rendered": has_final(rendered),
        "stream_snapshot_count": stream_snapshot_count,
        "ui_busy": bool(page.browser_input_area.is_ai_busy),
        "ui_has_queued_message": page.browser_input_area.queued_payload is not None,
        "driver": worker.connector.conn.diagnostic_snapshot(),
    }


def run_browser_selftest(app, window, worker, home: Path, fixture):
    """真实 Chrome/ChromeDriver + Worker + Qt 发送、流式同步、停止及进程恢复。"""
    from PySide6.QtCore import qVersion
    page = window.chat_page
    checks = []
    browser_processes = []
    ui_stream_samples = set()

    def ui_text():
        value = json.dumps(page._browser_all_messages, ensure_ascii=False)
        if fixture.response_count == 0 and "本地浏览器测试回复" in value:
            ui_stream_samples.add(value)
        return value

    def session():
        return getattr(worker.connector.conn, "local_session", None)

    def ready():
        return worker.browser_command_bridge.ready and session() is not None and session().process is not None

    def browser_diagnostic():
        return json.dumps(browser_selftest_probe(page, worker, fixture, len(ui_stream_samples)),
                          ensure_ascii=False, sort_keys=True)

    def wait(predicate, message, timeout=30):
        wait_for(app, predicate, message, timeout=timeout, timeout_detail=browser_diagnostic)

    def rendered_text():
        return json.dumps([getattr(bubble, "current_data", {}) for bubble in page.browser_msg_area.bubbles_cache],
                          ensure_ascii=False, default=lambda _: "<non-json>")

    def send(text):
        wait(lambda: page.browser_input_area.send_btn.isEnabled() and not page.browser_input_area.is_ai_busy,
             "等待浏览器输入恢复可发送")
        page.browser_input_area.input_box.setPlainText(text)
        page.browser_input_area.send_btn.click()

    wait(ready, "真实浏览器、匹配驱动和输入页面就绪", timeout=50)
    if worker.mode != "browser" or page.current_mode != "browser" or page.session_tabs.currentIndex() != 0:
        raise RuntimeError("浏览器 Worker 与界面模式不一致")
    browser_processes.append(session().process)
    capabilities = worker.connector.driver.capabilities
    browser_version = capabilities["browserVersion"]
    driver_version = capabilities["chrome"]["chromedriverVersion"].split()[0]
    if browser_version.split(".")[0] != driver_version.split(".")[0]:
        raise RuntimeError("实际 Chrome 与驱动主版本不匹配")
    checks += ["真实Chrome与匹配驱动连接", "本地浏览器Worker与UI模式一致"]

    first = "界面真实发送第一条中文消息"
    send(first)
    wait(lambda: fixture.request_count == 1, "网页收到真实 UI 输入")
    wait(lambda: "分块输出已完成" in ui_text() and "分块输出已完成" in rendered_text()
         and fixture.response_count == 1, "网页流式最终回复同步缓存与真实气泡")
    if len(ui_stream_samples) < 2:
        raise RuntimeError("界面没有观察到至少两个真实浏览器流式快照")
    if first not in ui_text() or page.browser_input_area.input_box.toPlainText():
        raise RuntimeError("网页回执或成功发送后的草稿状态不正确")
    checks += ["真实浏览器发送与回执", "浏览器流式文本读取", "浏览器最终文本读取"]

    send("停止生成路径，保留当前部分回复并阻止排队消息自动发送")
    wait(lambda: fixture.request_count == 2 and page.browser_input_area.is_ai_busy, "浏览器第二轮生成中")
    page.browser_input_area.input_box.setPlainText("这条待发消息不能发给网页")
    page.browser_input_area.on_send()
    if page.browser_input_area.queued_payload is None:
        raise RuntimeError("没有建立真实 UI 待发队列")
    page.browser_stop_btn.click()
    wait(lambda: fixture.cancel_count == 1 and not worker.browser_command_bridge.cancel_pending, "真实网页停止按钮确认")
    deadline = time.monotonic() + 3.4
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if fixture.request_count != 2 or page.browser_input_area.queued_payload is not None:
        raise RuntimeError("停止后仍自动发送了已取消的队列")
    checks.append("浏览器停止生成")

    # 走真实客户端重连/正常关闭路径，让 Chrome 完成资料写盘。
    # 不用 SIGTERM/TerminateProcess 冒充正常关窗，也不宣称覆盖任意崩溃恢复。
    before_page_loads = fixture.page_ready_count
    old_process = session().process
    page._browser_all_messages = []
    page.browser_msg_area.render_messages([], "")
    page.browser_reconnect_btn.click()
    wait(lambda: ready() and session().process.pid != old_process.pid,
         "浏览器窗口关闭后真实新进程重连", timeout=60)
    browser_processes.append(session().process)
    if old_process.poll() is None:
        raise RuntimeError("新的浏览器已启动，但此前自有浏览器仍未退出；" + browser_diagnostic())
    wait(lambda: fixture.page_ready_count > before_page_loads, "新浏览器进程实际重新加载网页")
    restored = fixture.page_ready_events[-1]["restored_message_count"]
    if restored < 4:
        raise RuntimeError(f"新浏览器进程未完整恢复前两轮消息，实际恢复 {restored} 条；" + browser_diagnostic())
    wait(lambda: first in ui_text() and first in rendered_text(), "专用资料目录中的网页历史恢复")
    checks += ["浏览器断开后重连", "浏览器重启后重新连接"]
    page.browser_input_area.clear_inputs()
    send("重连后还能正常发送")
    wait(lambda: fixture.request_count == 3, "重连后的真实发送")
    wait(lambda: fixture.response_count == 2 and "重连后还能正常发送" in ui_text(), "重连后的真实回复")

    # 活动会话中只有侧栏图标入口，独立 tooltip 不会成为按钮文本。
    worker.new_chat()
    wait(lambda: fixture.snapshot()["new_chat_count"] == 1, "真实侧栏图标创建新会话")
    wait(lambda: not page.browser_input_area.is_ai_busy and not page._browser_all_messages,
         "新会话在本地界面显示为空")
    if fixture.snapshot()["clear_count"] != 0:
        raise RuntimeError("新建会话错误触发了清空历史")
    checks.append("浏览器侧栏图标新建会话")

    send("生成尚未完成时关闭客户端窗口")
    wait(lambda: fixture.request_count == 4 and page.browser_input_area.is_ai_busy, "窗口关闭前确实存在活动浏览器生成")
    window.close()
    wait(lambda: not worker.isRunning() and all(process.poll() is not None for process in browser_processes),
         "活动生成时关闭窗口并清理应用拥有的浏览器", timeout=25)
    checks.append("浏览器活动生成时关闭窗口")
    checks.append("浏览器与驱动所有权清理")
    return {"mode": "local-browser", "fixture": "loopback-html", "browser_version": browser_version,
            "chromedriver_version": driver_version, "real_site_visited": False, "qt": qVersion(),
            "checks": checks, "stream_snapshot_count": len(ui_stream_samples),
            "browser_process_restart": True, "application_process_restart": False,
            "browser_restart_method": "owned-graceful-reconnect", "crash_recovery_tested": False,
            "same_profile_history_restored": True, "cancelled_queue_sent": False,
            "request_count": fixture.request_count, "response_count": fixture.response_count}

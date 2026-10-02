"""在全新状态和无宿主 Python/Node 的 PATH 下检验冻结本地 UI、Worker 与真实 Pi 往返。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from local_build import NAME, NODE_VERSION, PI_VERSION, ROOT, configure_console, digest, write_json

REQUIRED_CHECKS = {
    "本地Worker与完整主窗口", "真实Pi SDK对话", "真实Qt工具批准", "真实文件工具结果",
    "原生会话保存及续聊", "工具拒绝不写文件", "工具取消不写文件", "项目锁释放", "历史重开", "Worker与Pi清理完成",
}
REQUIRED_IMPORTS = {
    "chromadb", "fastembed", "onnxruntime", "docker", "selenium",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
}
REQUIRED_RESUME_CHECKS = {
    "应用重启后原会话可见", "应用重启后历史和Pi会话一致", "模拟模型配置已清除", "恢复自检退出完成",
}
REQUIRED_BROWSER_CHECKS = {
    "真实Chrome与匹配驱动连接", "本地浏览器Worker与UI模式一致", "真实浏览器发送与回执",
    "浏览器流式文本读取", "浏览器最终文本读取", "浏览器停止生成", "浏览器断开后重连",
    "浏览器重启后重新连接", "浏览器与驱动所有权清理", "浏览器活动生成时关闭窗口",
}


def executable_path(output: Path) -> Path:
    if sys.platform == "darwin":
        return output / "dist" / f"{NAME}.app/Contents/MacOS/{NAME}"
    return output / "dist" / NAME / (NAME + (".exe" if sys.platform == "win32" else ""))


def smoke_environment(state: Path) -> dict:
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
               "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "DISPLAY", "WAYLAND_DISPLAY"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    empty_path = state / "empty-path"
    env.update(PATH=str(empty_path), AI_BRIDGE_LOCAL_HOME=str(state), QT_QPA_PLATFORM="offscreen",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ANONYMIZED_TELEMETRY="False")
    return env


def validate_report(runtime: dict, expected: dict) -> dict:
    if runtime.get("mode") != "local-worker" or runtime.get("remote_server_required") is not False:
        raise RuntimeError("冒烟测试未使用真正的本地 Worker")
    if runtime.get("node") != "v" + NODE_VERSION or runtime.get("pi_version") != PI_VERSION:
        raise RuntimeError("冻结包没有运行精确固定的 Node/Pi")
    if any(runtime.get(key) != expected[key] for key in ("python", "qt")):
        raise RuntimeError("冻结 Python/Qt 运行时与构建清单不一致")
    missing = REQUIRED_CHECKS - set(runtime.get("checks", []))
    if missing:
        raise RuntimeError("本地功能冒烟缺少必要证据：" + ", ".join(sorted(missing)))
    missing_imports = REQUIRED_IMPORTS - set(runtime.get("core_imports", []))
    if missing_imports:
        raise RuntimeError("冻结核心导入探针未通过：" + ", ".join(sorted(missing_imports)))
    if runtime.get("skills", 0) <= 0 or runtime.get("plugins", 0) <= 0:
        raise RuntimeError("本地技能或面板插件没有实际加载")
    # 不公开用户/runner 路径、日志、会话、模型请求或任意未知字段。
    return {key: runtime[key] for key in ("mode", "remote_server_required", "provider", "python", "qt", "node",
                                          "pi_version", "skills", "plugins", "checks", "core_imports", "optional_external_services")}


def surviving_children(observed: dict) -> list:
    import psutil
    survivors = []
    for pid, created in observed.items():
        try:
            child = psutil.Process(pid)
            if child.create_time() == created and child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                survivors.append(child)
        except psutil.NoSuchProcess:
            pass
    return survivors


def terminate_tree(process: subprocess.Popen, observed: dict) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            subprocess.run([str(Path(os.environ["SYSTEMROOT"]) / "System32/taskkill.exe"),
                            "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=20)
    # 主进程先退出也必须检查孤儿；只操作真实观察过且 create_time 相同的后代，避免 PID 复用。
    for child in surviving_children(observed):
        try:
            child.kill()
            child.wait(timeout=10)
        except __import__("psutil").NoSuchProcess:
            pass


def failure_diagnostic(log_path: Path, state: Path) -> str:
    """只取专用空 HOME 自检的错误摘要；不上传原始日志、会话或网页内容。"""
    messages = []
    for path in (log_path, state / "local-startup.log"):
        if not path.is_file():
            continue
        value = path.read_text(encoding="utf-8", errors="replace")[-64_000:]
        traceback_start = value.rfind("Traceback (most recent call last):")
        if traceback_start >= 0:
            lines = value[traceback_start:].splitlines()[:36]
        else:
            lines = [line for line in value.splitlines() if re.search(r"(?:Error|Exception|FATAL|failed|失败)", line)][-12:]
        text = "\n".join(lines)
        for private_path in (str(state), str(log_path.parent), str(ROOT), str(Path.home())):
            text = text.replace(private_path, "<自检目录>")
        text = re.sub(r'File "[^"\n]*[/\\]([^/\\"\n]+\.py)"', r'File "\1"', text)
        text = text.replace("local-fixture-not-a-secret", "<模拟凭证>")
        text = re.sub(r"(?i)(api[_-]?key|authorization|bearer)(\s*[:=]\s*|\s+)[^\s,;]+", r"\1=<已隐藏>", text)
        if text:
            messages.append(path.name + ":\n" + text)
    return "\n".join(messages) or "未找到可安全输出的 traceback；未上传原始日志或测试状态"


def run_application(executable: Path, argument: str, state: Path, env: dict, log_path: Path) -> dict:
    import psutil
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(executable), argument], cwd=state, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, **kwargs)
        observed = {}
        saw_node = False
        saw_chrome = False
        saw_driver = False
        expected_chrome = os.path.normcase(str(Path(env["AI_BRIDGE_TEST_CHROME"]).resolve())) if env.get("AI_BRIDGE_TEST_CHROME") else None
        expected_driver = os.path.normcase(str(Path(env["AI_BRIDGE_TEST_CHROMEDRIVER"]).resolve())) if env.get("AI_BRIDGE_TEST_CHROMEDRIVER") else None
        try:
            deadline = time.monotonic() + 300
            while process.poll() is None:
                try:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        observed[child.pid] = child.create_time()
                        saw_node = saw_node or child.name().lower() in {"node", "node.exe"}
                        if expected_chrome or expected_driver:
                            observed_exe = os.path.normcase(str(Path(child.exe()).resolve()))
                            saw_chrome = saw_chrome or observed_exe == expected_chrome
                            saw_driver = saw_driver or observed_exe == expected_driver
                except psutil.NoSuchProcess:
                    pass
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(str(executable), 300)
                time.sleep(0.05)
            code = process.wait()
            if code:
                raise RuntimeError(f"冻结本地冒烟失败（退出码 {code}）\n" + failure_diagnostic(log_path, state))
            shutdown_deadline = time.monotonic() + 10
            while surviving_children(observed) and time.monotonic() < shutdown_deadline:
                time.sleep(0.1)
            if surviving_children(observed):
                raise RuntimeError("主窗口退出后仍有观察到的子进程存活；已停止自检并清理本次进程树")
            if argument == "--local-smoke-test" and not saw_node:
                raise RuntimeError("未观察到实际 Node 子进程，不能证明冻结 Pi 的进程退出")
            if argument == "--local-browser-smoke-test" and not (saw_chrome and saw_driver):
                raise RuntimeError("没有观察到固定官方浏览器与驱动的真实子进程")
            return {"observed_descendant_count": len(observed), "observed_node": saw_node,
                    "observed_test_chrome": saw_chrome, "observed_test_chromedriver": saw_driver,
                    "all_observed_descendants_exited": True}
        finally:
            terminate_tree(process, observed)


def read_browser_fixture(path: Path) -> tuple[dict, dict]:
    from local_browser_fixture import selected_sources, test_platform
    runtime = json.loads(path.read_text(encoding="utf-8"))
    manifest_path = ROOT / "licenses/local/browser-test-sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = selected_sources(manifest, test_platform())
    if (runtime.get("version") != manifest["version"] or runtime.get("platform") != test_platform()
            or runtime.get("archives") != records or runtime.get("source_manifest_sha256") != digest(manifest_path)
            or runtime.get("not_in_application_bundle") is not True):
        raise RuntimeError("浏览器测试夹具来源与当前固定官方记录不符")
    for key, hash_key in (("chrome", "chrome_executable_sha256"), ("chromedriver", "chromedriver_executable_sha256")):
        executable = Path(runtime[key])
        if (not executable.is_absolute() or not executable.is_file()
                or not executable.resolve().is_relative_to((path.parent / "runtime").resolve())
                or digest(executable) != runtime[hash_key]):
            raise RuntimeError("浏览器测试程序不在专用夹具目录中或其字节已变化")
    safe = {key: runtime[key] for key in ("version", "platform", "archives", "source_manifest_sha256",
            "official_manifest_url", "chrome_executable_sha256", "chromedriver_executable_sha256", "not_in_application_bundle")}
    return runtime, safe


def validate_browser_report(report: dict, fixture: dict) -> dict:
    if report.get("mode") != "local-browser" or report.get("fixture") != "loopback-html" or report.get("real_site_visited") is not False:
        raise RuntimeError("浏览器自检没有使用真实本地 Worker 和仅回环测试页面")
    if report.get("browser_version") != fixture["version"] or report.get("chromedriver_version") != fixture["version"]:
        raise RuntimeError("实际浏览器/驱动 capabilities 与固定官方测试版本不一致")
    if not REQUIRED_BROWSER_CHECKS.issubset(report.get("checks", [])):
        raise RuntimeError("浏览器自检缺少发送、分块读取、停止、重连或所有权清理证据")
    if (report.get("stream_snapshot_count", 0) < 2 or report.get("same_profile_history_restored") is not True
            or report.get("cancelled_queue_sent") is not False or report.get("browser_process_restart") is not True
            or report.get("application_process_restart") is not False
            or report.get("request_count", 0) < 4 or report.get("response_count", 0) < 2):
        raise RuntimeError("浏览器流式/取消队列/同资料目录恢复自检未完成")
    return {key: report[key] for key in ("mode", "fixture", "browser_version", "chromedriver_version", "real_site_visited",
            "qt", "checks", "stream_snapshot_count", "browser_process_restart", "application_process_restart",
            "same_profile_history_restored", "cancelled_queue_sent", "request_count", "response_count")}


def safe_failure_report(stage: str, error: Exception, output: Path) -> dict:
    summary = str(error)
    for private_path in (str(output), str(ROOT), str(Path.home())):
        summary = summary.replace(private_path, "<构建目录>")
    summary = re.sub(r"(?:[A-Za-z]:[/\\]|/(?:tmp|var|private|Users|home|workspace|opt)/)[^\s\"'\n]*", "<自检目录>", summary)
    summary = summary.replace("local-fixture-not-a-secret", "<模拟凭证>")
    summary = re.sub(r"(?i)(api[_-]?key|authorization|bearer)(\s*[:=]\s*|\s+)[^\s,;]+", r"\1=<已隐藏>", summary)
    return {"schema_version": 2, "status": "failed", "stage": stage, "error_type": type(error).__name__,
            "summary": summary[:8000], "binary_distribution_approved": False,
            "verification_limit": "失败或未完成的自检；不得解释为应用已可运行，不包含原始日志或用户状态"}


def run_checks(output: Path, args, progress: dict) -> None:
    progress["stage"] = "读取冻结库存"
    inventory_path = output / "review/local-desktop-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    browser_fixture = browser_provenance = None
    if not args.api_only:
        progress["stage"] = "核验固定浏览器测试来源"
        fixture_path = (args.browser_fixture or output / "browser-test/runtime.json").resolve()
        if not fixture_path.is_file():
            raise RuntimeError("缺少官方浏览器测试夹具；先运行 local_browser_fixture.py。仅诊断 API 可显式使用 --api-only")
        browser_fixture, browser_provenance = read_browser_fixture(fixture_path)
    with tempfile.TemporaryDirectory(prefix="ai-bridge-local-smoke-") as directory:
        state = Path(directory)
        env = smoke_environment(state)
        # 详细诊断仅留构建机；工作流不上传日志，避免路径/fixture 内容扩散。
        progress["stage"] = "API首次完整运行"
        process_probe = run_application(executable_path(output), "--local-smoke-test", state, env, output / "local-smoke.log")
        report = json.loads((state / "local-smoke.json").read_text(encoding="utf-8"))
        safe = validate_report(report, inventory["runtime_build_environment"])
        progress["stage"] = "API应用重启恢复"
        resume_process_probe = run_application(executable_path(output), "--local-resume-smoke-test", state, env, output / "local-resume-smoke.log")
        resumed = json.loads((state / "local-resume-smoke.json").read_text(encoding="utf-8"))
        if (resumed.get("mode") != "local-worker" or not REQUIRED_RESUME_CHECKS.issubset(resumed.get("checks", []))
                or resumed.get("conversation_id") != report.get("selftest_conversation_id")):
            raise RuntimeError("第二个真实应用进程没有恢复同一会话")
        safe["application_restart_probe"] = {"same_conversation_restored": True, "checks": resumed["checks"]}
        safe["process_cleanup_probe"] = {"first_process": process_probe, "second_process": resume_process_probe}
        safe["host_python_node_removed_from_path"] = True
        safe["fresh_state_directory"] = True
        safe["external_model_calls"] = False
    if browser_fixture:
        with tempfile.TemporaryDirectory(prefix="ai-bridge-browser-smoke-") as directory:
            state = Path(directory)
            env = smoke_environment(state)
            env.update(AI_BRIDGE_TEST_CHROME=browser_fixture["chrome"], AI_BRIDGE_TEST_CHROMEDRIVER=browser_fixture["chromedriver"])
            progress["stage"] = "真实浏览器流程"
            process_probe = run_application(executable_path(output), "--local-browser-smoke-test", state, env,
                                            output / "local-browser-smoke.log")
            report = json.loads((state / "local-browser-smoke.json").read_text(encoding="utf-8"))
            if report.get("qt") != inventory["runtime_build_environment"]["qt"]:
                raise RuntimeError("浏览器自检的 Qt 运行时与冻结清单不一致")
            safe["browser_probe"] = validate_browser_report(report, browser_fixture)
            safe["browser_probe"]["test_runtime_sources"] = browser_provenance
            safe["browser_probe"]["process_cleanup_probe"] = process_probe
    else:
        safe["browser_probe"] = {"status": "未运行；本次显式选择了 --api-only，不能作为浏览器验收"}
    progress["stage"] = "保存脱敏验证证据"
    safe.update(schema_version=2, status="passed", binary_distribution_approved=False)
    write_json(output / "review/local-smoke.json", safe)
    inventory["frozen_runtime_probe"] = safe
    write_json(inventory_path, inventory)
    print("冻结本地 API 自检通过：真实 Worker、Qt UI、Pi、批准/拒绝/取消与会话恢复；未调用外部模型")
    print("真实 Chrome 浏览器自检通过；仅回环 fixture，未访问真实站点" if browser_fixture else "浏览器自检未运行")


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/local-desktop"))
    parser.add_argument("--browser-fixture", type=Path, help="固定官方浏览器/驱动测试夹具 runtime.json")
    parser.add_argument("--api-only", action="store_true", help="只诊断 API 路径，不能据此宣称浏览器模式通过")
    args = parser.parse_args()
    if args.api_only and args.browser_fixture:
        parser.error("--api-only 不能同时指定浏览器测试夹具")
    output = args.output.resolve()
    progress = {"stage": "初始化自检"}
    write_json(output / "review/local-smoke.json", {"schema_version": 2, "status": "running",
               "stage": progress["stage"], "binary_distribution_approved": False})
    try:
        run_checks(output, args, progress)
    except Exception as error:
        write_json(output / "review/local-smoke.json", safe_failure_report(progress["stage"], error, output))
        raise


if __name__ == "__main__":
    main()

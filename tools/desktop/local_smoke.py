"""在全新状态和无宿主 Python/Node 的 PATH 下检验冻结本地 UI、Worker 与真实 Pi 往返。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from local_build import NAME, NODE_VERSION, PI_VERSION, write_json

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


def run_application(executable: Path, argument: str, state: Path, env: dict, log_path: Path) -> dict:
    import psutil
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(executable), argument], cwd=state, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, **kwargs)
        observed = {}
        saw_node = False
        try:
            deadline = time.monotonic() + 300
            while process.poll() is None:
                try:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        observed[child.pid] = child.create_time()
                        saw_node = saw_node or child.name().lower() in {"node", "node.exe"}
                except psutil.NoSuchProcess:
                    pass
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(str(executable), 300)
                time.sleep(0.05)
            code = process.wait()
            if code:
                raise RuntimeError(f"冻结本地冒烟失败（退出码 {code}）；请检查构建机 {log_path.name}")
            shutdown_deadline = time.monotonic() + 10
            while surviving_children(observed) and time.monotonic() < shutdown_deadline:
                time.sleep(0.1)
            if surviving_children(observed):
                raise RuntimeError("主窗口退出后仍有观察到的子进程存活；已停止自检并清理本次进程树")
            if argument == "--local-smoke-test" and not saw_node:
                raise RuntimeError("未观察到实际 Node 子进程，不能证明冻结 Pi 的进程退出")
            return {"observed_descendant_count": len(observed), "observed_node": saw_node,
                    "all_observed_descendants_exited": True}
        finally:
            terminate_tree(process, observed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/local-desktop"))
    args = parser.parse_args()
    output = args.output.resolve()
    inventory_path = output / "review/local-desktop-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="ai-bridge-local-smoke-") as directory:
        state = Path(directory)
        env = smoke_environment(state)
        # 详细诊断仅留构建机；工作流不上传日志，避免路径/fixture 内容扩散。
        process_probe = run_application(executable_path(output), "--local-smoke-test", state, env, output / "local-smoke.log")
        report = json.loads((state / "local-smoke.json").read_text(encoding="utf-8"))
        safe = validate_report(report, inventory["runtime_build_environment"])
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
        write_json(output / "review/local-smoke.json", safe)
        inventory["frozen_runtime_probe"] = safe
        write_json(inventory_path, inventory)
    print("冻结完整本地客户端自检通过：真实 Worker、Qt UI、Pi、批准/拒绝/取消与会话恢复；未调用外部模型")


if __name__ == "__main__":
    main()

# filename: app/core/worker_modules/worker_code_workspace.py
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

from app.core.logging import get_logger
from app.core.project_context import ProjectContext
from app.core.project_paths import project_config_path
from app.core.python_runtime import resolve_project_python, python_subprocess_environment

logger = get_logger("app.core.worker.code_workspace", side="worker")


class WorkerCodeWorkspaceBridge:
    """Code workspace actions for staging, sync, snapshots, and ignored blocks."""

    def __init__(self, worker):
        self.worker = worker

    def ignore_block_content(self, filename, content, client_id="Host", **kwargs):
        threading.Thread(target=self.do_ignore_block, args=(filename, content)).start()

    def do_ignore_block(self, filename, content):
        ok, msg = self.worker.file_service.add_ignored_content(filename, content)
        self.worker.safe_emit_status(f"🗑️ {msg}")

    def unignore_block_content(self, filename, content, client_id="Host", **kwargs):
        threading.Thread(target=self.do_unignore_block, args=(filename, content)).start()

    def do_unignore_block(self, filename, content):
        worker = self.worker
        if hasattr(worker.file_service, "remove_ignored_content"):
            ok, msg = worker.file_service.remove_ignored_content(content)
            worker.safe_emit_status(f"♻️ {msg}")

            if ok:
                worker.safe_emit_status("🔄 正在回溯并重新扫描代码...")
                try:
                    worker.process_batch(worker.last_messages_snapshot)
                    self.do_server_scan()
                except Exception as exc:
                    worker.safe_emit_status(f"⚠️ 回溯扫描失败: {exc}")
        else:
            worker.safe_emit_status("❌ FileService 不支持撤销操作")

    def get_staging_file_content(self, rel_path, client_id="Host", **kwargs):
        worker = self.worker
        staging_dir = project_config_path(worker.config, "export_code_path", "export/code")
        new_path = os.path.join(staging_dir, rel_path)
        new_content = "File not found"
        try:
            if os.path.exists(new_path):
                with open(new_path, "r", encoding="utf-8") as handle:
                    new_content = handle.read()
        except Exception as exc:
            new_content = f"Error reading staging: {exc}"

        project_root = ProjectContext.get().get_project_root()
        old_path = os.path.join(project_root, rel_path)
        old_content = None
        try:
            if os.path.exists(old_path):
                with open(old_path, "r", encoding="utf-8") as handle:
                    old_content = handle.read()
        except Exception as exc:
            logger.warning("读取旧文件内容失败: %s", exc)

        worker.file_preview_signal.emit(
            {
                "target_client_id": client_id,
                "rel_path": rel_path,
                "content": new_content,
                "old_content": old_content,
            }
        )

    def handle_sync_request(self, client_id="Host", **kwargs):
        worker = self.worker
        worker.safe_emit_status(f"🔄 [Sync] {client_id} 请求同步...")
        sync_data = worker.update_service.pack_client_code()
        worker.ota_sync_signal.emit(sync_data)

    def do_server_scan(self, **kwargs):
        worker = self.worker
        if not worker.rpc_lock.tryLock():
            return
        try:
            changes = worker.update_service.scan()
            worker.update_list_signal.emit(changes)
        finally:
            worker.rpc_lock.unlock()

    def do_server_apply(self, paths, **kwargs):
        worker = self.worker
        if not worker.rpc_lock.tryLock():
            return
        try:
            worker.update_service.process_updates(
                paths,
                worker.safe_emit_status,
                worker.ota_sync_signal.emit,
            )
        finally:
            worker.rpc_lock.unlock()

    def request_generate_snapshot(self, *args, **kwargs):
        worker = self.worker
        worker.safe_emit_status("⏳ 正在生成项目快照...")
        try:
            root = ProjectContext.get().get_project_root()
            script = os.path.join(root, "dump_code.py")
            if not os.path.isfile(script):
                worker.safe_emit_status("❌ 当前项目没有 dump_code.py，无法生成项目快照。")
                return
            python = resolve_project_python(
                root, worker.config.get("sandbox_local_python", ""), purpose="生成项目快照"
            )
            result = subprocess.run(
                [python, script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                cwd=root,
                env=python_subprocess_environment(),
                timeout=120,
            )
            if result.returncode == 0:
                snapshot_path = os.path.join(root, "FULL_PROJECT_CONTEXT.txt")
                if os.path.exists(snapshot_path):
                    with open(snapshot_path, "r", encoding="utf-8") as handle:
                        content = handle.read()
                    worker.snapshot_ready_signal.emit(content)
                    worker.safe_emit_status("✅ 快照生成完毕")
                else:
                    worker.safe_emit_status("❌ 错误: 未找到快照文件")
            else:
                worker.safe_emit_status(f"❌ 生成失败: {result.stderr}")
        except Exception as exc:
            worker.safe_emit_status(f"❌ 执行异常: {exc}")

    def do_server_clear_cache(self, **kwargs):
        worker = self.worker
        staging_dir = project_config_path(worker.config, "export_code_path", "export/code")
        if not os.path.exists(staging_dir):
            worker.safe_emit_status("⚠️ 服务端暂存区已为空")
            return

        try:
            count = 0
            for filename in os.listdir(staging_dir):
                file_path = os.path.join(staging_dir, filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                    count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    count += 1

            worker.safe_emit_status(f"🗑️ 服务端暂存区已清空 ({count} items)")
            self.do_server_scan()
        except Exception as exc:
            worker.safe_emit_status(f"❌ 服务端清空失败: {exc}")

    def manual_save(self, filename, content, **kwargs):
        self.worker.file_service.save_code(filename, content)

    def touch_file(self, path, **kwargs):
        if os.path.exists(path):
            os.utime(path, None)

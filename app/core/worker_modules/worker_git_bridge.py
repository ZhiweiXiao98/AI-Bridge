from app.core.config import ConfigManager
from app.core.git_manager import GitManager
from app.core.logging import get_logger

logger = get_logger("app.core.worker_modules.worker_git_bridge", side="worker")


class WorkerGitBridge:
    """Git workbench/backup bridge for WorkerThread.

    WorkerThread keeps the RPC surface and signals; this bridge owns the Git
    manager calls plus the optional knowledge reindex that follows push/backup.
    """

    def __init__(self, worker):
        self.worker = worker

    @staticmethod
    def _target_group(user_role):
        return "admin" if user_role == "developer" else "user"

    def get_workbench_state(self, limit=30, client_id="Host", user_role=None):
        payload = GitManager().get_workbench_state(limit=limit)
        payload["target_client_id"] = client_id
        payload["target_group"] = self._target_group(user_role)
        try:
            self.worker.git_workbench_signal.emit(payload)
        except Exception as exc:
            logger.warning(exc)
        return payload

    def get_file_diff(self, path, kind=None, client_id="Host", user_role=None):
        payload = GitManager().get_file_diff_content(path, kind=kind)
        payload["target_client_id"] = client_id
        payload["target_group"] = self._target_group(user_role)
        try:
            self.worker.git_diff_preview_signal.emit(payload)
        except Exception as exc:
            logger.warning(exc)
        return payload

    def get_config_snapshot(self, client_id="Host", user_role=None):
        payload = GitManager().get_git_config_snapshot()
        payload["target_client_id"] = client_id
        payload["target_group"] = self._target_group(user_role)
        try:
            self.worker.git_config_signal.emit(payload)
        except Exception as exc:
            logger.warning(exc)
        return payload

    def emit_status(self, detail_text, status_text=None):
        if status_text:
            self.worker.safe_emit_status(status_text)
        try:
            self.worker.git_detail_signal.emit(detail_text)
        except Exception as exc:
            logger.warning(exc)

    def emit_log_lines(self, log):
        if not log:
            return
        for line in str(log).splitlines():
            if line.strip():
                try:
                    self.worker.git_detail_signal.emit(f"[GitLog] {line}")
                except Exception as exc:
                    logger.warning(exc)

    def execute_action(
        self,
        git_func,
        start_msg,
        start_detail,
        success_msg,
        fail_msg,
        post_actions=None,
    ):
        self.emit_status(start_detail, start_msg)
        result = git_func(GitManager())
        if isinstance(result, tuple) and len(result) == 2:
            ok, log = result
            extra = None
        elif isinstance(result, tuple) and len(result) == 3:
            ok, log, extra = result
        else:
            ok = result[0]
            log = result[1] if len(result) > 1 else None
            extra = None

        self.emit_log_lines(log)
        if ok:
            self.emit_status(f"[Git] {success_msg}", f"[Git] {success_msg}")
        else:
            self.emit_status(f"[Git] {fail_msg}", f"[Git] {fail_msg}")

        for action in post_actions or []:
            try:
                action()
            except Exception as exc:
                logger.warning(exc)

        if isinstance(result, tuple) and len(result) == 3:
            return ok, log, extra
        return ok

    def init_repo(self, client_id="Host", user_role=None):
        return self.execute_action(
            git_func=lambda gm: gm.init_repo(),
            start_msg="[Git] Starting repository initialization...",
            start_detail="[Git] Repository initialization requested",
            success_msg="Repository initialized",
            fail_msg="Repository initialization failed",
            post_actions=[lambda: self.get_config_snapshot(client_id=client_id, user_role=user_role)],
        )

    def set_user(self, name, email, client_id="Host", user_role=None):
        return self.execute_action(
            git_func=lambda gm: gm.set_user_config(name, email),
            start_msg="[Git] Saving Git identity...",
            start_detail="[Git] Git identity update requested",
            success_msg="Git identity saved",
            fail_msg="Git identity save failed",
            post_actions=[lambda: self.get_config_snapshot(client_id=client_id, user_role=user_role)],
        )

    def set_remote(self, name, url, client_id="Host", user_role=None):
        return self.execute_action(
            git_func=lambda gm: gm.set_remote(name, url),
            start_msg="[Git] Updating remote...",
            start_detail="[Git] Remote configuration requested",
            success_msg="Remote updated",
            fail_msg="Remote update failed",
            post_actions=[
                lambda: self.get_config_snapshot(client_id=client_id, user_role=user_role),
                lambda: self.run_connectivity_checks(client_id=client_id, user_role=user_role),
            ],
        )

    def set_upstream(self, client_id="Host", user_role=None):
        return self.execute_action(
            git_func=lambda gm: gm.set_upstream_to_origin_current_branch(),
            start_msg="[Git] Binding upstream branch...",
            start_detail="[Git] Upstream binding requested",
            success_msg="Upstream branch bound",
            fail_msg="Upstream binding failed",
            post_actions=[
                lambda: self.get_config_snapshot(client_id=client_id, user_role=user_role),
                lambda: self.run_connectivity_checks(client_id=client_id, user_role=user_role),
            ],
        )

    def run_connectivity_checks(self, client_id="Host", user_role=None):
        payload = GitManager().run_connectivity_checks()
        payload["target_client_id"] = client_id
        payload["target_group"] = self._target_group(user_role)
        try:
            self.worker.git_config_signal.emit(payload)
        except Exception as exc:
            logger.warning(exc)
        return payload

    def push_only(self):
        self.emit_status("[Git] Push requested", "[Git] Pushing...")
        ok, log = GitManager().push_only()
        self.emit_log_lines(log)
        if ok:
            self.emit_status("[Git] Push succeeded", "[Git] Push succeeded")
            self._maybe_reindex_after_git_push(None)
        else:
            self.emit_status("[Git] Push failed", "[Git] Push failed")
        return ok

    def backup(self, msg):
        self.emit_status(f"[Git] Backup requested: {msg}", "[Git] Creating backup...")
        ok, log, changed_files = GitManager().backup(msg)
        self.emit_log_lines(log)
        if ok:
            self.emit_status("[Git] Backup succeeded", "[Git] Backup succeeded")
            self._maybe_reindex_after_git_push(changed_files or [])
        else:
            self.emit_status("[Git] Backup failed", "[Git] Backup failed")
        return ok

    def _maybe_reindex_after_git_push(self, changed_files):
        config = ConfigManager.load()
        if not config.get("knowledge_reindex_after_git_push", True):
            self.emit_status(
                "[Knowledge] Skipped: reindex after Git push is disabled",
                "[Knowledge] Skipped: reindex after Git push is disabled",
            )
            return

        file_count = len(changed_files or [])
        if file_count:
            self.emit_status(
                f"[Knowledge] Queued incremental reindex for {file_count} changed files",
                "[Knowledge] Queued incremental reindex...",
            )
        else:
            self.emit_status(
                "[Knowledge] No changed-file list available; queued project reindex",
                "[Knowledge] Queued project reindex...",
            )
        self.worker.executor.submit(self.run_knowledge_reindex_after_git_push, changed_files)

    def run_knowledge_reindex_after_git_push(self, changed_files=None):
        normalized = [str(item).strip() for item in (changed_files or []) if str(item).strip()]
        use_incremental = bool(normalized)
        if use_incremental:
            start_text = f"[Knowledge] Starting incremental reindex ({len(normalized)} files)..."
        else:
            start_text = "[Knowledge] Starting project reindex..."
        self.worker.safe_emit_status(start_text)
        self.emit_status(start_text)

        try:
            if use_incremental:
                from app.core.knowledge.reindex_runner import reindex_changed_files

                summary = reindex_changed_files(
                    normalized,
                    ".",
                    progress_callback=self.on_knowledge_reindex_progress,
                )
                success_text = (
                    "[Knowledge] Incremental reindex completed: "
                    f"ok={summary['ok']} fail={summary['fail']} skip={summary['skip']} "
                    f"deleted={summary['deleted']} keep={summary['keep']}"
                )
            else:
                from app.core.knowledge.reindex_runner import reindex_project

                summary = reindex_project(".", progress_callback=self.on_knowledge_reindex_progress)
                success_text = (
                    "[Knowledge] Project reindex completed: "
                    f"ok={summary['ok']} fail={summary['fail']} skip={summary['skip']} "
                    f"deleted={summary['deleted']} keep={summary['keep']}"
                )

            if summary.get("enabled", True):
                self.worker.safe_emit_status(success_text)
                self.emit_status(success_text)
            else:
                skipped = "[Knowledge] Skipped: rule filter is disabled"
                self.worker.safe_emit_status(skipped)
                self.emit_status(skipped)
        except Exception as exc:
            err_text = f"[Knowledge] Reindex failed: {exc}"
            self.worker.safe_emit_status(err_text)
            self.emit_status(err_text)

    def on_knowledge_reindex_progress(self, info):
        info = dict(info or {})
        stage = info.get("stage")
        summary_text = None
        detail_text = None

        if stage == "disabled":
            summary_text = "[Knowledge] Skipped: rule filter is disabled"
            detail_text = summary_text
        elif stage == "prepare":
            summary_text = "[Knowledge] Preparing scan..."
            detail_text = summary_text
        elif stage == "scan_start":
            summary_text = "[Knowledge] Scanning project files..."
            detail_text = summary_text
        elif stage == "scan_done":
            detail_text = f"[Knowledge] Scan completed, candidates={info.get('total', 0)}"
        elif stage == "delete_start":
            detail_text = f"[Knowledge] Cleaning stale indexes, total={info.get('total', 0)}"
        elif stage == "delete_done":
            detail_text = f"[Knowledge] Stale index cleanup completed, deleted={info.get('deleted', 0)}"
        elif stage == "index_start":
            summary_text = f"[Knowledge] Writing index, total={info.get('total', 0)}"
            detail_text = summary_text
        elif stage == "index_progress":
            detail_text = (
                f"[Knowledge] Index progress {info.get('current', 0)}/{info.get('total', 0)} "
                f"[{info.get('status', 'ok')}] {info.get('file', '')}"
            )

        if summary_text:
            self.worker.safe_emit_status(summary_text)
        if detail_text:
            self.emit_status(detail_text)

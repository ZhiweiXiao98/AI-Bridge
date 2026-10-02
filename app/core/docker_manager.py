# filename: app/core/docker_manager.py
import docker
import os
import sys
import time
import subprocess
import logging
from app.core.project_context import ProjectContext
import uuid
import threading
from contextlib import contextmanager
from docker.errors import ContainerError, ImageNotFound, APIError, NotFound
from app.core.code_validator import CodeValidator
from app.core.execution_history import ExecutionHistory, ExecutionRecord
from app.core.logging import get_logger

logger = get_logger("app.core.docker_manager", side="worker")

# 执行模式常量
EXEC_MODE_DOCKER = "docker"
EXEC_MODE_LOCAL = "local"

class ExecutionTimeout(Exception):
    """代码执行超时异常"""
    pass

@contextmanager
def temp_code_file(code: str, directory=None):
    """临时代码文件上下文管理器，确保清理"""
    temp_filename = f".sandbox_exec_{uuid.uuid4().hex[:8]}.py"
    if directory is not None:
        temp_filename = os.path.join(directory, temp_filename)
    try:
        with open(temp_filename, "w", encoding="utf-8") as f:
            f.write(code)
        yield temp_filename
    finally:
        try:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
        except Exception as e:
            logger.warning(f"⚠️ 清理临时文件失败: {e}")

class DockerManager:
    CONTAINER_NAME = "ai_bridge_sandbox"

    def __init__(self, image=None):
        self.image = image or os.getenv("DOCKER_SANDBOX_IMAGE", "ai-bridge-sandbox:latest")
        self.client = None
        self.available = False
        self._container = None
        self._execution_lock = threading.Lock()
        self._initialization_lock = threading.Lock()
        self._local_desktop = os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1"
        self._instance_id = uuid.uuid4().hex
        self._container_name = (f"ai_bridge_local_{self._instance_id[:12]}"
                                if self._local_desktop else self.CONTAINER_NAME)
        self._owns_container = False
        self._cleanup_thread = None
        self._closed = False
        self.initialization_error = ""
        self.history = ExecutionHistory()
        self.project_root = ProjectContext.get().get_project_root()
        # 从配置读取执行模式，默认 docker
        from app.core.config import ConfigManager
        cfg = ConfigManager.load()
        self.exec_mode = cfg.get("sandbox_exec_mode", EXEC_MODE_DOCKER)
        self.local_python = cfg.get("sandbox_local_python", "")  # 空串 = 使用系统默认
        if not self._local_desktop:
            self._init_docker()

    @property
    def container(self):
        """
        Expose the internal container object safely.
        Fixes AttributeError in tests that access .container
        """
        return self._container

    def _init_docker(self):
        if self._closed:
            return
        try:
            self.client = docker.from_env(timeout=5) if self._local_desktop else docker.from_env()
            self.client.ping()
            logger.info(f"🐳 Docker Connected. Image: {self.image}")

            # 1. 确保镜像存在
            try:
                self.client.images.get(self.image)
            except ImageNotFound:
                if self._local_desktop:
                    self.initialization_error = (
                        f"缺少 Docker 沙盒镜像 {self.image}。请先在 Docker 中手动构建或获取此镜像后重试；"
                        "客户端不会自动下载镜像，也不会切换为宿主机执行。"
                    )
                    self.available = False
                    return
                logger.info(f"⏳ Pulling image {self.image}...")
                self.client.images.pull(self.image)

            # 2. 启动或获取长驻容器
            self._ensure_container_running()
            self.available = True
            self.initialization_error = ""

        except Exception as e:
            logger.warning(f"❌ Docker not available: {e}")
            self.available = False
            self.initialization_error = (
                "Docker 沙盒不可用，请安装并启动 Docker，准备沙盒镜像后重试。"
                "不会自动切换为宿主机执行。"
            )

    def _ensure_container_running(self):
        """确保有一个长驻容器在运行"""
        if self._closed:
            raise RuntimeError("Docker 管理器正在关闭")
        try:
            # 尝试获取现有容器
            self._container = self.client.containers.get(self._container_name)
            if self._local_desktop:
                labels = self._container.labels or {}
                if (labels.get("ai-bridge.local-instance") != self._instance_id
                        or labels.get("ai-bridge.project-root") != self.project_root):
                    self._container = None
                    raise RuntimeError("拒绝使用不属于此本地客户端和项目的 Docker 容器")
                self._owns_container = True
            if self._container.status != 'running':
                logger.info("🔄 Restarting stopped sandbox container...")
                self._container.start()
        except NotFound:
            # 创建新容器
            logger.info("🆕 Creating new persistent sandbox container...")
            host_path = self.project_root
            volumes = {host_path: {'bind': '/workspace', 'mode': 'rw'}}

            # SDK containers.run() implicitly pulls a missing image. Desktop
            # mode must use create()+start() to keep downloads user-controlled.
            create = self.client.containers.create if self._local_desktop else self.client.containers.run
            self._container = create(
                self.image,
                name=self._container_name,
                command="tail -f /dev/null",  # 让容器保持运行
                volumes=volumes,
                working_dir="/workspace",
                detach=True,
                mem_limit="1g",
                network_mode="bridge" if self._local_desktop else "host",
                restart_policy={"Name": "no" if self._local_desktop else "always"},
                **({"labels": {"ai-bridge.local-instance": self._instance_id,
                               "ai-bridge.project-root": self.project_root}} if self._local_desktop else {})
            )
            self._owns_container = self._local_desktop
            if self._local_desktop:
                self._container.start()
            logger.info(f"✅ Sandbox Container Started: {self._container.short_id}")

    def force_cleanup(self):
        if not self._container:
            return
        if self._local_desktop and not self._owns_container:
            return
        try:
            self._container.stop(timeout=3)
            self._container.remove(force=True)
            logger.info("[Docker] 容器已强制清理")
        except Exception as e:
            logger.warning(f"[Docker] 容器清理异常: {e}")
        finally:
            self._container = None
            self._owns_container = False

    def shutdown(self, timeout=3.0):
        """Clean only this desktop instance's container; preserve server containers."""
        if not self._local_desktop:
            return True
        self._closed = True
        if self._cleanup_thread is None:
            def cleanup():
                with self._initialization_lock:
                    self.force_cleanup()
                    if self.client is not None:
                        self.client.close()
            self._cleanup_thread = threading.Thread(target=cleanup, daemon=True, name="docker-local-cleanup")
            self._cleanup_thread.start()
        if self._cleanup_thread is not threading.current_thread():
            self._cleanup_thread.join(timeout=max(0.0, timeout))
        return not self._cleanup_thread.is_alive()

    def on_about_to_switch(self, new_root: str, new_db_path: str):
        logger.info("[Docker] 项目切换前清理容器")
        self.force_cleanup()

    def on_project_switched(self, new_root: str, new_db_path: str):
        self.project_root = new_root
        logger.info(f"[Docker] 项目路径已更新: {new_root}")

    def set_exec_mode(self, mode: str, local_python: str = ""):
        """切换执行模式并持久化到 config.json。

        Args:
            mode: EXEC_MODE_DOCKER 或 EXEC_MODE_LOCAL
            local_python: 本地模式下使用的 Python 解释器路径，空串表示系统默认
        """
        self.exec_mode = mode
        self.local_python = local_python
        try:
            from app.core.config import ConfigManager
            cfg = ConfigManager.load()
            cfg["sandbox_exec_mode"] = mode
            cfg["sandbox_local_python"] = local_python
            ConfigManager.save(cfg)
            logger.info(f"[沙盒] 执行模式已切换并保存: mode={mode}, python={local_python or '系统默认'}")
        except Exception as e:
            logger.warning(f"[沙盒] 执行模式保存失败: {e}")

    def _execute_local(self, code: str, timeout: int) -> tuple[int, str]:
        """在本地进程中执行代码（无容器隔离）。

        使用 self.local_python 指定的解释器，空串则取 sys.executable。
        工作目录设为 project_root，保持与 Docker 模式一致。
        """
        from app.core.python_runtime import resolve_project_python, PythonRuntimeUnavailable, python_subprocess_environment
        try:
            python_bin = resolve_project_python(self.project_root, self.local_python, purpose="本地 Python 沙盒")
        except PythonRuntimeUnavailable as error:
            return 1, str(error)
        with temp_code_file(code, directory=self.project_root if self._local_desktop else None) as temp_filename:
            abs_path = os.path.abspath(temp_filename)
            logger.info(f"💻 本地执行: {python_bin} {abs_path}")
            try:
                result = subprocess.run(
                    [python_bin, abs_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.project_root,
                    env=python_subprocess_environment(),
                )
                output = result.stdout
                if result.stderr:
                    output += result.stderr
                return result.returncode, output
            except subprocess.TimeoutExpired:
                logger.warning(f"⏱️ 本地执行超时 ({timeout}s)")
                return 1, f"❌ 执行超时 ({timeout}s)\n提示：代码可能包含无限循环或长时间阻塞操作"
            except FileNotFoundError:
                msg = f"❌ 找不到 Python 解释器: {python_bin}"
                logger.error(msg)
                return 1, msg
            except Exception as e:
                msg = f"本地执行异常: {e}"
                logger.error(msg)
                return 1, msg

    def execute_code(self, code: str, timeout: int = 60, skip_validation: bool = False) -> tuple[int, str]:
        """
        执行代码：根据 exec_mode 走 Docker 沙盒或本地进程。

        Args:
            code: 要执行的 Python 代码
            timeout: 超时时间（秒），默认 60 秒
            skip_validation: 是否跳过代码验证（默认 False）

        Returns:
            (exit_code, output) 元组
        """
        if self._closed:
            return -1, "客户端正在关闭，无法执行新的代码"
        # 本地模式：跳过 Docker，直接走 subprocess
        if self.exec_mode == EXEC_MODE_LOCAL:
            if not skip_validation:
                is_safe, warnings, errors = CodeValidator.validate(code)
                if not is_safe:
                    error_msg = CodeValidator.format_validation_result(warnings, errors)
                    logger.warning(f"代码验证失败:\n{error_msg}")
                    return 1, f"❌ 代码验证失败\n\n{error_msg}\n\n提示：代码包含不安全的操作，已阻止执行"
            return self._execute_local(code, timeout)

        # Docker 模式
        if self._local_desktop and not self.available:
            with self._initialization_lock:
                if not self.available:
                    self._init_docker()
        if not self.available:
            return -1, self.initialization_error or "Docker environment not available"

        # 🆕 代码静态检查
        if not skip_validation:
            is_safe, warnings, errors = CodeValidator.validate(code)

            if not is_safe:
                error_msg = CodeValidator.format_validation_result(warnings, errors)
                logger.warning(f"代码验证失败:\n{error_msg}")
                return 1, f"❌ 代码验证失败\n\n{error_msg}\n\n提示：代码包含不安全的操作，已阻止执行"

            if warnings:
                warning_msg = CodeValidator.format_validation_result(warnings, [])
                logger.info(f"代码验证警告:\n{warning_msg}")
                # 警告不阻止执行，但会记录

        # 🆕 并发控制：同一时间只允许一个代码块执行
        start_time = time.time()
        with self._execution_lock:
            try:
                # 确保容器活着
                if not self._container:
                    self._ensure_container_running()

                self._container.reload()
                if self._container.status != 'running':
                    self._container.start()

                # 🆕 使用上下文管理器管理临时文件
                with temp_code_file(code, directory=self.project_root if self._local_desktop else None) as temp_filename:
                    logger.info(f"🚀 Executing inside container: {temp_filename}")

                    # 🆕 使用线程 + 超时控制
                    result = {'exit_code': None, 'output': None, 'error': None}

                    def execute_in_thread():
                        try:
                            cmd = ["python", os.path.basename(temp_filename)]
                            exec_result = self._container.exec_run(
                                cmd,
                                workdir="/workspace",
                                demux=True
                            )

                            result['exit_code'] = exec_result.exit_code
                            stdout = exec_result.output[0] if exec_result.output and exec_result.output[0] else b""
                            stderr = exec_result.output[1] if exec_result.output and exec_result.output[1] else b""
                            result['output'] = stdout.decode('utf-8', errors='replace') + stderr.decode('utf-8', errors='replace')
                        except Exception as e:
                            result['error'] = str(e)

                    exec_thread = threading.Thread(target=execute_in_thread, daemon=True)
                    exec_thread.start()
                    exec_thread.join(timeout=timeout)

                    # 检查是否超时
                    if exec_thread.is_alive():
                        logger.warning(f"⏱️ 代码执行超时 ({timeout}s)")
                        # 🔧 异步重启容器，不阻塞返回
                        def restart_container_async():
                            try:
                                logger.info("🔄 正在重启容器...")
                                self._container.restart()
                                logger.info("✅ 容器已重启")
                            except Exception as e:
                                logger.error(f"❌ 容器重启失败: {e}")

                        restart_thread = threading.Thread(target=restart_container_async, daemon=True)
                        restart_thread.start()

                        return 1, f"❌ 执行超时 ({timeout}s)\n提示：代码可能包含无限循环或长时间阻塞操作"

                    # 检查执行结果
                    if result['error']:
                        exit_code, output = 1, f"Sandbox Error: {result['error']}"
                    else:
                        exit_code, output = result['exit_code'], result['output']

                    # 🆕 记录执行历史
                    duration = time.time() - start_time
                    record = ExecutionRecord(
                        timestamp=start_time,
                        code=code,
                        exit_code=exit_code,
                        output=output,
                        duration=duration,
                        validation_warnings=warnings if not skip_validation else [],
                        validation_errors=errors if not skip_validation else [],
                        timeout=timeout
                    )
                    self.history.add_record(record)

                    return exit_code, output

            except Exception as e:
                msg = f"Sandbox Error: {str(e)}"
                logger.error(msg)
                # 如果容器挂了，尝试重启一次
                try:
                    if self._container:
                        self._container.restart()
                except Exception as e:
                    logger.warning(f"容器重启失败: {e}")
                return 1, msg

    def get_execution_history(self, count: int = 10):
        """获取最近的执行历史"""
        return self.history.get_recent(count)

    def get_execution_statistics(self):
        """获取执行统计信息"""
        return self.history.get_statistics()

    def clear_execution_history(self):
        """清空执行历史"""
        self.history.clear()

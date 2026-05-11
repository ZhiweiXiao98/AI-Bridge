# filename: app/core/docker_manager.py
import docker
import os
import time
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

class ExecutionTimeout(Exception):
    """代码执行超时异常"""
    pass

@contextmanager
def temp_code_file(code: str):
    """临时代码文件上下文管理器，确保清理"""
    temp_filename = f".sandbox_exec_{uuid.uuid4().hex[:8]}.py"
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
        self.history = ExecutionHistory()
        self.project_root = ProjectContext.get().get_project_root()
        self._init_docker()

    @property
    def container(self):
        """
        Expose the internal container object safely.
        Fixes AttributeError in tests that access .container
        """
        return self._container

    def _init_docker(self):
        try:
            self.client = docker.from_env()
            self.client.ping()
            self.available = True
            logger.info(f"🐳 Docker Connected. Image: {self.image}")
            
            # 1. 确保镜像存在
            try:
                self.client.images.get(self.image)
            except ImageNotFound:
                logger.info(f"⏳ Pulling image {self.image}...")
                self.client.images.pull(self.image)
                
            # 2. 启动或获取长驻容器
            self._ensure_container_running()
            
        except Exception as e:
            logger.warning(f"❌ Docker not available: {e}")
            self.available = False

    def _ensure_container_running(self):
        """确保有一个长驻容器在运行"""
        try:
            # 尝试获取现有容器
            self._container = self.client.containers.get(self.CONTAINER_NAME)
            if self._container.status != 'running':
                logger.info("🔄 Restarting stopped sandbox container...")
                self._container.start()
        except NotFound:
            # 创建新容器
            logger.info("🆕 Creating new persistent sandbox container...")
            host_path = self.project_root
            volumes = {host_path: {'bind': '/workspace', 'mode': 'rw'}}
            
            self._container = self.client.containers.run(
                self.image,
                name=self.CONTAINER_NAME,
                command="tail -f /dev/null",  # 让容器保持运行
                volumes=volumes,
                working_dir="/workspace",
                detach=True,
                mem_limit="1g",
                network_mode="host",  # TODO: 改为 bridge 模式提高安全性
                restart_policy={"Name": "always"}
            )
            logger.info(f"✅ Sandbox Container Started: {self._container.short_id}")

    def force_cleanup(self):
        if not self._container:
            return
        try:
            self._container.stop(timeout=3)
            self._container.remove(force=True)
            logger.info("[Docker] 容器已强制清理")
        except Exception as e:
            logger.warning(f"[Docker] 容器清理异常: {e}")
        finally:
            self._container = None

    def on_about_to_switch(self, new_root: str, new_db_path: str):
        logger.info("[Docker] 项目切换前清理容器")
        self.force_cleanup()

    def on_project_switched(self, new_root: str, new_db_path: str):
        self.project_root = new_root
        logger.info(f"[Docker] 项目路径已更新: {new_root}")

    def execute_code(self, code: str, timeout: int = 60, skip_validation: bool = False) -> tuple[int, str]:
        """
        在沙盒中执行代码
        
        Args:
            code: 要执行的 Python 代码
            timeout: 超时时间（秒），默认 60 秒
            skip_validation: 是否跳过代码验证（默认 False）
            
        Returns:
            (exit_code, output) 元组
        """
        if not self.available:
            return -1, "Docker environment not available"
        
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
                with temp_code_file(code) as temp_filename:
                    logger.info(f"🚀 Executing inside container: {temp_filename}")
                    
                    # 🆕 使用线程 + 超时控制
                    result = {'exit_code': None, 'output': None, 'error': None}
                    
                    def execute_in_thread():
                        try:
                            cmd = ["python", temp_filename]
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

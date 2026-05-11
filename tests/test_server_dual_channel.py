# filename: tests/test_server_dual_channel.py
import pytest
import sys
from unittest.mock import MagicMock, patch

# [Fix] 优雅处理 httpx 缺失的情况
# FastAPI TestClient 强依赖 httpx，如果没有安装，导入时会抛出 RuntimeError
try:
    from fastapi.testclient import TestClient
    from server import app, auth
    HAS_DEPS = True
except (ImportError, RuntimeError):
    HAS_DEPS = False

@pytest.mark.skipif(not HAS_DEPS, reason="缺少 httpx 库，无法运行 FastAPI 测试客户端")
class TestServerDualChannel:
    
    # 只有当依赖存在时才初始化 Client，防止类定义阶段报错
    client = TestClient(app) if HAS_DEPS else None

    # Mock 鉴权，绕过真实数据库
    def mock_verify_admin(self):
        return {"sub": "admin", "role": "developer"}

    def setup_method(self):
        if not HAS_DEPS: return
        
        # 覆盖依赖，模拟已登录管理员
        from server import verify_admin
        app.dependency_overrides[verify_admin] = self.mock_verify_admin
        # 覆盖密码验证
        app.dependency_overrides[auth.verify_password] = lambda u, p: True

    def teardown_method(self):
        if not HAS_DEPS: return
        app.dependency_overrides = {}

    def test_sync_messages_endpoint(self):
        """测试消息拉取接口"""
        # 模拟服务端内存数据
        import server
        server.LATEST_MESSAGES_DATA = [{"id": 1, "text": "Hello"}]
        
        response = self.client.get("/api/sync/messages")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data[0]["text"] == "Hello"

    def test_sync_code_endpoint(self):
        """测试代码同步接口"""
        import server
        server.LATEST_SYNC_DATA = {"file1.py": "print('code')"}
        
        response = self.client.get("/api/sync/code")
        
        assert response.status_code == 200
        data = response.json()
        assert "file1.py" in data
        assert data["file1.py"] == "print('code')"

    def test_upload_endpoint(self):
        """测试文件上传接口 (HTTP通道的一部分)"""
        # 模拟文件上传
        files = {'file': ('test.txt', b'test content', 'text/plain')}
        
        # Mock os.makedirs 和 open 防止写真实磁盘
        with patch("os.makedirs"), patch("builtins.open", MagicMock()), patch("shutil.copyfileobj"):
            response = self.client.post("/api/upload", files=files)
            
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            assert "path" in response.json()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
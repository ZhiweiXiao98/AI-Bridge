# Docker 测试环境使用指南

## 📁 目录结构

app/core/sandbox/
├── Dockerfile.test              # 测试环境
├── Dockerfile.ui                # UI 测试环境
├── docker-compose.test.yml      # Docker Compose 配置
└── README.md                    # 本文件

## 🚀 快速开始

### 1. 运行所有测试（不含 UI）

cd app/core/sandbox
docker-compose -f docker-compose.test.yml up test

### 2. 运行 UI 测试

cd app/core/sandbox
docker-compose -f docker-compose.test.yml up ui-test

### 3. 启动客户端供 AI 测试

cd app/core/sandbox
docker-compose -f docker-compose.test.yml up client

然后使用 VNC 客户端连接 localhost:5900 查看界面。

## 🐳 Docker 环境说明

### 测试环境 (Dockerfile.test)

- 基础镜像: python:3.10-slim
- 包含 Docker CLI（通过挂载宿主机套接字）
- 包含 pytest, pytest-cov, pytest-mock
- 用途: 运行单元测试和集成测试

### UI 测试环境 (Dockerfile.ui)

- 基础镜像: python:3.10-slim
- 包含 X11 和 VNC 支持
- 包含 Qt 依赖库
- 暴露端口: 5900 (VNC)
- 用途: 运行 UI 测试和客户端

## 🔧 Docker 套接字挂载

使用挂载宿主机套接字方式，优点：

- 更轻量，不需要特权模式
- 安全性更高
- 可以直接使用宿主机的 Docker 镜像和缓存
- CI/CD 环境常用

## 📊 测试标记

使用 pytest 标记来分类测试：

- @pytest.mark.docker: 需要 Docker 环境的测试
- @pytest.mark.ui: 需要 UI 环境的测试

运行特定标记的测试：

pytest -m docker          # 只运行 Docker 测试
pytest -m "not docker"    # 跳过 Docker 测试
pytest -m ui              # 只运行 UI 测试

## 🔍 VNC 连接

1. 启动客户端容器
2. 使用 VNC 客户端连接 localhost:5900
3. 密码: 无（已禁用）

推荐的 VNC 客户端：
- macOS: Screen Sharing (内置)
- Windows: TightVNC, RealVNC
- Linux: Remmina, TigerVNC

## ⚠️ 注意事项

1. 确保宿主机 Docker 守护进程运行
2. 确保端口 5900 未被占用
3. 测试容器需要访问宿主机 Docker 套接字
4. 测试数据不会持久化，每次运行都是全新环境

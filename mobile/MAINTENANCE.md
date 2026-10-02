# Data Bridge Mobile 维护指南

## 定位

Data Bridge Mobile 是手机伴随端，不是桌面端的 Android 复刻。

目标是对齐腾讯 Marvis 类产品的架构思路：电脑负责执行任务，手机负责连接电脑、查看状态、发送指令、切换会话、查看日志，并在需要时作为远程控制入口。

## 当前技术路线

| 模块 | 技术 | 说明 |
|---|---|---|
| 手机端 | 静态 Web/PWA | 无 Python 运行时，无移动端构建工具链 |
| 通信 | HTTP + WebSocket | 复用现有 Data Bridge 服务端协议 |
| 执行端 | Windows 桌面服务 | 继续负责浏览器自动化、文件操作、模型调用和代码执行 |
| 发布形态 | 浏览器/PWA | 手机浏览器打开，也可添加到主屏幕 |

## 目录

```text
mobile/
├── README.md
├── MAINTENANCE.md
├── serve_mobile.ps1
└── web/
    ├── index.html
    ├── styles.css
    ├── app.js
    ├── app-core.mjs
    ├── manifest.webmanifest
    ├── sw.js
    └── icon.svg
```

## 运行

启动 Data Bridge PC 服务端后，再启动手机端静态服务：

```powershell
C:\Data-Bridge\mobile\serve_mobile.ps1 -Port 8787
```

手机和电脑在同一局域网时，用手机浏览器打开：

```text
http://<电脑 IP>:8787
```

登录页填写电脑 IP、端口、账号和密码。默认服务端口通常是 `8765`。

## 功能边界

手机端负责：

- 登录 PC 服务端
- 拉取消息和会话
- 通过 WebSocket 接收服务端通知
- 发送浏览器模式消息
- 发送 API 模式消息
- 切换会话
- 查看服务端状态和日志事件

手机端不负责：

- 本地运行模型
- 本地控制 Chrome
- 本地执行代码
- 本地读写项目文件
- 本地承载桌面 UI

这些能力都留在 PC 端。手机端越轻，越稳定，也越容易做成真正可用的产品。

## 为什么移除旧移动方案

旧方案把 Python UI 打进 Android 包，构建链路过重，且不符合伴随端定位。

被移除的内容包括：

- Python 移动端入口和 UI
- Android 打包脚本
- 移动端私有依赖文件
- 移动端私有服务层封装
- Android 离线构建脚本

现在 mobile 不再维护任何移动端 Python 打包路径。

## 测试

核心协议和解析逻辑在 `web/app-core.mjs`，用 Node 直接测试：

```powershell
node C:\Data-Bridge\tests\mobile_web_core.test.mjs
```

测试覆盖：

- HTTP/WebSocket 地址规范化
- 设备 ID 稳定生成
- 服务端消息解析
- RPC 消息结构
- 浏览器/API 两种发送模式

## 后续产品化路径

真正需要 App Store/应用商店形态时，不回到 Python 打包路线。推荐二选一：

- 用 Capacitor 包装当前 PWA，保留 Web 代码和轻量发布。
- 用原生 Android/iOS 重写 UI，但仍只作为伴随端，继续复用 HTTP/WebSocket 协议。

不推荐把桌面端能力塞进手机包。

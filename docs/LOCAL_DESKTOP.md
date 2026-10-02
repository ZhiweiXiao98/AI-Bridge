# 本地客户端：使用、重建与运行验收

本入口将现有 `WorkerThread`、主窗口、技能和 Pi SDK 放在同一台电脑运行。优先目标是实际可启动、可交互和可退出，不以“装入全部依赖”代替功能验收。它不需要先部署 AI Bridge 服务器，也不需要 AI Bridge 远程账号。原有远程客户端入口和远程打包脚本保持独立。

**当前是可构建、可审查的源码工作。二进制发行门槛尚未放行；CI 只上传明确列出的 JSON 证据，不提供安装包下载。** 构建成功、冒烟通过和许可证文本齐备都不自动代表安全、法律或最终发行审查完成。

## 运行范围

- 主程序冻结自己的 Python 和 Qt，内含本地 Worker、Selenium 自动化代码、Docker SDK、Chroma/fastembed/ONNX 检索引擎、Qt WebEngine、内置技能和面板
- 固定随包 Node **22.23.3**，Pi SDK **0.99.1**，按原 `runtime/pi/package-lock.json` 安装完整生产依赖树。最终用户启动应用和使用 Pi 不需要安装 Python、Node 或 npm
- 模型服务需要在现有设置页填写自己的服务地址、模型与密钥。使用第三方模型可能产生该提供商的费用；构建和自检仅调用本机模拟服务，不调用收费 API
- 主浏览器标签页使用用户已安装的 Chrome 和应用拥有的独立资料目录。用户自行登录目标网站；不会复用普通 Chrome 账号目录，也不附加到身份不明的调试端口
- 在“连接设置”填写目标网页和 Chrome/匹配驱动路径；也可在明确允许后使用包内官方 Selenium Manager 联网取得匹配驱动。未允许时不会静默下载可执行文件；不会从当前工作目录或 PATH 拾取未知驱动。客户端不自动下载整个 Chrome
- 内嵌 Qt WebEngine 仅用于网页预览，不能据此声称已支持自动对话。自动清空网页会话的 API stateless 路径在本地入口暂不可用；现有网站 DOM 适配的能力边界仍需针对目标站点确认
- Docker SDK 已随包，实际容器执行仍需用户安装并启动自己的 Docker 引擎、准备镜像。程序不会因为打包而获得 Docker 引擎
- RAG 引擎已随包，模型权重未预置。首次使用嵌入或重排模型可能联网下载；需另行确认模型许可与网络条件。离线自检只核验引擎，不伪称完成真实模型检索质量验收
- 执行项目代码、安装项目依赖或运行项目 pytest 属于开发工具功能。通过执行菜单的本地 Python 设置、`AI_BRIDGE_PYTHON`，或项目 `.venv`、`venv`、`env`、`.env` 选择外部解释器；没有解释器时给出明确提示，绝不递归启动冻结应用。Git、Rhino 等外部开发软件也需按使用功能自行配置
- 冻结应用更新采用替换整个应用。不得在安装目录执行源码 Git/pip 自更新

## 浏览器模式的实际边界

设置好 Chrome、目标网页及驱动后，可从主浏览器标签页发送、读取、停止和重连。程序只管理自己启动的专用 Chrome 和驱动，关闭时不终止用户其他浏览器。网页登录由用户在该专用窗口完成。首次安装 Chrome 请使用 Google 官方渠道；离线环境需自行提供匹配且可信的 ChromeDriver。

macOS CI 使用 **Chrome for Testing 154.0.8037.57** 和同版本驱动。Windows CI 使用标准 GitHub runner 已安装、Google LLC 签名有效的 Chrome，并配置已固定归档哈希的 **ChromeDriver 154.0.8037.57**；要求两者 `MAJOR.MINOR.BUILD` 完全相同，并分别记录实际完整版本。此预装分支不运行安装器、不修改 ACL、系统设置或浏览器沙箱。

两种测试均访问仅监听回环地址的 HTML 聊天夹具，验证真实浏览器、Selenium、Worker 和 Qt UI 的联动，不登录第三方账号、不访问真实服务、不调用模型。它们不能证明任意网站或网站的新 DOM 已经适配，也不能替代用户实际目标站点的验收。

## 用户数据与只读资源

本地入口先配置数据目录，再导入任何配置、日志、数据库、Worker 或窗口模块：

- Windows：`%LOCALAPPDATA%/AI-Bridge-Local`
- macOS：`~/Library/Application Support/AI-Bridge-Local`
- Linux 工程验证：`${XDG_DATA_HOME:-~/.local/share}/ai-bridge-local`

可用 `AI_BRIDGE_LOCAL_HOME` 指定测试或独立数据目录。配置、会话、布局和日志存放于该目录；安装包内资源通过独立只读根解析。冻结的 Pi 只接受包内 Node 和 sidecar 路径，不从工作目录、PATH 或任意环境变量替换可执行代码。

打包资源只来自已跟踪的明确公开资源：图标、内置技能及 Python 辅助文件、面板插件、公开 Prompt、默认布局、前端库及其声明。不会把整个仓库、整个 `config/`、外部技能目录、用户浏览器配置、数据库、`.env`、API 配置或密钥作为数据复制。

## 固定输入与重建

默认目标是标准 GitHub-hosted runner 的 **Windows x64** 和 **macOS arm64**。Linux x64 仅支持工程验证，不代表已经通过两个目标平台的验收。

使用审查对应 commit 的源码和 **CPython 3.12.10**。必须创建全新 venv，不复用日常 Python 环境：

```sh
python -m venv .local-desktop-venv
# macOS/Linux
source .local-desktop-venv/bin/activate
# Windows PowerShell 改用 .local-desktop-venv\Scripts\Activate.ps1
python -c "from pathlib import Path; Path('build/local-desktop').mkdir(parents=True, exist_ok=True)"
python -m pip install --only-binary=:all: --report build/local-desktop/install-report.json -r requirements-desktop-local-build.txt
python -m pip check
python -m unittest discover -s tests/public_ci -p 'test_local_desktop*.py' -v
python tools/desktop/local_build.py
python tools/desktop/local_browser_fixture.py --output build/local-desktop/browser-test
python tools/desktop/local_smoke.py --browser-fixture build/local-desktop/browser-test/runtime.json
```

上述浏览器归档流程适用于 macOS/Linux 工程验证。Windows 标准 GitHub CI 将准备浏览器那一步替换为 `python tools/desktop/local_preinstalled_browser.py --output build/local-desktop/browser-test`。该分支只读 HKLM 的 Chrome 安装记录和 Authenticode 签名，要求标准 Program Files 安装位置，并记录镜像标识、Chrome 签名与字节哈希。Chrome 版本若已与固定驱动不兼容则失败，不自动更新系统 Chrome。普通本地重建不能冒充标准 CI 或把发现浏览器当成运行通过。

构建时会从固定官方 Node 归档同时提取 Node 和临时 npm，最终包只携带 Node 与其许可证，不携带构建用 npm。无需另外安装构建用 Node/npm。`--prepare-only` 可只生成输入和许可证材料；`--print-command` 只显示冻结命令。

本地独立构建输入保留原 `requirements.lock` 的完整候选集合，并公开修正以下问题，不修改远程客户端锁：

- 对齐 `requirements.txt` 已提高的下限：google-genai 2.7.0、idna 3.17、python-multipart 0.0.30、streamlit 1.58.0、pytest-asyncio 1.4.0
- 补 pytest-socket；为 pywin32、win32_setctime 加 Windows 条件，为 POSIX 补固定 pexpect、ptyprocess、uvloop
- 原 grpcio 1.78.1 已被 PyPI 撤回，使用同系列未撤回 1.78.0；这是明确记录的依赖修订，不代表对全部依赖完成漏洞审查
- 加入固定 PyInstaller 工具链。安装后 `pip check` 必须通过，任何目标缺 wheel 都应真实失败，不能删除 RAG、Docker、浏览器或 Worker 来伪造成功

该输入是版本锁，不是跨平台哈希锁。每次安装的官方 wheel URL、版本和 SHA-256 会写入生成声明中的 `requirements-resolved.txt`；同一 OS、架构、Python ABI 可用 `--require-hashes --only-binary=:all:` 重装。实际安装集合与安装报告不一致时构建会停止。不要上传原始 pip 报告，它可能包含私有索引或构建机路径。

### Node 与 Pi 的精确性

`licenses/local/node-sources.json` 保存官方 Node 22.23.3 的 Windows/macOS/Linux 归档 SHA-256、精确源码归档 SHA-256 和核验时间。构建同时核对当前官方校验清单及已提交哈希，并运行包内 Node 读取实际版本；尚未完成发行者签名独立验证。

Pi 原锁中七个 `@earendil-works` 子包缺 `integrity`。`licenses/local/npm-integrity.json` 补充官方 registry 的原版本 SHA-512，不改变原锁或版本。构建用 `npm ci --omit=dev --ignore-scripts`，保留完整生产依赖树和相对 `.bin` 链接。原锁有哈希的包交给 npm 校验；上述七包另取固定归档验证 SHA-512，并逐文件比对实际安装字节。目标平台不适用的可选包明确记录，不隐藏缺少的必需包。

依赖安装脚本不执行。真正冻结的 Pi SDK 初始化、模型往返、工具执行和关闭必须由后续冒烟验证，不能把“npm 安装成功”当成功运行的证明。

## 自动验收做了什么

`local_smoke.py` 创建全新空数据目录，清除外部模型凭证和 Python/Node 搜索路径，再启动真正冻结后的应用。它要求：

1. 本地 Worker 和完整主窗口真实启动，内置技能与面板实际加载
2. RAG、ONNX、Docker、Selenium、QtWebEngine 核心导入成功，内嵌浏览器没有静默退回简易渲染器
3. 包内精确 Node/Pi 接入仅监听回环地址的模拟模型，完成真实工具批准、真实文件读取、拒绝不写入、取消不写入
4. 原生 Pi 会话保存与续聊成功，项目锁释放，Worker 和 Pi 正常退出
5. 再启动第二个真正的应用进程，看到原会话、历史及相同 Pi 会话，且模拟模型密钥已清除
6. 用另一个全新空目录启动第三个冻结应用进程，显式提供已校验的官方 Chrome 与匹配驱动，验证真实 UI 发送、回执、流式/最终文本、停止和待发队列清除；点击 UI 重连并正常关闭专用 Chrome 后，要求旧进程退出、新进程恢复同一资料目录的至少四条消息；另验证活动生成中关闭主窗口，以及所有已观察到的自有后代退出

浏览器检查记录 WebDriver capabilities 暴露的精确 Chrome/驱动版本、实际分块快照数量与进程清理证据。此恢复测试限定为应用拥有的 Chrome 正常关闭后重连，记录 `browser_restart_method=owned-graceful-reconnect`、`crash_recovery_tested=false`，不代表强杀、崩溃或断电后历史一定恢复。Chrome 进程重启与应用进程重启严格区分：`application_process_restart=false` 明确保留浏览器链路应用重启恢复未覆盖的边界，不能把 API 链路的第二进程恢复当成浏览器恢复。

`licenses/local/browser-test-sources.json` 保存官方 CfT 版本清单 URL、三个工程目标归档的实际下载 SHA-256 和大小。解压器保留 macOS framework 的内部相对链接，拒绝路径穿越、外部链接和特殊文件。macOS 使用完整固定 CfT；Windows 独立标注 `runner-preinstalled-chrome` 来源，仅取得固定驱动，不把预装 Chrome 伪称为下载的 CfT。原 CfT 分支仍强制浏览器/驱动精确同版本及固定归档来源。测试运行时不加入 `resources/`、`dist/` 或任何上传清单的二进制内容；JSON 仅记录版本、官方来源、镜像/签名及校验值。当前云执行环境拒绝 Chrome 必需的 AF_UNIX 能力，因此不能在这里假称浏览器实跑成功；真实浏览器执行依赖 Mac/Windows CI 的终态证据。

如只需独立诊断 API 链路，可显式执行 `local_smoke.py --api-only`。其 JSON 会把浏览器自检标为未运行，不能代替默认验收。

原始日志和测试会话留在构建机临时路径，不上传。失败时在清理专用目录前只输出去除路径、模拟凭证的 traceback 摘要，便于定位 Windows 无控制台应用错误。公开证据只包含安全选取的布尔结论、版本、检查项、数量及固定测试运行时来源，不包含用户/runner 绝对路径、密钥、模型请求或会话正文。

以上不是对真实外部模型、网站登录、Docker 镜像、RAG 模型质量或两个目标操作系统全部功能的验收。源码测试、Linux 冻结构建和 Windows/macOS 冻结构建分别记录，不能互相替代。

## 清单、许可材料与发行阻塞

输出目录 `build/local-desktop/` 包含：

- `resources/`：准确的公开资源、官方 Node 与锁定 Pi 依赖；不公开上传
- `generated-notices/`：完整构建环境 Python 包、实际安装 npm 包、Node、已有 Qt/Python 来源线索与前端资源的许可文本及校验信息
- `dist/AI-Bridge-Local`，macOS 另有 `.app`：本地未批准发行产物
- `review/local-build-inputs.json`：输入版本、来源、资源哈希及 npm 平台可选缺项
- `review/local-desktop-inventory.json`：实际 PYZ 模块、原生文件、前后 SHA-256、TOC/RECORD/npm 来源映射、缺口及发行阻塞
- `review/local-smoke.json`：经过筛选的 API 运行与第二进程恢复、真实浏览器夹具和所有权清理证据，各自明确未覆盖项

完整本地包没有套用远程客户端的缩减依赖白名单，也没有复用排除 QtWebEngine、Chroma、fastembed、Docker、Selenium、Worker 的策略。实际运行时依赖由最终文件/PYZ 归属确认；构建环境内未分发的开发包另列，不能把安装环境当成运行时 BOM。

发行前至少仍需独立完成：

- QtWebEngine/Chromium、可能进入依赖图的 QtPdf/QtVirtualKeyboard、Qt/PySide/Shiboken 及其内嵌组件逐项许可路线、对应源码和可替换性核验
- Node/V8/OpenSSL/libuv、ONNX、Chroma、tokenizers、Pi 及内嵌第三方原生组件和模型的独立许可/安全审查
- 每个平台可观察的原生 LGPL 库替换及完整重新组合测试；现有远程包的支持模块探针不替代完整本地包验证
- 缺许可证文本、缺来源映射和系统原生库再分发权限的逐项解决，保留实际对应源码、补丁和构建参数
- Windows/macOS 目标平台实际冻结运行、签名/公证和最终归档隐私审查

GitHub 工作流无论成功或失败都只允许上传上述三份明确 JSON，权限为 `contents: read`。自检开始先写 `running`，失败则覆写为 `failed` 并保留阶段、错误类型和脱敏摘要，不能把旧成功记录当作这次结果；每种状态均明确不批准二进制发行。不上传依赖二进制、安装包、原始安装报告、浏览器状态或日志，不提供跳过审查的发行参数，也不使用签名密钥或创建 Release。

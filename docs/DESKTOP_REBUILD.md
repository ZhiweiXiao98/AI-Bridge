# 桌面客户端的可核验重建与库重新组合

当前仅验证构建过程，**不提供公开二进制下载，也不宣称字节级可重复构建或完整 LGPL 履约已经完成**。以下步骤不要求私有签名密钥。应用自有源码按 MIT 提供，第三方代码按其原许可证使用。

## 1. 固定构建输入

使用与清单一致的操作系统、CPU 架构和 CPython 3.12.10。分别构建 Windows x64 和 macOS ARM64（Apple Silicon）；不能把某平台的 wheel 用作另一平台的证据。

先从审查对应的公开 Git commit 检出完整源码。在全新目录创建一次性虚拟环境，不使用日常工作的 Python 环境：

```sh
python -m venv .desktop-venv
# macOS/Linux
source .desktop-venv/bin/activate
# Windows PowerShell 使用 .desktop-venv\Scripts\Activate.ps1
python -c "from pathlib import Path; Path('build/desktop').mkdir(parents=True, exist_ok=True)"
python -m pip install --report build/desktop/install-report.json -r requirements-desktop-build.txt
python -m unittest discover -s tests/public_ci -p 'test_desktop*.py' -v
python tools/desktop/build.py
python tools/desktop/smoke.py
```

`requirements-desktop-build.txt` 固定完整依赖版本；本次 pip 安装报告另外记录实际 wheel 的文件名、下载 URL 和 SHA-256。不要上传原始安装报告：其中可能包含私有索引信息。打包工具只导出不含凭证、查询参数的 PyPI 官方公开下载 URL。

若要复现同一平台的确切 wheel，先检查 `THIRD_PARTY_NOTICES/python-packages.json` 中每个候选包都存在 `wheel` 记录，再在新的同平台环境中执行：

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements-resolved.txt
```

`requirements-resolved.txt` 位于生成的许可证目录中，使用本次 wheel 的精确 URL/哈希。若本地安装报告缺项，不能把这个文件视作完整锁；先在全新 venv 重新安装并留证。不要将不同平台的该文件混用。

除源码 commit、wheel 外，还要保留 `desktop-inventory.json` 中的构建脚本哈希、Python/Qt 冻结运行时版本、实际 PYZ 成员、原生文件版本和输入/输出 SHA-256。PE 版本资源或 Mach-O load command 的版本不是其上游源码版本的证明。签名、编译工具、时间戳及 runner 系统镜像可导致不同输出哈希。

## 2. 取得相应源码和声明

`licenses/desktop/sources.json` 给出 Qt / PySide / Shiboken 6.11.1 的官方完整源码档案与上游公布的 SHA-256；`python-sources.json` 给出相应 Python distribution 的源码档案与 PyPI 公布的 SHA-256，包括 certifi 的 MPL 覆盖源码。

下载后必须自行计算 SHA-256 并与记录比较。上述记录不表示已下载整个 Qt 源码，也不证明 wheel 没有未记录补丁或特殊构建参数。继续发行核验时，应保留实际构建对应的源码、补丁、构建选项和上游依赖声明，核对其与目标库的对应关系；不能只链接项目主页。

## 3. 已自动化的重新组合探针

在同一个一次性 venv 中运行：

```sh
python tools/desktop/recombine.py
```

该测试在 LGPL 覆盖的 `PySide6.support.deprecated` Python 源码末尾加入一个无行为副作用的标记，重新构建应用，再由冻结登录窗口 smoke 读取标记。它证明修改后的 PySide 支持代码确实重新进入 PYZ 并被运行。测试无账号、网络请求或服务器登录，结束时恢复原始源码字节并清理该模块缓存。

证据写入 `build/desktop/review/recombination-test.json`，记录修改前后 SHA-256、观察到的标记和范围。它不等于已完成全部 Qt 原生库替换验证。修改后的 probe 产物仅用于本地/临时 CI 测试，不上传或发布。

## 4. 仍需验收的原生库替换 / 完整重新组合

若更换 Qt / PySide / Shiboken 原生部分，应从上述精确源码起步，使用相同 Python ABI、Qt 公共接口与目标架构生成自己的兼容 wheel，在新 venv 中安装并重建应用。保留自己的源码改动、工具链、配置和 wheel 哈希。不要直接把其他版本、其他架构的 DLL/framework 混入。

须用有可观察修改的接口兼容库运行登录、GUI、网络相关探针，证明加载的是用户修改版本；现有登录 smoke 不代替完整功能测试。Windows x64 和 macOS ARM64 都须分别留下证据。

macOS 优先通过完整 PyInstaller 构建重新生成 `.app`，由 PyInstaller 对自己的修改产物作 ad-hoc 签名。若进行手工 shared-library 替换，必须保留 framework 目录层次、相对 symlink、install name/rpath，按内层库到外层 app 的顺序重新签名；不能把对外层一次 `--deep` 签名当作正确重签顺序的替代。最后可执行：

```sh
codesign --verify --deep --strict --verbose=2 build/desktop/dist/AI-Bridge-Remote.app
python tools/desktop/smoke.py
```

ad-hoc 签名不会获得 Developer ID 信任或 Apple 公证。测试不得依赖本项目的私有签名密钥，不得绕过系统安全警告。相关参考：[PyInstaller 6.22.0 签名说明](https://pyinstaller.org/en/v6.22.0/feature-notes.html#macos-binary-code-signing)、[Apple TN2206](https://developer.apple.com/library/archive/technotes/tn2206/_index.html)。

## 5. 发行门槛保持关闭

必须先解决实际清单中的原生/第三方来源缺口、平台再分发条件、完整对应源码可取得性、上述平台探针以及最终归档隐私/声明核验。成功构建、登录 smoke 或本次重新组合探针均不自动批准发行。当前源码工作流仅上传两个明确 JSON 路径，没有二进制上传开关、签名凭证、release、merge 或长期源码书面承诺。

# 测试说明

在仓库根目录使用项目虚拟环境。依赖安装方法见 [README](../README.md)。

## 默认集合与协议检查

```powershell
# 远程协议聚焦回归，可从其它目录调用此脚本
.\run_checks.ps1

# 指定模块
.\run_checks.ps1 -TestPaths tests/test_journal_search.py,tests/test_structure_dump.py

# pytest.ini 的默认集合
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -q
```

`run_checks.ps1` 使用仓库自己的 `.venv`，默认运行 `tests/test_remote_protocol.py`，并传递 pytest 退出码。`-InstallDependencies` 会先安装 `requirements.txt`。

默认集合排除 `slow` 和 `benchmark`。其余 UI、Docker 和集成测试仍可能被选中；按改动范围选择目标，结果中注明通过、跳过和未验证项。

## 常用分组

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -m slow
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -m docker
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -m benchmark
```

命令行 `-m` 覆盖默认标记表达式。标记定义在 `pytest.ini`。`tests/conftest.py` 在 Docker 不可用时跳过相关 Docker 测试；其它外部依赖由对应测试与 fixture 决定。

## UI 与覆盖率

在没有显示设备的环境中，先设置 Qt 的 offscreen 平台，再运行指定 UI 用例：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_doc_organizer_preview.py -q
```

覆盖率需要显式传入插件选项：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests --cov=app --cov-report=term-missing --cov-report=html
```

`htmlcov/`、`.coverage` 和 `coverage.json` 是本地报告。覆盖率和通过数量以实际命令输出为准，历史阶段报告用于追溯。

## 编写与隔离

`tests/helpers.py` 提供 `RecordingSignal`、`RecordingLock` 等轻量替身。新增 bridge / consumer 测试优先复用它们。

读写配置、对话、索引和项目状态的测试使用 `tmp_path` 与替换路径，避免改写开发者本机数据。涉及持久化时重新构造对象或重新加载文件，验证完整行为。

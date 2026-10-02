# Docker 拉取镜像卡住 问题修复记录

日期: 2026-02-26

概述
--
在一台 Windows 开发机上，浏览器可正常访问互联网，但在 PowerShell 中执行 `docker pull python:3.13-slim` 时命令卡住无响应。经排查发现 Docker CLI 可运行但与守护进程（Docker Desktop / WSL2 后端）通信时超时。

影响范围
--
- 无法通过 `docker` 命令从 registry 拉取镜像
- Docker Desktop GUI 显示服务状态不稳定或守护进程未完全就绪

关键发现
--
1. 初步检查发现 Windows 服务 `com.docker.service` 一开始处于 Stopped 状态，后手动启动为 Running。
2. 在服务为 Running 的情况下，使用命名管道访问守护进程 `docker -H npipe:////./pipe/docker_engine info` 会超时（客户端挂起）。
3. 从 Docker Desktop 的 WSL 后端日志（`C:\Users\1\AppData\Local\Docker\log\vm\init.log`）发现引导阶段报错：缺少 `/opt/docker-desktop/componentsVersion.json`，并出现对 `/run/host-services/backend.sock` 的 IPC 连接失败与超时。
4. 因为 WSL 内部的引导失败，守护进程虽有进程存在，但无法完成 bootstrap，导致 CLI 请求命名管道时无法收到响应。

修复步骤（实际执行）
--
1. 确认 Windows 上存在 componentsVersion.json

	在 PowerShell 中执行：

	```powershell
	Get-ChildItem "C:\Program Files\Docker" -Recurse -Filter componentsVersion.json
	```

	结果：找到文件 `C:\Program Files\Docker\Docker\resources\componentsVersion.json`。

2. 将该文件写入到 `docker-desktop` WSL 发行版的 `/opt/docker-desktop`（以 root 写入）

	在管理员 PowerShell 中执行：

	```powershell
	Get-Content -Raw -Encoding UTF8 "C:\Program Files\Docker\Docker\resources\componentsVersion.json" \
	  | wsl -d docker-desktop -u root -- sh -lc "mkdir -p /opt/docker-desktop && cat > /opt/docker-desktop/componentsVersion.json && chmod 644 /opt/docker-desktop/componentsVersion.json && echo 'WROTE_OK' && ls -l /opt/docker-desktop/componentsVersion.json"
	```

	预期输出包含 `WROTE_OK` 以及 `/opt/docker-desktop/componentsVersion.json` 的文件信息。实际显示：

	```text
	WROTE_OK
	-rw-r--r--    1 root     root           509 Feb 26 14:09 /opt/docker-desktop/componentsVersion.json
	```

3. 重启 WSL 与 Docker 服务，验证命名管道与守护进程

	```powershell
	wsl --shutdown
	Restart-Service -Name com.docker.service -Force
	Start-Sleep -Seconds 8
	Test-Path \\.\pipe\docker_engine
	```

	`Test-Path` 返回 `True` 表示命名管道已创建。

4. 非阻塞方式确认守护进程响应

	使用短超时的后台 job 来验证：

	```powershell
	$job = Start-Job -ScriptBlock { docker -H npipe:////./pipe/docker_engine info 2>&1 }
	if (-not (Wait-Job -Job $job -Timeout 15)) {
	  Write-Output "==== TIMED_OUT ===="
	} else {
	  Write-Output "==== COMPLETED ===="
	  Receive-Job -Job $job
	}
	```

	修复后输出为 `==== COMPLETED ====`, 并成功返回 `docker info` 的 Server 信息（包括 Server Version、Storage Driver、HTTP Proxy 等配置）。

5. 验证拉取镜像

	使用正确的 pull 命令（注意：`--progress` 不是 docker pull 的参数）：

	```powershell
	docker pull python:3.13-slim
	```

	结果：命令成功完成，输出例如：

	```text
	Digest: sha256:... 
	Status: Image is up to date for python:3.13-slim
	docker.io/library/python:3.13-slim
	```

根本原因
--
Docker Desktop 的 WSL 后端在 bootstrap 阶段期望 `/opt/docker-desktop/componentsVersion.json` 存在来判断组件版本与启动流程。该文件缺失导致后端引导失败（IPC socket 未就绪），尽管 Windows 服务被标记为 Running，但内部后端进程没有完成初始化，因此 CLI 发出的命名管道请求超时等待响应。

解决效果
--
将缺失文件从宿主机安装目录写入 WSL 中并重启后端，Docker Desktop 成功完成引导，`docker info` 与 `docker pull` 恢复正常。

后续建议（预防 / 维运）
--
1. 升级或修复安装：若怀疑安装包不完整或未来再次出现缺少文件，考虑使用 Docker Desktop 的 Repair/Reset 功能或重新安装最新版本。
2. 备份重要数据：定期导出本地重要镜像（`docker save`）和容器状态，以防 `docker-desktop-data` 损坏需重建时丢失数据。示例：

	```powershell
	docker save -o c:\backups\myimage.tar myimage:tag
	```

3. 代理与网络：如果处于公司网络并通过代理访问外部 registry，检查 Docker Desktop → Settings → Resources → Proxies 中的设置，并确保 `NO_PROXY` 配置包含内部加速器或 registry 地址。

4. 日志监控：出现类似阻塞时先查看 `C:\Users\<user>\AppData\Local\Docker\log\vm\init.log` 与 `host` 日志来定位缺失文件、socket 权限或 wsl-bootstrap 的超时信息。

记录人: 修复操作由开发者与支持协作完成（操作日志已记录于会话）

-- 结束 --


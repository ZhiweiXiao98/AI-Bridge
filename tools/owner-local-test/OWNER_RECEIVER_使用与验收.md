# 本人测试包本地接收说明

源码d51dc1e、本次沿用的收件公钥及材料范围已绑定。实际接收入口仍为false，独立交付收据hash仍为TBD，必须在取得真实CI运行与ZIP证据后由发布负责人绑定；不能从加密封套自我证明来源。此文及公开配方不包含私钥。

## 文件与入口

- `extract_owner_artifacts.py`：正式有界ZIP提取模块
- `open_owner_package.py`：独立收据绑定及实际接收器wrapper
- `tests/test_owner_receiver_integration.py`：ZIP、收据和本地映射的拒绝测试
- `streaming-seal-tests/test_real_interop.py`：调用上述正式模块的真实合成RSA/AES往返

API：`extract_artifacts(artifacts, local_files, output_directory, expected=...)` 与 `recover_with_key(receipt_path, local_files, output_directory, private_key=...)`。后者的private_key是本地进程内对象，不是命令行参数或可序列化上传对象。

## 独立交付收据

固定文件名为 `owner-delivery-receipt.json`，最大64KiB。批准后的wrapper须固定其原始文件字节SHA-256；该hash必须由可信下载工具回执/本人可信渠道传递，不能从收到的envelope自证。这是可信渠道绑定，不是发送者数字签名认证。

收据只允许：schema_version=1、filename、source_commit、workflow_commit、run_id、run_attempt、recipient_sha256、materials_manifest_sha256、archive_size、archive_sha256、artifacts及binary_distribution_approved=false。

每个artifacts记录必须精确包含number、GitHub artifact name、artifact_id、run_id、run_attempt、ZIP实际size和sha256。name固定为 `owner-local-cipher-序号-完整workflowSHA`；序号从001连续排列。数量由独立DMG长度决定，最多128件。

本地工具可能把ZIP重命名。须另给显式映射：schema_version=1，artifacts列表中的每项只有artifact_id和本地绝对物理path。本地文件名不构成GitHub身份。模块只消费映射中的确切文件，拒绝缺失、额外、重复ID及重复路径/文件inode，不扫描目录猜测文件身份。

## ZIP和解密边界

每件实际ZIP先按1MiB块计算hash并核对可信收据size；必须≤32MiB。第001件只接受part001和envelope，其他件只接受对应单片。所有路径逐级O_NOFOLLOW，输入必须regular file，输出全新0700目录、0600文件。

EOCD在ZipFile解析之前有界检查：最多两条记录，central directory最多4096字节；拒绝ZIP64、跨磁盘、评论、前后附加数据、额外/重复/穿越/链接条目、未知flag及不一致的local/central header。支持ZIP_STORED与安全有界DEFLATE（包括level0）；实际解压长度、CRC、真实deflate EOF及尾随数据都检查，不信任声明的“小尺寸”。异常压缩比例也拒绝，不能用压缩炸弹越过输出上限。

只有全部ZIP验证通过才落地envelope。wrapper先验证独立收据及封套上下文，再请求私钥，最后调用已审查的receive_local核心。GCM认证和独立明文hash/size均通过后，才出现verified目录中的最终DMG和完成标记。失败不安装、不运行、不上传；异常时不打印私钥相关traceback。

## 本地私钥加载方案

未来获批后，CLI只接受 --receipt、--artifact-map 和 --output。不提供私钥、私钥路径或口令参数，也不从环境变量读取秘密。仅本人交互终端通过隐藏输入选择本地私钥绝对路径及口令；拒绝管道/无TTY。文件须由当前用户持有、权限0400/0600、无symlink祖先及额外硬链接，最大32KiB。实际私钥加载路径本轮未执行，不读取owner秘密。

若需启用，应由本人在自己的可信设备运行；私钥不得进入构建机、聊天、日志或上传目录。Python/OpenSSL不保证RAM中秘密可靠擦除。删除临时文件也不是介质级安全擦除。

## 已验证和剩余限制

- 25项提取/收据拒绝测试通过，包含伪造小尺寸的大DEFLATE流、CRC、未知/重复条目、路径、32MiB上限和私钥加载前阻断
- 17项真实RSA-3072/AES-GCM互通测试通过。48MiB+17字节经过正式提取器及wrapper，STORE和deflate0两种实际ZIP都恢复成功
- 最大合成ZIP为25,173,026字节，距32MiB上限余8,381,406字节；随机本地文件名通过显式artifact ID映射正确关联
- 26项原流式测试复跑通过。没有owner密钥输入、真实应用输入或发布；合成RSA私钥仅驻内存，未序列化，测试临时目录已删除

已有配方已完成独立源码审查，首版887安装包已完成真实Mac只读DMG验收及加密上传，首版实际GitHub下载ZIP结构也已核验。r2更新源码绑定后，仍须完成本轮材料绑定复核、真实构建及挂载完整验收、独立收据绑定与认证解密；首版证据不能替代本轮证据。Mac本机私钥加载与文件系统验证、3GiB压力测试未在此声称完成。公开配方中的source/recipient/materials指纹为固定来源约束；实际CI工作流提交、运行编号、ZIP摘要和最终DMG摘要须由独立可信回执补齐。

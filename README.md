# Requirement Workbench（Demo）

**项目状态：Demo / MVP。** 这是一个在本地运行的 AI 邮件需求工作台演示项目，用于展示从邮件整理、逐项澄清需求到导出 Markdown 的最小流程；本仓库不提供线上服务。默认的 10 条邮件线程、AI 分析和发信均使用 Mock 数据，模拟回复不会寄出真实邮件。

首页为空间玻璃卡片，进入后可以查看邮件、逐项澄清需求并导出 Markdown。真实 IMAP/SMTP 邮箱和 DeepSeek 是可选的本地配置；代码提供接入链路，但尚未使用真实账号完成联机验收，不应把默认演示结果理解为真实邮件或真实模型的运行结果。

界面使用简体中文；邮件主题、正文、发件人和附件文件名保持邮件原来的语言。

## 本地启动

需要 Node.js 20.9+、Python 3.11+。在项目根目录运行：

```bash
bash scripts/dev.sh
```

首次运行会创建 `.venv` 并安装依赖。打开 http://localhost:3000 。后端在 http://localhost:8000 ，接口文档在 http://localhost:8000/docs 。退出使用 Ctrl+C。

若默认端口被其他项目占用，使用 `FRONTEND_PORT=3001 BACKEND_PORT=8001 bash scripts/dev.sh`，打开 http://localhost:3001 。启动脚本会拒绝复用已占用端口，避免连接到其他项目。

默认使用 Mock 邮箱和 Mock AI，包含 10 个演示线程。所有发信均为本地模拟，不会向外部联系人发送邮件。SQLite 保存于 `backend/data/requirement_workbench.sqlite3`。

## DeepSeek

复制 `backend/.env.example` 为 `backend/.env`，设置 `LLM_PROVIDER=deepseek` 和 `DEEPSEEK_API_KEY`，再运行启动脚本。密钥仅供后端使用。无密钥时会明确标识为 Mock。附件只向模型提供文件名、类型和大小。

## 真实邮箱

真实邮箱使用通用 IMAP 收件和 SMTP 发信，不绑定某一家邮箱。复制 `backend/.env.example` 为 `backend/.env`，设置 `MAIL_PROVIDER=imap`，填写 `MAIL_IMAP_*` 和 `MAIL_SMTP_*`。Gmail、QQ、163、Outlook 等邮箱通常需要先开启 IMAP/SMTP，并使用客户端专用密码或应用密码；不要把密码写入前端或提交到 Git。

启动后点击首页的“同步邮件”即可拉取最近邮件。`MAIL_IMAP_LIMIT` 控制每次最多读取多少封，`MAIL_IMAP_TIMEOUT=45` 控制 IMAP 网络超时秒数，`MAIL_IMAP_MARK_SEEN=false` 默认不会修改邮箱的已读状态。同步会在本地保存邮件正文、发件人和附件原件供下载；传给 DeepSeek 的只有附件文件名、类型和大小，不含附件内容。若开启 `MAIL_IMAP_MARK_SEEN`，邮件会在本地入库成功后才标为已读。

首次启用真实邮箱时，“自动回复”会关闭；需要时可在界面里主动开启。即使自动回复关闭，你仍可在真实邮件的详情页手动发送回复。演示线程不会通过真实邮箱发出。

例如 Gmail 通常使用 `imap.gmail.com:993` 和 `smtp.gmail.com:465`；QQ 邮箱通常使用 `imap.qq.com:993` 和 `smtp.qq.com:465`。具体地址和端口以邮箱服务商的设置页为准。

## 演示路径

拖动首页 → 进入需求 → 阅读邮件与附件 → 在智能助手中回答当前问题 → 检查需求 Markdown → 复制或下载 → 查看回复记录 → 返回首页。

AUTO REPLY、线程和单邮件 DO NOT REPLY 由服务端校验。未知字段保持为空。附件仍只作为元数据展示，不会进入 AI 分析。

## 检查

```bash
.venv/bin/python -m pytest backend/tests -q
cd frontend
npm run typecheck
npm run build
```

启动前端后，在项目根目录运行 `bash scripts/smoke.sh`，可检查临时 Mock 数据库的后端接口和中文首页；如果前端未启动，脚本会明确提示跳过前端检查。

产品需求见 `docs/PRODUCT.md`，历史 HTTP 契约见 `docs/API_CONTRACT.md`。

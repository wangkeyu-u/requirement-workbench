# MVP 验收记录

## 结论

Mock 邮箱的演示主链路已通过浏览器和 API 验收。真实邮箱已加入通用 IMAP/SMTP provider；真实 DeepSeek 和邮箱网络调用仍需要用户在本机配置凭据后验证。

## 浏览器验证

- WebGPU/TSL 渲染运行，10 条 live threads 可见；空间任务实测拖拽约 +319px、进入详情与返回首页。
- 主任务在内置浏览器连续提交 deadline 和 acceptance_criteria 两个演示答案：完整度 87% → 90% → 97%，每次只有一个问题。
- 最后一次回答后自动生成 Mock outbound 邮件和 reply_log，状态 replied；重复发送按钮禁用。
- Markdown 页面显示新答案，已解决的问题不再出现在 Open Questions。
- Chrome 实测 Copy Markdown，并通过粘贴核对完整文档内容。
- Chrome 下载记录确认 application-performance-dashboard.md（1,125 B）及 performance-dashboard-reference.pdf（601 B）完成。
- Chrome 打开附件，PDF 查看器显示 1 页、“PDF 已加载完毕”及 Requirement reference。
- Codex 内置浏览器的 PDF 扩展被宿主屏蔽、下载事件回调未返回，已改用 Chrome 完成验证，未绕过屏蔽。

## 自动检查与 API

- 前端 typecheck、生产 build 通过；本轮小改后 typecheck 再次通过。
- 后端 14 项测试通过，覆盖初始化、增量更新、自动回复、禁止回复、重复发送、重启持久化、DeepSeek 错误处理及附件结构。
- settings、threads、detail、Markdown、附件 inline/download 正常；10 条线程。
- `POST /api/mail/sync` 已覆盖真实邮箱消息的幂等导入、线程归并和附件元数据保存。
- 全局 AUTO REPLY 可持久化，关闭时拒绝发送；线程和邮件 DO NOT REPLY 均返回 409。

## 当前运行与演示数据

3000/8000 已被另一个目录的应用占用，本项目运行在 http://localhost:3001 与 http://localhost:8001 。启动脚本支持 FRONTEND_PORT=3001 BACKEND_PORT=8001，并拒绝复用被占用的端口。

AUTO REPLY 为 true。Customer export 和 Application performance dashboard 保留验收产生的模拟回复；后者含明确标注 demo 的期限与验收答案。没有发送真实邮件。

## 验证边界

- 未进行长时间 GPU 压力/帧率测量。
- DeepSeek 真实密钥调用和 IMAP/SMTP 网络连接未测试，配置、解析、失败路径和幂等导入已有测试。
- Mock 风险提示是轻量演示数据，不等同于完整需求审查。

## 已修复问题

- 运行库误清理导致无表：已恢复，测试仅清临时目录。
- Next dev/build 输出冲突：隔离 .next-dev 与 .next。
- 问题重启后恢复、已解决问题残留、自动回复缺失、无效附件、DeepSeek 静默降级均已修复。
- 下载 Blob URL 延迟释放，避免浏览器消费前失效。

# MVP HTTP 契约

历史接口设计记录。当前行为以 `backend/main.py` 与接口测试为准。

## HTTP 契约
API base 为 NEXT_PUBLIC_API_URL 或 http://localhost:8000。允许本地 localhost/127.0.0.1 的 3000、3001 和配置的 FRONTEND_PORT 使用 CORS。
GET /api/threads -> Thread[]
POST /api/mail/sync -> {provider,fetched,imported,skipped,threads}
GET /api/threads/{id} -> {thread:Thread,emails:Email[],requirement:Requirement,question:Question|null,reply_log:Reply[]}
POST /api/threads/{id}/analyze -> 同详情
POST /api/threads/{id}/answer body {answer:string} -> 同详情
PATCH /api/threads/{id} body {do_not_reply:boolean} -> 同详情
PATCH /api/emails/{id} body {do_not_reply:boolean} -> {ok:true}
GET /api/settings -> {auto_reply:boolean,llm_provider:string,mail_provider:string}
PATCH /api/settings body {auto_reply:boolean} -> settings
POST /api/threads/{id}/reply -> 同详情；Mock 模式模拟发信，真实邮箱模式使用 SMTP。手动发送不受自动回复开关限制；线程/邮件禁止回复和防重复由后端检查，演示线程不能通过真实邮箱发送。
POST /api/threads/{id}/reply/resolve body {delivered:boolean} -> 同详情；仅用于 SMTP 结果待确认的记录。确认已发送会记录回复，确认未发送会允许重新发送。
GET /api/requirements/{id}/markdown -> {markdown:string}
GET /api/attachments/{id}?download=true -> 文件（不送模型）
GET /api/health -> {ok:true}

Thread: {id,title,sender,subject,preview,status,completeness,unread_count,question_count,updated_at,do_not_reply,requirement_id,category}
Email: {id,thread_id,sender,sender_email,subject,body,received_at,direction:'inbound'|'outbound',do_not_reply,attachments:Attachment[]}
Attachment: {id,filename,content_type,size}
Question: {field:string,text:string}
Reply: {id,body,status:'sending'|'uncertain'|'sent',created_at}
Requirement: 文档第8节字段，字符串与数组按文档约定；id 为 requirement_id，status 字符串，completeness 数字。
状态统一 waiting_for_me / ready / replied / no_action / do_not_reply。

默认至少10个真实感 Mock thread。Mock 模式可完整演示。配置 `MAIL_PROVIDER=imap` 后，`POST /api/mail/sync` 使用 IMAP 收件、SMTP 发信；后端需提供幂等初始化并持久化用户回答。一次回答仅写当前 question.field；对未确认事实不做承诺。附件内容不得进入模型上下文。

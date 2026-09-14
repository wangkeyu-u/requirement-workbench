# MVP 协作契约

完整需求见 PRODUCT.md。三个任务使用同一目录，禁止覆盖他人文件、git reset 或替他人提交。主任务负责集成与验收。

## 文件归属
- 空间首页：frontend/package.json、配置、src/app/*、src/components/spatial/*、全局样式；负责 Next.js 启动壳，集成 WorkbenchShell。
- 详情工作台：frontend/src/components/workbench/*，自己的 CSS module；不改 package.json 或 app。提供 default export WorkbenchShell，props {threadId:string,onClose:()=>void,onUpdated?:()=>void}。
- 后端：backend/**，负责 FastAPI + SQLite、Mock 邮箱/LLM、DeepSeek adapter、测试。
- 主任务：docs/**、frontend/src/lib/**、根 README、启动脚本与必要集成修复。

## HTTP 契约
API base 为 NEXT_PUBLIC_API_URL 或 http://localhost:8000。允许 localhost:3000 CORS。
GET /api/threads -> Thread[]
POST /api/mail/sync -> {provider,fetched,imported,skipped,threads}
GET /api/threads/{id} -> {thread:Thread,emails:Email[],requirement:Requirement,question:Question|null,reply_log:Reply[]}
POST /api/threads/{id}/analyze -> 同详情
POST /api/threads/{id}/answer body {answer:string} -> 同详情
PATCH /api/threads/{id} body {do_not_reply:boolean} -> 同详情
PATCH /api/emails/{id} body {do_not_reply:boolean} -> {ok:true}
GET /api/settings -> {auto_reply:boolean,llm_provider:string,mail_provider:string}
PATCH /api/settings body {auto_reply:boolean} -> settings
POST /api/threads/{id}/reply -> 同详情；模拟发信，后端强制检查全局及邮件/线程禁止状态并防重复。
GET /api/requirements/{id}/markdown -> {markdown:string}
GET /api/attachments/{id}?download=true -> 文件（不送模型）
GET /api/health -> {ok:true}

Thread: {id,title,sender,subject,preview,status,completeness,unread_count,question_count,updated_at,do_not_reply,requirement_id,category}
Email: {id,thread_id,sender,sender_email,subject,body,received_at,direction:'inbound'|'outbound',do_not_reply,attachments:Attachment[]}
Attachment: {id,filename,content_type,size}
Question: {field:string,text:string}
Reply: {id,body,status,created_at}
Requirement: 文档第8节字段，字符串与数组按文档约定；id 为 requirement_id，status 字符串，completeness 数字。
状态统一 waiting_for_me / ready / replied / no_action / do_not_reply。

默认至少10个真实感 Mock thread。Mock 模式可完整演示。配置 `MAIL_PROVIDER=imap` 后，`POST /api/mail/sync` 使用 IMAP 收件、SMTP 发信；后端需提供幂等初始化并持久化用户回答。一次回答仅写当前 question.field；对未确认事实不做承诺。附件内容不得进入模型上下文。

前端 dark charcoal + warm ivory + muted sage，低饱和玻璃材质，真实 HTML 字。主页英文产品界面，保持视觉一致。详情正常 DOM。禁止只以 CSS blur 冒充 shader。WebGPU 不可用提供可操作 fallback。可读取其他任务文件，但只修改归属范围；遇到契约问题向主任务报告。

# Requirement Workbench Demo

## 1. Product Vision

开发一个个人使用的 AI 邮件需求工作台。

它的核心体验可以概括为：

> **一个打开后足够惊艳的工作台 + 一个老实、本分、不擅自做决定的 AI 员工。**

用户不需要自己逐封阅读、整理和理解需求邮件。

系统负责：

**收取邮件 → 理解邮件 → 判断是否需要处理 → 发现需求 → 向用户追问 → 整理 Requirement → 自动回复邮件**

前端视觉必须具有明显辨识度。

不能做成普通：

* Gmail Clone
* Notion Clone
* ChatGPT Clone
* Linear Clone
* 三栏 SaaS Dashboard

首页必须重点借鉴 Codrops：

**Building an Infinite Liquid Glass Grid with Three.js, WebGPU, and TSL**

并在其基础上做成适用于邮件 Requirement Workbench 的高级版本。

---

# 2. Target User

第一版只有一个用户：

**Owner / Me**

不考虑：

* 多用户
* Team Workspace
* RBAC
* 公司账号体系
* 管理员
* SSO

应用运行在自己的 Mac 上。

不需要应用登录页面。

---

# 3. Core Product Principle

AI 的行为原则：

> 主动干活，但不要自作主张。

AI 可以：

* 阅读邮件正文
* 理解上下文
* 判断邮件意图
* 提取 Requirement
* 判断信息是否完整
* 发现模糊点
* 发现简单冲突
* 向我提问
* 整理 Requirement
* 生成回复
* 自动回复允许回复的邮件

AI 不应该：

* 猜测未知信息
* 编造 Deadline
* 编造 Scope
* 编造 Business Goal
* 擅自承诺技术可行性
* 擅自承诺成本
* 擅自承诺交付时间
* 擅自理解附件
* 进行非常复杂的需求推理
* 把简单 Requirement Analysis 做成复杂多 Agent 系统

整体 AI 性格应该像：

**谨慎、可靠、执行力强的初级 Business Analyst / AI Employee。**

---

# 4. Primary Workflow

完整流程：

```text
Receive Email
      ↓
Email appears in Workbench
      ↓
AI reads email body + thread
      ↓
User may mark:
DO NOT REPLY
      ↓
AI identifies intent
      ↓
Is this related to a requirement?
      ↓
Extract known information
      ↓
Update Requirement State
      ↓
Check missing / ambiguous information
      ↓
Need clarification?
   ↙             ↘
 YES              NO
 ↓                 ↓
Ask Me          Generate Requirement
 ↓                 ↓
My Answer       Generate Reply
 ↓                 ↓
Update State    Auto Reply
 ↓
Continue Analysis
```

---

# 5. Email Behaviour

## 5.1 Mailbox

第一版邮件 Provider 不需要绑定死 Gmail。

设计统一接口：

```text
MailProvider
```

后续可以实现：

```text
GmailProvider
OutlookProvider
IMAPProvider
MockProvider
```

Demo 必须首先可以通过 MockProvider 完整运行。

如果配置真实邮箱 Provider，则可以真实接收和发送邮件。

---

# 6. Automatic Reply

系统支持：

```text
AUTO REPLY: ON / OFF
```

默认可以开启 Auto Reply。

当 Auto Reply 开启时：

AI 可以自动发送回复。

但必须支持：

```text
DO NOT REPLY
```

用户可以：

* 对单封邮件禁止回复
* 对整个 Thread 禁止回复

状态示例：

```text
AUTO REPLY
DO NOT REPLY
WAITING FOR ME
REPLIED
NO ACTION
```

如果标记为：

```text
DO NOT REPLY
```

AI 永远不能给该 Thread 发送邮件。

---

# 7. Clarification Behaviour

当 Requirement 信息不完整时：

**AI 优先问我。**

而不是自动向邮件发送者追问。

例如：

邮件：

> We need a dashboard to monitor application performance.

AI 提取：

```text
Goal:
Monitor application performance

Users:
Unknown

Metrics:
Unknown

Deadline:
Unknown

Data Source:
Unknown
```

然后右侧 AI Employee 问：

```text
Who is this dashboard for?
```

我回答：

```text
Operations team.
```

系统仅更新：

```json
{
  "users": ["Operations Team"]
}
```

然后继续：

```text
What metrics should the dashboard include?
```

AI 每次优先问：

**当前最重要的一个问题。**

不要一次弹出十几个问题。

---

# 8. Requirement State

Requirement 必须维护结构化 State。

不能每次重新生成整篇 Markdown。

建议数据：

```json
{
  "id": "",
  "title": "",
  "requester": "",
  "background": "",
  "business_problem": "",
  "goal": "",
  "stakeholders": [],
  "users": [],
  "scope": [],
  "out_of_scope": [],
  "functional_requirements": [],
  "non_functional_requirements": [],
  "constraints": [],
  "dependencies": [],
  "data_sources": [],
  "deadline": null,
  "priority": null,
  "acceptance_criteria": [],
  "assumptions": [],
  "open_questions": [],
  "risks": [],
  "status": "",
  "completeness": 0
}
```

字段允许为空。

AI 不得为了“填完整”而生成不存在的信息。

---

# 9. Requirement Output

最终主要输出：

**Markdown**

格式：

```markdown
# Requirement Title

## Background

## Business Problem

## Goal

## Stakeholders

## Users

## Scope

## Out of Scope

## Functional Requirements

### FR-001
...

### FR-002
...

## Non-functional Requirements

### NFR-001
...

## Constraints

## Dependencies

## Data Sources

## Deadline

## Priority

## Acceptance Criteria

### AC-001
...

## Assumptions

## Risks

## Open Questions
```

支持：

```text
Copy Markdown
Download .md
```

第一版不需要：

* Word
* PDF
* PowerPoint
* Jira Export

---

# 10. Multiple Emails → One Requirement

一个 Requirement 可以来自：

* 多封邮件
* 同一个 Thread
* 多轮回复
* 不同时间收到的信息

AI 应持续更新现有 Requirement。

例如：

```text
Email 1
↓
Requirement 40%

Email 2
↓
Requirement 55%

My Answer
↓
Requirement 72%

Email Reply
↓
Requirement 90%
```

不能每收到新邮件就重新创建一个 Requirement。

---

# 11. Lightweight Requirement Review

AI 可以进行简单的 Requirement Challenge。

但只通过 Prompt 实现。

不要：

* 多 Agent Debate
* Knowledge Graph
* Rule Engine
* 大型 Requirement Validation Framework

允许 AI 判断：

```text
Missing Information
Ambiguous Information
Simple Conflict
Potential Risk
Unknown Feasibility
```

例如：

```text
⚠ Deadline is unclear

⚠ "Real-time" is mentioned but no refresh interval is defined

⚠ Scope appears to conflict with previous email

⚠ Technical feasibility has not been confirmed
```

复杂情况：

```text
Ask Me
```

不要自行展开复杂推理。

---

# 12. Attachments

邮件附件需要正常显示。

例如：

```text
Attachments

📄 requirement.pdf
📊 data.xlsx
📝 proposal.docx
🖼 screenshot.png
```

支持：

```text
Open
Download
Save
```

但是：

**AI 第一版禁止读取附件内容。**

附件不得：

* 自动解析
* 自动 OCR
* 自动进入 DeepSeek
* 自动进入 Requirement Context

AI 只能知道：

```text
Attachment exists
filename
file type
file size
```

UI 可以提醒：

```text
This email contains attachments.
Attachments are not included in AI analysis.
```

---

# 13. AI Model

第一版：

**DeepSeek**

必须建立：

```text
LLMProvider
```

而不是把 DeepSeek API 调用散落在业务代码里。

例如：

```text
LLMProvider
├── analyzeEmail()
├── extractRequirement()
├── updateRequirement()
├── detectMissingInformation()
├── askClarification()
├── generateMarkdown()
└── generateReply()
```

实现：

```text
DeepSeekProvider
MockProvider
```

未来才能方便替换其他模型。

---

# 14. AI System Personality

AI Employee 的 System Prompt 核心：

```text
You are a careful junior business analyst working for the user.

Your job is to help the user process emails and turn unclear requests into accurate requirements.

Be proactive in execution but conservative in assumptions.

Never invent missing facts.

If important information is unknown, ask the user.

Prefer one high-value clarification question at a time.

Do not over-engineer simple requirements.

Do not promise deadlines, cost, scope, resources, or technical feasibility unless explicitly confirmed.

When updating a requirement, preserve existing confirmed information.

Distinguish clearly between:
- confirmed information
- inferred information
- missing information
- assumptions

Your goal is not to sound intelligent.
Your goal is to be reliable.
```

---

# 15. Main UX Concept

产品不应该一打开就是普通 Inbox。

打开应用后首先进入：

# Infinite Requirement Workspace

这里是整个产品最重要的视觉体验。

每个 Requirement / Email Thread 是一个：

**Liquid Glass Object / Card**

漂浮在一个可以拖动探索的无限空间里。

用户的感觉应该是：

> 我的所有工作和需求漂浮在一个数字工作空间里，而不是排在一个普通列表里。

---

# 16. Frontend Reference — Hard Requirement

视觉必须重点借鉴 Codrops Infinite Liquid Glass Grid。

技术方向：

```text
Next.js
React
TypeScript

Three.js
React Three Fiber
WebGPU
TSL
Motion
```

不是只做：

```css
backdrop-filter: blur(...)
```

然后称之为 Liquid Glass。

必须真正有：

* 3D spatial layout
* shader-based glass
* refraction
* edge highlights
* depth
* perspective
* drag inertia
* infinite wrapping
* sphere-based spatial curvature

---

# 17. Infinite Spatial Grid

首页卡片不应该位于传统二维 Grid。

视觉上建立一个巨大的：

**Curved Infinite Surface**

卡片：

中央：

```text
front-facing
larger
clearer
```

越靠边：

```text
slightly rotated
slightly smaller
slightly farther away
```

产生：

```text
depth
spatial curvature
infinite workspace
```

效果。

实际卡片数量保持有限。

卡片离开一侧后：

从另外一侧重新出现。

形成：

**Fake Infinite Grid**

禁止真正创建无限 DOM。

---

# 18. Liquid Glass Material

Requirement Card 使用：

**custom shader liquid glass**

每张卡本质可以只是：

```text
subdivided flat plane
```

通过 Shader 制造：

```text
rounded surface
bevel
thickness
refraction
dispersion
fresnel reflection
rim highlight
glass distortion
```

优先：

```text
TSL
MeshBasicNodeMaterial
SDF
```

而不是大量真实透明几何体。

---

# 19. Advanced Version

不要简单复制参考 Demo。

在它之上加入 Requirement Workbench 自己的状态表达。

例如卡片内部：

```text
PRODUCT ANALYTICS DASHBOARD

Alice Chen

NEED CLARIFICATION

72%

3 unread
2 questions

Last update
4m ago
```

玻璃边缘和环境光可以轻微根据状态变化。

但禁止过度使用高饱和颜色。

---

# 20. Real HTML Text

重要文字必须保持：

**真实 HTML。**

包括：

* Requirement Title
* Sender
* Status
* Percentage
* Time
* Email Subject

不能全部变成 Canvas Texture。

原因：

* 清晰
* 可选择
* Accessibility
* 高 DPI
* 浏览器原生字体渲染

视觉上 HTML 必须精确跟随 3D Card。

---

# 21. Zero React Rerender Dragging

拖拽 Infinite Workspace 时：

不能每个 pointer movement 都更新 React State。

使用：

```text
Motion Value
R3F Frame Loop
refs
direct transform update
```

来处理：

```text
position
velocity
camera
card transformation
```

目标：

拖拽过程尽量：

```text
0 React rerenders
```

---

# 22. Card Interaction

鼠标 Hover：

```text
subtle scale
glass highlight
depth movement
soft reflection change
```

点击：

卡片不能直接：

```text
window.location → boring page
```

必须有空间 Transition。

---

# 23. Enter Requirement Transition

点击 Requirement：

```text
Card selected
      ↓
Nearby cards move away
      ↓
Selected card moves toward camera
      ↓
Card expands
      ↓
Perspective gradually flattens
      ↓
Liquid Glass card transforms into Workbench
```

形成：

> “进入这个 Requirement”

的感觉。

这是核心动画。

---

# 24. Detailed Workbench

进入 Requirement 后：

视觉从：

```text
Experimental / Spatial
```

转为：

```text
Focused / Productive
```

不要继续所有内容都用 3D。

主要工作区域使用正常 DOM。

建议布局：

```text
┌──────────────────────────────────────────────────────────────┐
│ ← Workspace      Requirement Name           AUTO REPLY ●    │
├───────────────┬─────────────────────────┬────────────────────┤
│               │                         │                    │
│ THREAD        │ EMAIL                   │ AI EMPLOYEE        │
│               │                         │                    │
│ Alice         │ From Alice              │ Requirement 72%    │
│ Yesterday     │                         │                    │
│               │ We need...              │ ✓ Goal             │
│ You           │                         │ ✓ Users            │
│ Today         │ Attachments             │ ✕ Deadline         │
│               │ proposal.pdf            │                    │
│               │                         │ AI asks:           │
│               │                         │                    │
│               │                         │ When should this    │
│               │                         │ be delivered?       │
│               │                         │                    │
│               │                         │ [ answer... ]       │
└───────────────┴─────────────────────────┴────────────────────┘
```

---

# 25. Right Panel — AI Employee

这是工作台灵魂。

不应该只是一个 ChatGPT 对话框。

显示：

## Requirement Completeness

```text
72%

████████████████░░░░
```

## Known

```text
✓ Business Goal
✓ User
✓ Main Function
```

## Missing

```text
○ Deadline
○ Acceptance Criteria
```

## Risks

```text
⚠ Scope unclear
```

## AI Question

```text
When should this feature be available?
```

输入：

```text
September 30
```

系统实时更新 Requirement。

---

# 26. AI Presence

AI 应该像：

**坐在右边认真帮我工作的员工。**

而不是：

“Ask me anything!”

避免：

* 大量 AI 营销文案
* Emoji
* 过度人格化
* AI Avatar
* 虚拟人物动画

AI 的高级感来自：

**它真的把事情做好。**

---

# 27. Requirement Document View

右侧可以切换：

```text
AI
Requirement
```

Requirement 页面显示实时 Markdown。

例如：

```text
AI | Requirement
```

选择 Requirement：

直接查看当前完整 Requirement。

---

# 28. UI Visual Language

整体：

```text
Dark
Premium
Spatial
Minimal
Dense
Quiet
High-end
```

背景：

接近黑色但不是纯黑。

加入：

* very slow light movement
* subtle environmental gradients
* subtle grain
* soft depth
* glass refraction

禁止：

* 大面积紫色渐变
* Cyberpunk
* Neon dashboard
* 过度 Glow
* 典型 AI SaaS 风格

---

# 29. Performance

这是工作工具，不是纯视觉 Demo。

GPU 效果不能损害使用。

不要实现参考文章后期加入的复杂：

```text
XPBD cloth simulation
```

第一版不需要。

使用：

```text
fake liquid glass
SDF
single-pass shader
pooled cards
WebGPU
```

即可。

---

# 30. Fallback

如果 WebGPU 不可用：

自动切换：

```text
CSS Glass + 2D Spatial Grid
```

所有业务功能必须正常。

不能：

```text
WebGPU unavailable → app unusable
```

---

# 31. Reduced Motion

支持：

```text
prefers-reduced-motion
```

减少：

* inertia
* spatial movement
* refraction animation
* transition duration

---

# 32. Suggested Architecture

```text
requirement-workbench/

frontend/
  app/

  components/

    spatial/
      InfiniteWorkspace.tsx
      SpatialCard.tsx
      SpatialCamera.tsx
      LiquidGlassMaterial.ts
      CardHtmlOverlay.tsx
      WorkspaceTransition.tsx

    workbench/
      WorkbenchShell.tsx
      ThreadPanel.tsx
      EmailPanel.tsx
      AIEmployeePanel.tsx
      RequirementView.tsx
      AttachmentList.tsx
      ReplyStatus.tsx

    glass/
      GlassPanel.tsx
      GlassButton.tsx
      GlassInput.tsx

backend/

  app/
    main.py

    api/
      mail.py
      requirements.py
      ai.py

    models/
      email.py
      requirement.py

    services/
      mail_service.py
      requirement_service.py
      ai_service.py

    providers/
      mail/
        base.py
        mock.py
        gmail.py

      llm/
        base.py
        mock.py
        deepseek.py

    database/
      database.py
```

---

# 33. Database

第一版 SQLite。

至少保存：

```text
email_threads
emails
requirements
clarification_messages
reply_log
settings
attachments
```

不做复杂 Requirement Version History。

只保存当前 Requirement 即可。

---

# 34. Demo Data

提供至少 10 个 Mock Thread。

类型包括：

```text
Dashboard Request
AI Automation
Excel Automation
Data Analysis
Internal Tool
Report Generation
Workflow Automation
Bug Fix
Feature Request
Simple Non-requirement Email
```

故意让部分邮件：

```text
完整
不完整
模糊
存在轻微冲突
带附件
无需回复
```

用于展示完整产品能力。

---

# 35. Demo Must Demonstrate

Demo 最少必须能完整演示：

```text
Open App
↓
Beautiful Infinite Liquid Glass Workspace
↓
Drag Workspace
↓
Select Requirement
↓
Spatial Enter Animation
↓
Read Email
↓
See Attachment
↓
AI Extracts Requirement
↓
AI Detects Missing Information
↓
AI Asks Me
↓
I Answer
↓
Requirement Updates
↓
Markdown Generated
↓
AI Generates Reply
↓
Auto Reply Simulation
↓
Return to Infinite Workspace
```

---

# 36. Out of Scope — Demo

暂时不要做：

* Multi-user
* Authentication
* RBAC
* Teams
* SSO
* Attachment AI Parsing
* OCR
* Vector Database
* RAG
* Knowledge Base
* Multi-Agent
* Complex Workflow Engine
* Requirement Version Control
* Jira Integration
* Slack Integration
* Calendar
* Word Export
* PDF Export
* Mobile App
* Mobile-first UI

不要因为“以后可能需要”提前实现。

---

# 37. Acceptance Criteria

Demo 完成必须满足：

### AC-001

启动后不是传统 Inbox，而是 Infinite Liquid Glass Workspace。

### AC-002

视觉效果能够明确看出参考了 Codrops Infinite Liquid Glass Grid，而不是普通 CSS Glassmorphism。

### AC-003

Workspace 可以流畅拖动并形成无限空间感。

### AC-004

卡片具有明显但克制的 Liquid Glass Shader 效果。

### AC-005

Requirement 卡片文字始终清晰。

### AC-006

点击卡片存在完整的空间进入动画。

### AC-007

可以查看完整邮件 Thread。

### AC-008

可以显示附件并打开/下载，但 AI 不读取附件。

### AC-009

DeepSeek 能从邮件正文提取结构化 Requirement。

### AC-010

未知字段保持 Unknown / Empty，不允许 AI 编造。

### AC-011

AI 可以发现 Requirement 缺失信息。

### AC-012

AI 每次优先向用户询问一个最重要的问题。

### AC-013

用户回答后，只更新相关 Requirement State。

### AC-014

可以实时生成 Markdown Requirement。

### AC-015

能够生成邮件回复。

### AC-016

支持 Auto Reply。

### AC-017

支持单邮件或 Thread 的 DO NOT REPLY。

### AC-018

被设置为 DO NOT REPLY 的 Thread 绝不能自动发送。

### AC-019

应用能在个人 Mac 本地运行。

### AC-020

不需要应用账号登录。

---

# 38. Implementation Priority

开发顺序必须按照：

```text
1. Infinite Liquid Glass frontend prototype

2. Requirement detail transition

3. Workbench UI

4. Mock mailbox

5. RequirementState

6. Mock AI flow

7. DeepSeek integration

8. Auto Reply state machine

9. Markdown generation

10. Optional real mailbox adapter
```

第一阶段不要先浪费时间处理 Gmail OAuth。

先把：

> **惊艳的产品壳 + 完整 Requirement 工作流**

做出来。

---

# 39. Final Product Definition

这个产品不是：

**AI Email Client**

也不是：

**AI Requirement Generator**

而是：

# AI Requirement Workbench

邮件只是任务进入系统的入口。

AI Employee 负责把模糊的邮件不断推进成可以执行的 Requirement。

最终体验应该形成鲜明反差：

### 外部

一个高级、空间化、Liquid Glass 的未来工作台。

### 内部

一个安静、谨慎、不会乱做决定的 AI 员工。

**Fancy workspace outside. Reliable employee inside.**

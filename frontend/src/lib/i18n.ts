import type { ThreadStatus } from './api';

export const STATUS_LABELS: Record<ThreadStatus, string> = {
  waiting_for_me: '等待你的补充',
  ready: '可以回复',
  replied: '已回复',
  no_action: '无需处理',
  do_not_reply: '禁止回复',
};

export const STATUS_HELP: Record<ThreadStatus, string> = {
  waiting_for_me: '下一步需要你确认一项信息。',
  ready: '需求信息已足够，可以进行回复操作。',
  replied: '这条线程已有回复记录。',
  no_action: '这条线程不需要回复。',
  do_not_reply: '这条线程已禁止回复。',
};

export function isMockMailProvider(mailProvider: string): boolean {
  return mailProvider.trim().toLowerCase() === 'mock';
}

export function outboundMailLabel(mailProvider: string): string {
  return isMockMailProvider(mailProvider) ? '模拟发送' : '真实邮件已发送';
}

export function replyActionLabel(mailProvider: string, busy = false): string {
  if (isMockMailProvider(mailProvider)) return busy ? '正在模拟回复……' : '模拟回复';
  return busy ? '正在发送邮件……' : '发送邮件';
}

export function replyStatusLabel(status: string, mailProvider: string): string {
  switch (status.trim().toLowerCase()) {
    case 'sent':
      return isMockMailProvider(mailProvider) ? '模拟发送完成' : '真实邮件已发送';
    case 'sending':
      return '正在发送，请稍后刷新确认';
    case 'uncertain':
      return '发送结果待确认';
    case 'simulated':
      return '模拟发送完成';
    case 'delivered':
      return '邮件已送达';
    case 'recorded':
      return '仅记录，未发送';
    default:
      return '已记录';
  }
}

export function errorLabel(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : '';
  if (!message) return fallback;
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return '无法连接本地服务，请确认后端已启动。';
  }

  const mailError = message.match(/^Mail provider error:\s*(.*)$/i)?.[1] ?? '';
  if (mailError) {
    if (/send result is unknown|check the sent mailbox/i.test(mailError)) return '邮件发送结果无法确认，请先查看邮箱发件箱，再选择确认结果。';
    if (/SMTP send failed/i.test(mailError)) return 'SMTP 发送请求异常，结果待确认，请先核对邮箱发件箱。';
    if (/SMTP configuration is incomplete/i.test(mailError)) return 'SMTP 配置不完整，请检查后端邮箱设置；本次发送结果仍需核对发件箱。';
    if (/Mailbox configuration is incomplete/i.test(mailError)) return '邮箱同步失败：IMAP 配置不完整，请检查后端邮箱设置。';
    if (/Mailbox sync failed/i.test(mailError)) return '邮箱同步失败，请检查 IMAP 地址、端口、账号和密码。';
    if (/Unsupported mail provider/i.test(mailError)) return '当前邮箱服务配置不受支持，请检查后端邮箱设置。';
    return '邮箱服务调用失败，请检查邮箱配置。';
  }
  if (/^LLM provider error:/i.test(message)) return '智能助手调用失败，请检查模型服务配置与网络连接。';

  const apiErrors: Array<[RegExp, string]> = [
    [/^Thread is marked DO NOT REPLY$/i, '这条线程已设置禁止回复。'],
    [/^An email in this thread is marked DO NOT REPLY$/i, '这条线程中的邮件已设置禁止回复。'],
    [/^Answer the pending question before replying$/i, '请先回答待确认问题，再发送回复。'],
    [/^This thread does not require a reply$/i, '这条线程无需回复。'],
    [/^Requirement is not ready to reply$/i, '需求信息尚未达到回复条件。'],
    [/^Duplicate reply blocked$/i, '系统已阻止重复发送。'],
    [/^A reply is already in progress for this thread$/i, '这条线程的回复正在处理中。'],
    [/^A reply was already sent for this thread$/i, '这条线程已有回复，无法重复发送。'],
    [/^Confirm whether the previous reply was delivered before sending again$/i, '上一封邮件的发送结果待确认，请先核对发件箱。'],
    [/^No uncertain reply is waiting for confirmation$/i, '当前没有待确认的发送记录，请刷新线程。'],
    [/^Demo threads cannot be sent through a real mailbox$/i, '真实邮箱模式不能发送演示线程，请先同步真实邮件。'],
    [/^This thread no longer has the question you answered$/i, '待确认问题已发生变化，请重新加载后再回答。'],
    [/^The pending question changed; reload before answering$/i, '待确认问题已发生变化，请重新加载后再回答。'],
    [/^Answer cannot be empty$/i, '请先填写答案。'],
    [/^Reply provider returned an empty body$/i, '未能生成回复内容，请重新尝试。'],
    [/^Thread not found$/i, '未找到这条线程。'],
    [/^Email not found$/i, '未找到这封邮件。'],
    [/^Requirement not found$/i, '未找到需求记录。'],
    [/^Settings are not initialized$/i, '工作台设置尚未初始化，请检查后端配置。'],
  ];
  for (const [pattern, label] of apiErrors) {
    if (pattern.test(message)) return label;
  }

  const requestFailure = message.match(/^Request failed \((\d{3})\)$/i);
  if (requestFailure) return `请求失败（${requestFailure[1]}），请稍后重试。`;
  return fallback;
}

const CATEGORY_LABELS: Record<string, string> = {
  requirement: '需求',
  no_action: '无需处理',
  NO_ACTION: '无需处理',
  REQUIREMENT: '需求',
  THREAD: '线程',
  ANALYTICS: '数据分析',
  OPERATIONS: '运营',
  PRODUCT: '产品',
  FINANCE: '财务',
  CUSTOMER: '客户',
  BRAND: '品牌',
  PLATFORM: '平台',
  RESEARCH: '研究',
  DATA_ANALYSIS: '数据分析',
  AUTOMATION: '自动化',
  INTERNAL_TOOL: '内部工具',
  REPORT: '报告',
  WORKFLOW: '工作流',
};

const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  requester: '提出人',
  background: '背景',
  business_problem: '业务问题',
  goal: '业务目标',
  stakeholders: '相关方',
  users: '使用者',
  scope: '范围',
  out_of_scope: '范围外',
  functional_requirements: '主要功能',
  non_functional_requirements: '非功能要求',
  constraints: '约束条件',
  dependencies: '依赖项',
  data_sources: '数据来源',
  deadline: '截止时间',
  priority: '优先级',
  acceptance_criteria: '验收标准',
  assumptions: '假设',
  open_questions: '待确认问题',
  risks: '风险',
  status: '状态',
  completeness: '完成度',
};

export function categoryLabel(category: string | null | undefined): string {
  const value = category?.trim();
  if (!value) return '需求';
  return CATEGORY_LABELS[value] ?? CATEGORY_LABELS[value.toUpperCase()] ?? '其他';
}

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? '其他字段';
}

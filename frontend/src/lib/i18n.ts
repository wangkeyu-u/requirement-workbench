import type { ThreadStatus } from './api';

export const STATUS_LABELS: Record<ThreadStatus, string> = {
  waiting_for_me: '等待你的补充',
  ready: '可以生成回复',
  replied: '已回复',
  no_action: '无需处理',
  do_not_reply: '禁止回复',
};

export const STATUS_HELP: Record<ThreadStatus, string> = {
  waiting_for_me: '下一步需要你确认一项信息。',
  ready: '需求信息已经足够，可以生成回复。',
  replied: '这条线程已经记录了一次模拟回复。',
  no_action: '这条线程不需要回复。',
  do_not_reply: '这条线程已禁止回复。',
};

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

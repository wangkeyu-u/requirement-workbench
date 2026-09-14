'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from 'react';
import {
  api,
  type Attachment,
  type Email,
  type Requirement,
  type Settings,
  type ThreadDetail,
  type ThreadStatus,
} from '../../lib/api';
import { categoryLabel, fieldLabel, STATUS_HELP, STATUS_LABELS } from '../../lib/i18n';
import styles from './WorkbenchShell.module.css';

export interface WorkbenchShellProps {
  threadId: string;
  onClose: () => void;
  onUpdated?: () => void;
}

type ViewMode = 'ai' | 'requirement';
type ActionKey = 'analyze' | 'answer' | 'reply' | 'thread-guard' | 'email-guard' | 'settings';

const SIGNAL_FIELDS: Array<{
  key: keyof Requirement;
  label: string;
}> = [
  { key: 'goal', label: '业务目标' },
  { key: 'users', label: '使用者' },
  { key: 'scope', label: '范围' },
  { key: 'functional_requirements', label: '主要功能' },
  { key: 'acceptance_criteria', label: '验收标准' },
  { key: 'deadline', label: '截止时间' },
  { key: 'data_sources', label: '数据来源' },
];

function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : '';
  if (/failed to fetch|networkerror|load failed/i.test(message)) return '无法连接本地服务，请确认后端已启动。';
  return message || '连接本地工作台时发生错误。';
}

function hasContent(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some((item) => hasContent(item));
  }

  if (typeof value !== 'string') return value !== null && value !== undefined;

  const normalized = value.trim().toLowerCase();
  return Boolean(normalized) && !['unknown', 'tbd', 'n/a', 'not provided', 'not specified'].includes(normalized);
}

function getDefaultEmailId(emails: Email[]): string {
  const inbound = emails.filter((email) => email.direction === 'inbound');
  return (inbound[inbound.length - 1] ?? emails[emails.length - 1])?.id ?? '';
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'Asia/Shanghai',
  }).format(date);
}

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '大小未知';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function replyStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    sent: '已发送',
    simulated: '已模拟',
    delivered: '已送达',
    recorded: '已记录',
  };
  return labels[status.toLowerCase()] ?? '已记录';
}

function initials(value: string): string {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '—';
  return parts.slice(0, 2).map((part) => part[0]).join('').toUpperCase();
}

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  return slug || 'requirement';
}

function StatusPill({ status }: { status: ThreadStatus }) {
  return (
    <span className={`${styles.statusPill} ${styles[`status_${status}`]}`}>
      <span className={styles.statusDot} aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  );
}

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.65,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };

  switch (name) {
    case 'arrow-left':
      return <svg {...common}><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></svg>;
    case 'arrow-up-right':
      return <svg {...common}><path d="M7 17 17 7" /><path d="M7 7h10v10" /></svg>;
    case 'check':
      return <svg {...common}><path d="m5 12 4.2 4.2L19 6.5" /></svg>;
    case 'chevron-down':
      return <svg {...common}><path d="m6 9 6 6 6-6" /></svg>;
    case 'clipboard':
      return <svg {...common}><rect x="6" y="5" width="12" height="15" rx="2" /><path d="M9 5.5V4h6v1.5" /><path d="M9.5 10h5" /><path d="M9.5 13.5h5" /></svg>;
    case 'download':
      return <svg {...common}><path d="M12 4v10" /><path d="m8 10 4 4 4-4" /><path d="M5 19h14" /></svg>;
    case 'file':
      return <svg {...common}><path d="M7 3.8h7l3.5 3.5V20H7z" /><path d="M14 3.8v4h3.5" /><path d="M9.5 12h5" /><path d="M9.5 15h5" /></svg>;
    case 'mail':
      return <svg {...common}><rect x="3.5" y="5.5" width="17" height="13" rx="2" /><path d="m4.5 7 7.5 6 7.5-6" /></svg>;
    case 'paperclip':
      return <svg {...common}><path d="m8.5 12.5 5.7-5.7a3 3 0 0 1 4.2 4.2l-7.2 7.2a4.5 4.5 0 0 1-6.4-6.4l7.1-7.1" /></svg>;
    case 'refresh':
      return <svg {...common}><path d="M20 11a8 8 0 0 0-14.7-4L4 9" /><path d="M4 4v5h5" /><path d="M4 13a8 8 0 0 0 14.7 4L20 15" /><path d="M20 20v-5h-5" /></svg>;
    case 'send':
      return <svg {...common}><path d="m21 3-7.2 18-3.8-7-7-3.8z" /><path d="M21 3 10 14" /></svg>;
    case 'shield':
      return <svg {...common}><path d="M12 3 19 6v5.5c0 4.5-3 7.8-7 9.5-4-1.7-7-5-7-9.5V6z" /><path d="m9.5 12 1.7 1.7 3.7-3.7" /></svg>;
    case 'spark':
      return <svg {...common}><path d="m12 3 1.3 5.7L19 10l-5.7 1.3L12 17l-1.3-5.7L5 10l5.7-1.3z" /><path d="m19 15 .5 2.5L22 18l-2.5.5L19 21l-.5-2.5L16 18l2.5-.5z" /></svg>;
    case 'external':
      return <svg {...common}><path d="M14 5h5v5" /><path d="m19 5-8 8" /><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" /></svg>;
    case 'x':
      return <svg {...common}><path d="m6 6 12 12" /><path d="m18 6-12 12" /></svg>;
    default:
      return null;
  }
}

type IconName =
  | 'arrow-left'
  | 'arrow-up-right'
  | 'check'
  | 'chevron-down'
  | 'clipboard'
  | 'download'
  | 'external'
  | 'file'
  | 'mail'
  | 'paperclip'
  | 'refresh'
  | 'send'
  | 'shield'
  | 'spark'
  | 'x';

function PanelLabel({ children, trailing }: { children: ReactNode; trailing?: ReactNode }) {
  return (
    <div className={styles.panelLabel}>
      <span>{children}</span>
      {trailing ? <span className={styles.panelLabelTrailing}>{trailing}</span> : null}
    </div>
  );
}

function Toggle({ checked, disabled, label, onChange }: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      className={`${styles.toggle} ${checked ? styles.toggleOn : ''}`}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
    >
      <span className={styles.toggleKnob} />
    </button>
  );
}

function LoadingState({ label = '正在加载工作台' }: { label?: string }) {
  return (
    <div className={styles.stateCard} role="status" aria-live="polite">
      <div className={styles.loaderOrbit} aria-hidden="true"><span /></div>
      <div>
        <p className={styles.stateKicker}>本地工作台</p>
        <h2>{label}</h2>
        <p className={styles.stateCopy}>正在从本地服务读取最新线程状态。</p>
      </div>
    </div>
  );
}

function ErrorState({ message, onRetry, onClose }: { message: string; onRetry: () => void; onClose: () => void }) {
  return (
    <section className={styles.shell} aria-label="需求工作台错误">
      <div className={styles.stateTopbar}>
        <button className={styles.iconButton} type="button" onClick={onClose} aria-label="返回工作台">
          <Icon name="arrow-left" />
        </button>
        <div>
          <p className={styles.eyebrow}>需求工作台 / 本地服务</p>
          <h1>无法打开这条线程</h1>
        </div>
      </div>
      <div className={styles.stateWrap}>
        <div className={styles.stateCard} role="alert">
          <div className={styles.errorMark}>!</div>
          <div>
            <p className={styles.stateKicker}>加载失败</p>
            <h2>没有修改任何内容。</h2>
            <p className={styles.stateCopy}>{message}</p>
            <button className={styles.primaryButton} type="button" onClick={onRetry}>
              <Icon name="refresh" size={16} />
              重试连接
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function AttachmentList({ attachments, onOpen, onDownload }: {
  attachments: Attachment[];
  onOpen: (attachment: Attachment) => void;
  onDownload: (attachment: Attachment) => void;
}) {
  if (!attachments.length) return null;

  return (
    <section className={styles.attachmentSection} aria-labelledby="attachments-heading">
      <div className={styles.attachmentHeading}>
        <div>
          <p className={styles.subLabel} id="attachments-heading">附件 <span>{String(attachments.length).padStart(2, '0')}</span></p>
        </div>
        <Icon name="paperclip" size={16} />
      </div>
      <div className={styles.attachmentList}>
        {attachments.map((attachment) => (
          <div className={styles.attachmentRow} key={attachment.id}>
            <div className={styles.fileIcon}><Icon name="file" size={18} /></div>
            <div className={styles.attachmentMeta}>
              <span className={styles.attachmentName}>{attachment.filename}</span>
              <span className={styles.attachmentSize}>{attachment.content_type} · {formatFileSize(attachment.size)}</span>
            </div>
            <div className={styles.attachmentActions}>
              <button type="button" className={styles.inlineButton} onClick={() => onOpen(attachment)}>
                <Icon name="external" size={14} />
                打开
              </button>
              <button type="button" className={styles.inlineButton} onClick={() => onDownload(attachment)}>
                <Icon name="download" size={14} />
                下载
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ThreadRail({
  detail,
  selectedEmailId,
  onSelect,
}: {
  detail: ThreadDetail;
  selectedEmailId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className={`${styles.panel} ${styles.threadPanel}`} aria-label="邮件线程">
      <div className={styles.panelHeader}>
        <PanelLabel trailing={`${detail.emails.length} 条消息`}>邮件线程</PanelLabel>
      </div>

      <div className={styles.threadMeta}>
        <div className={styles.threadMetaTop}>
          <span className={styles.categoryTag}>{categoryLabel(detail.thread.category)}</span>
          {detail.thread.unread_count > 0 ? <span className={styles.unreadTag}>{detail.thread.unread_count} 条未读</span> : null}
        </div>
        <h2>{detail.thread.title}</h2>
        <p>{detail.thread.preview}</p>
      </div>

      <div className={styles.emailTimeline}>
        {detail.emails.map((email, index) => {
          const selected = email.id === selectedEmailId;
          return (
            <button
              type="button"
              className={`${styles.emailItem} ${selected ? styles.emailItemActive : ''}`}
              key={email.id}
              onClick={() => onSelect(email.id)}
              aria-current={selected ? 'true' : undefined}
            >
              <span className={styles.timelineRail} aria-hidden="true"><span /></span>
              <span className={styles.emailItemMain}>
                <span className={styles.emailItemTopline}>
                  <span className={styles.emailDirection}>{email.direction === 'outbound' ? '你' : `消息 ${String(index + 1).padStart(2, '0')}`}</span>
                  <span className={styles.emailTime}>{formatDate(email.received_at)}</span>
                </span>
                <strong>{email.direction === 'outbound' ? '你' : email.sender}</strong>
                <span className={styles.emailSubject}>{email.subject}</span>
                <span className={styles.emailItemFooter}>
                  <span>{email.direction === 'outbound' ? '已发送回复' : email.sender_email}</span>
                  {email.attachments.length ? <span className={styles.attachmentCount}><Icon name="paperclip" size={12} />{email.attachments.length}</span> : null}
                  {email.do_not_reply ? <span className={styles.guardBadge}><Icon name="shield" size={12} /> 已禁止回复</span> : null}
                </span>
              </span>
              <span className={styles.itemChevron}><Icon name="arrow-up-right" size={14} /></span>
            </button>
          );
        })}
      </div>

      <div className={styles.threadRailFooter}>
        <span className={styles.footerRule} />
        <span>当前状态</span>
        <span className={styles.footerRule} />
      </div>
      <div className={styles.threadStatusSummary}>
        <StatusPill status={detail.thread.status} />
        <span>{STATUS_HELP[detail.thread.status]}</span>
      </div>
    </aside>
  );
}

function EmailPanel({
  email,
  onToggleNoReply,
  onOpenAttachment,
  onDownloadAttachment,
  busy,
}: {
  email: Email | undefined;
  onToggleNoReply: (email: Email) => void;
  onOpenAttachment: (attachment: Attachment) => void;
  onDownloadAttachment: (attachment: Attachment) => void;
  busy: boolean;
}) {
  if (!email) {
    return (
      <section className={`${styles.panel} ${styles.emailPanel} ${styles.emptyPanel}`} aria-label="邮件">
        <div className={styles.emptyPanelInner}>
          <div className={styles.emptyIcon}><Icon name="mail" size={22} /></div>
          <p className={styles.subLabel}>未选择消息</p>
          <p>请从线程中选择一条消息，查看完整内容。</p>
        </div>
      </section>
    );
  }

  const senderLabel = email.direction === 'outbound' ? '你' : email.sender;

  return (
    <section className={`${styles.panel} ${styles.emailPanel}`} aria-label="邮件详情">
      <div className={styles.panelHeader}>
        <PanelLabel trailing={email.direction === 'outbound' ? '发出' : '收到'}>邮件</PanelLabel>
      </div>

      <div className={styles.emailScroll}>
        <div className={styles.emailHeader}>
          <div className={styles.senderMark} aria-hidden="true">{initials(senderLabel)}</div>
          <div className={styles.senderDetails}>
            <div className={styles.senderNameRow}>
              <h2>{senderLabel}</h2>
              <span className={styles.emailTimestamp}>{formatDate(email.received_at)}</span>
            </div>
            <p>{email.sender_email}</p>
          </div>
          <span className={`${styles.directionChip} ${email.direction === 'outbound' ? styles.directionOutbound : ''}`}>
            {email.direction === 'outbound' ? '已发送' : '已收到'}
          </span>
        </div>

        <div className={styles.emailSubjectBlock}>
          <p className={styles.subLabel}>主题</p>
          <h3>{email.subject}</h3>
        </div>

        <div className={styles.bodyRule} />
        <div className={styles.emailBody}>{email.body}</div>

        <AttachmentList
          attachments={email.attachments}
          onOpen={onOpenAttachment}
          onDownload={onDownloadAttachment}
        />

        <div className={styles.emailFooterAction}>
          <div>
            <p className={styles.subLabel}>回复保护</p>
            <p>{email.do_not_reply ? '这条消息不会参与自动回复。' : '这条消息可以参与自动回复。'}</p>
          </div>
          <button
            className={`${styles.guardButton} ${email.do_not_reply ? styles.guardButtonActive : ''}`}
            type="button"
            onClick={() => onToggleNoReply(email)}
            disabled={busy}
          >
            <Icon name="shield" size={15} />
            {email.do_not_reply ? '允许回复' : '禁止回复'}
          </button>
        </div>
      </div>
    </section>
  );
}

function CompletenessCard({ requirement }: { requirement: Requirement }) {
  const percentage = Math.max(0, Math.min(100, Math.round(requirement.completeness ?? 0)));

  return (
    <section className={styles.completenessCard} aria-label={`需求完成度 ${percentage}%`}>
      <div className={styles.completenessTopline}>
        <div>
          <p className={styles.subLabel}>需求完成度</p>
        </div>
        <strong>{percentage}<small>%</small></strong>
      </div>
      <div className={styles.progressTrack} aria-hidden="true">
        <span style={{ width: `${percentage}%` }} />
      </div>
      <div className={styles.progressFooter}>
        <span>状态</span>
        <span>{STATUS_LABELS[requirement.status as ThreadStatus] ?? (requirement.status || '审核中')}</span>
      </div>
    </section>
  );
}

function SignalSection({ title, items, emptyLabel, tone = 'neutral' }: {
  title: string;
  items: string[];
  emptyLabel: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <section className={`${styles.signalSection} ${tone === 'warning' ? styles.signalWarning : ''}`}>
      <div className={styles.signalHeader}>
        <p className={styles.subLabel}>{title}</p>
        <span>{String(items.length).padStart(2, '0')}</span>
      </div>
      {items.length ? (
        <ul className={styles.signalList}>
          {items.map((item) => (
            <li key={item}>
              <span className={styles.signalBullet} aria-hidden="true">{tone === 'warning' ? '!' : '•'}</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.signalEmpty}>{emptyLabel}</p>
      )}
    </section>
  );
}

function QuestionCard({
  question,
  answer,
  onAnswerChange,
  onSubmit,
  busy,
}: {
  question: ThreadDetail['question'];
  answer: string;
  onAnswerChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  busy: boolean;
}) {
  if (!question) {
    return (
      <section className={`${styles.questionCard} ${styles.questionEmpty}`}>
        <div className={styles.questionMarker}><Icon name="check" size={16} /></div>
        <div>
          <p className={styles.subLabel}>助手提问</p>
          <h3>目前没有需要澄清的问题。</h3>
          <p>线程有变化时可以重新分析，智能助手会一次提出一个需要你决定的问题。</p>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.questionCard}>
      <div className={styles.questionMarker}><Icon name="spark" size={17} /></div>
      <div className={styles.questionContent}>
        <p className={styles.subLabel}>助手提问 · {fieldLabel(question.field)}</p>
        <h3>{question.text}</h3>
        <form onSubmit={onSubmit}>
          <textarea
            value={answer}
            onChange={(event) => onAnswerChange(event.target.value)}
            placeholder="填写已确认的答案……"
            rows={3}
            aria-label="回答智能助手的问题"
            disabled={busy}
          />
          <div className={styles.questionFooter}>
            <span>只会更新这一项字段。</span>
            <button className={styles.sendButton} type="submit" disabled={busy || !answer.trim()}>
              {busy ? '正在更新……' : '提交答案'}
              <Icon name="send" size={14} />
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}

function RequirementDocument({
  requirement,
  markdown,
  loading,
  error,
  copied,
  onRetry,
  onCopy,
  onDownload,
}: {
  requirement: Requirement;
  markdown: string | null;
  loading: boolean;
  error: string | null;
  copied: boolean;
  onRetry: () => void;
  onCopy: () => void;
  onDownload: () => void;
}) {
  return (
    <div className={styles.requirementView}>
      <div className={styles.documentToolbar}>
        <div>
          <p className={styles.subLabel}>实时 Markdown</p>
        </div>
        <div className={styles.documentActions}>
          <button className={styles.inlineButton} type="button" onClick={onCopy} disabled={loading || Boolean(error)}>
            <Icon name="clipboard" size={14} />
            {copied ? '已复制' : '复制 Markdown'}
          </button>
          <button className={styles.inlineButton} type="button" onClick={onDownload} disabled={loading || Boolean(error)}>
            <Icon name="download" size={14} />
            下载 .md
          </button>
        </div>
      </div>
      <div className={styles.documentRule} />
      {loading ? <LoadingState label="正在生成需求文档" /> : null}
      {!loading && error ? (
        <div className={styles.documentError} role="alert">
          <div className={styles.errorMarkSmall}>!</div>
          <div>
            <strong>Markdown 暂不可用。</strong>
            <p>{error}</p>
            <button className={styles.inlineButton} type="button" onClick={onRetry}><Icon name="refresh" size={14} />重试</button>
          </div>
        </div>
      ) : null}
      {!loading && !error && markdown !== null ? (
        <pre className={styles.markdownDocument}>{markdown}</pre>
      ) : null}
      <div className={styles.documentFootnote}>
        <span>{requirement.id}</span>
        <span>仅根据已确认字段更新</span>
      </div>
    </div>
  );
}

function EmployeePanel({
  detail,
  settings,
  viewMode,
  onViewModeChange,
  answer,
  onAnswerChange,
  onAnswer,
  onAnalyze,
  onReply,
  onCopyMarkdown,
  onDownloadMarkdown,
  onRetryMarkdown,
  markdown,
  markdownLoading,
  markdownError,
  copied,
  busyAction,
  replyDisabledReason,
}: {
  detail: ThreadDetail;
  settings: Settings;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  answer: string;
  onAnswerChange: (value: string) => void;
  onAnswer: (event: FormEvent<HTMLFormElement>) => void;
  onAnalyze: () => void;
  onReply: () => void;
  onCopyMarkdown: () => void;
  onDownloadMarkdown: () => void;
  onRetryMarkdown: () => void;
  markdown: string | null;
  markdownLoading: boolean;
  markdownError: string | null;
  copied: boolean;
  busyAction: ActionKey | null;
  replyDisabledReason: string | null;
}) {
  const knownFields = useMemo(
    () => SIGNAL_FIELDS.filter(({ key }) => hasContent(detail.requirement[key])).map(({ label }) => label),
    [detail.requirement],
  );
  const missingFields = useMemo(
    () => SIGNAL_FIELDS.filter(({ key }) => !hasContent(detail.requirement[key])).map(({ label }) => label),
    [detail.requirement],
  );
  const risks = detail.requirement.risks.filter(hasContent);
  const openQuestions = detail.requirement.open_questions.filter(hasContent);
  const missingItems = missingFields.slice(0, 5);
  if (openQuestions.length) missingItems.push(`${openQuestions.length} 个待确认问题`);

  return (
    <aside className={`${styles.panel} ${styles.employeePanel}`} aria-label="智能助手">
      <div className={styles.employeeHeader}>
        <div className={styles.employeeHeaderTop}>
          <PanelLabel trailing={detail.reply_log.length ? `${detail.reply_log.length} 条回复` : '安静模式'}>智能助手</PanelLabel>
          <span className={styles.liveIndicator}><span /> 本地助手</span>
        </div>
        <div className={styles.viewTabs} role="tablist" aria-label="智能助手面板视图">
          <button type="button" role="tab" aria-selected={viewMode === 'ai'} className={viewMode === 'ai' ? styles.viewTabActive : ''} onClick={() => onViewModeChange('ai')}>助手</button>
          <button type="button" role="tab" aria-selected={viewMode === 'requirement'} className={viewMode === 'requirement' ? styles.viewTabActive : ''} onClick={() => onViewModeChange('requirement')}>需求文档</button>
        </div>
      </div>

      {viewMode === 'requirement' ? (
        <RequirementDocument
          requirement={detail.requirement}
          markdown={markdown}
          loading={markdownLoading}
          error={markdownError}
          copied={copied}
          onRetry={onRetryMarkdown}
          onCopy={onCopyMarkdown}
          onDownload={onDownloadMarkdown}
        />
      ) : (
        <div className={styles.employeeScroll}>
          <CompletenessCard requirement={detail.requirement} />

          <div className={styles.signalGrid}>
            <SignalSection title="已确认" items={knownFields} emptyLabel="还没有已确认的信息。" />
            <SignalSection title="待补充" items={missingItems} emptyLabel="核心字段已经收集完成。" />
          </div>

          <SignalSection title="风险" items={risks} emptyLabel="暂未发现明显风险。" tone="warning" />

          <QuestionCard
            question={detail.question}
            answer={answer}
            onAnswerChange={onAnswerChange}
            onSubmit={onAnswer}
            busy={busyAction === 'answer'}
          />

          <div className={styles.employeeActions}>
            <button className={styles.secondaryButton} type="button" onClick={onAnalyze} disabled={busyAction !== null}>
              <Icon name="spark" size={15} />
              {busyAction === 'analyze' ? '正在分析……' : '分析线程'}
            </button>
            <button className={styles.primaryButton} type="button" onClick={onReply} disabled={busyAction !== null || Boolean(replyDisabledReason)} title={replyDisabledReason ?? undefined}>
              <Icon name="send" size={15} />
              {busyAction === 'reply' ? '正在模拟……' : '模拟回复'}
            </button>
          </div>
          {replyDisabledReason ? <p className={styles.actionHint}>{replyDisabledReason}</p> : null}

          {detail.reply_log.length ? (
            <section className={styles.replyLog}>
              <div className={styles.signalHeader}>
                <p className={styles.subLabel}>回复记录</p>
                <span>{String(detail.reply_log.length).padStart(2, '0')}</span>
              </div>
              {detail.reply_log.slice().reverse().map((reply) => (
                <div className={styles.replyRow} key={reply.id}>
                  <span className={styles.replyStatus}>{replyStatusLabel(reply.status)}</span>
                  <p>{reply.body}</p>
                  <time>{formatDate(reply.created_at)}</time>
                </div>
              ))}
            </section>
          ) : null}
        </div>
      )}
    </aside>
  );
}

export default function WorkbenchShell({ threadId, onClose, onUpdated }: WorkbenchShellProps) {
  const [detail, setDetail] = useState<ThreadDetail | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [selectedEmailId, setSelectedEmailId] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('ai');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<ActionKey | null>(null);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [markdownLoading, setMarkdownLoading] = useState(false);
  const [markdownError, setMarkdownError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const retryActionRef = useRef<(() => void) | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    setActionError(null);
    retryActionRef.current = () => { void loadData(); };

    try {
      const [nextDetail, nextSettings] = await Promise.all([api.thread(threadId), api.settings()]);
      setDetail(nextDetail);
      setSettings(nextSettings);
      setSelectedEmailId((current) => nextDetail.emails.some((email) => email.id === current) ? current : getDefaultEmailId(nextDetail.emails));
      setMarkdown(null);
      setMarkdownError(null);
      setAnswer('');
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    setDetail(null);
    setSettings(null);
    setSelectedEmailId('');
    setViewMode('ai');
    setMarkdown(null);
    void loadData();
  }, [loadData]);

  const runDetailAction = useCallback(async (action: ActionKey, operation: () => Promise<ThreadDetail>) => {
    setBusyAction(action);
    setActionError(null);
    retryActionRef.current = () => { void runDetailAction(action, operation); };

    try {
      const nextDetail = await operation();
      setDetail(nextDetail);
      setSelectedEmailId((current) => nextDetail.emails.some((email) => email.id === current) ? current : getDefaultEmailId(nextDetail.emails));
      setMarkdown(null);
      setMarkdownError(null);
      onUpdated?.();
      return nextDetail;
    } catch (error) {
      setActionError(errorMessage(error));
      return null;
    } finally {
      setBusyAction(null);
    }
  }, [onUpdated]);

  const runEmailGuardAction = useCallback(async (emailId: string, nextValue: boolean) => {
    setBusyAction('email-guard');
    setActionError(null);
    retryActionRef.current = () => { void runEmailGuardAction(emailId, nextValue); };

    try {
      await api.setEmailNoReply(emailId, nextValue);
      // The email guard also changes the thread and requirement status server-side.
      setDetail(await api.thread(threadId));
      setMarkdown(null);
      setMarkdownError(null);
      onUpdated?.();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusyAction(null);
    }
  }, [onUpdated, threadId]);

  const runSettingsAction = useCallback(async (nextValue: boolean) => {
    setBusyAction('settings');
    setActionError(null);
    retryActionRef.current = () => { void runSettingsAction(nextValue); };

    try {
      const nextSettings = await api.setAutoReply(nextValue);
      setSettings(nextSettings);
      onUpdated?.();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusyAction(null);
    }
  }, [onUpdated]);

  const loadMarkdown = useCallback(async (): Promise<string> => {
    if (!detail) throw new Error('需求尚未加载。');
    setMarkdownLoading(true);
    setMarkdownError(null);
    try {
      const result = await api.markdown(detail.requirement.id);
      setMarkdown(result.markdown);
      return result.markdown;
    } catch (error) {
      const message = errorMessage(error);
      setMarkdownError(message);
      throw error;
    } finally {
      setMarkdownLoading(false);
    }
  }, [detail]);

  useEffect(() => {
    if (viewMode === 'requirement' && markdown === null && !markdownLoading && !markdownError) {
      void loadMarkdown().catch(() => undefined);
    }
  }, [loadMarkdown, markdown, markdownError, markdownLoading, viewMode]);

  const selectedEmail = detail?.emails.find((email) => email.id === selectedEmailId);

  const handleAnalyze = useCallback(() => {
    if (!detail || busyAction) return;
    void runDetailAction('analyze', () => api.analyze(detail.thread.id));
  }, [busyAction, detail, runDetailAction]);

  const handleAnswer = useCallback((event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedAnswer = answer.trim();
    if (!detail || !detail.question || !trimmedAnswer || busyAction) return;

    void runDetailAction('answer', () => api.answer(detail.thread.id, trimmedAnswer)).then((nextDetail) => {
      if (nextDetail) setAnswer('');
    });
  }, [answer, busyAction, detail, runDetailAction]);

  const replyDisabledReason = useMemo(() => {
    if (!detail || !settings) return '正在加载回复设置。';
    if (detail.thread.do_not_reply) return '线程保护已开启，无法回复。';
    if (detail.emails.some((email) => email.do_not_reply) || detail.thread.status === 'do_not_reply') return '这条线程中的消息已开启回复保护。';
    if (settings.auto_reply === false) return '请先打开“自动回复”，才能模拟发送。';
    if (detail.thread.status === 'replied') return '这条线程已经模拟回复过了。';
    if (detail.thread.status === 'no_action') return '这条线程标记为无需处理。';
    if (detail.thread.category !== 'requirement') return '这条线程不是需求。';
    if (detail.question) return '请先回答待确认问题。';
    if (detail.requirement.completeness < 75) return '需求还需要更多已确认信息才能回复。';
    return null;
  }, [detail, settings]);

  const handleReply = useCallback(() => {
    if (!detail || busyAction || replyDisabledReason) return;
    void runDetailAction('reply', () => api.reply(detail.thread.id));
  }, [busyAction, detail, replyDisabledReason, runDetailAction]);

  const handleThreadGuard = useCallback(() => {
    if (!detail || busyAction) return;
    const nextValue = !detail.thread.do_not_reply;
    void runDetailAction('thread-guard', () => api.setThreadNoReply(detail.thread.id, nextValue));
  }, [busyAction, detail, runDetailAction]);

  const handleEmailGuard = useCallback((email: Email) => {
    if (busyAction) return;
    void runEmailGuardAction(email.id, !email.do_not_reply);
  }, [busyAction, runEmailGuardAction]);

  const handleAttachmentOpen = useCallback((attachment: Attachment) => {
    if (typeof window === 'undefined') return;
    window.open(api.attachment(attachment.id), '_blank', 'noopener,noreferrer');
  }, []);

  const handleAttachmentDownload = useCallback((attachment: Attachment) => {
    if (typeof document === 'undefined') return;
    const link = document.createElement('a');
    link.href = api.attachment(attachment.id, true);
    link.download = attachment.filename;
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, []);

  const copyText = useCallback(async (value: string) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const textArea = document.createElement('textarea');
    textArea.value = value;
    textArea.style.position = 'fixed';
    textArea.style.opacity = '0';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const didCopy = document.execCommand('copy');
    textArea.remove();
    if (!didCopy) throw new Error('浏览器拒绝了剪贴板访问。');
  }, []);

  const handleCopyMarkdown = useCallback(async () => {
    try {
      const value = markdown ?? await loadMarkdown();
      await copyText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (error) {
      setMarkdownError(errorMessage(error));
    }
  }, [copyText, loadMarkdown, markdown]);

  const handleDownloadMarkdown = useCallback(async () => {
    try {
      const value = markdown ?? await loadMarkdown();
      const blob = new Blob([value], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${slugify(detail?.requirement.title || 'requirement')}.md`;
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Keep the blob alive until the browser has consumed the download URL.
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (error) {
      setMarkdownError(errorMessage(error));
    }
  }, [detail?.requirement.title, loadMarkdown, markdown]);

  const retryMarkdown = useCallback(() => {
    void loadMarkdown().catch(() => undefined);
  }, [loadMarkdown]);

  if (loading && !detail) {
    return (
      <section className={styles.shell} aria-label="需求工作台加载中">
        <div className={styles.stateTopbar}>
          <button className={styles.iconButton} type="button" onClick={onClose} aria-label="返回工作台"><Icon name="arrow-left" /></button>
          <div><p className={styles.eyebrow}>需求工作台 / 本地服务</p><h1>正在打开需求</h1></div>
        </div>
        <div className={styles.stateWrap}><LoadingState /></div>
      </section>
    );
  }

  if (loadError && !detail) {
    return <ErrorState message={loadError} onRetry={() => { void loadData(); }} onClose={onClose} />;
  }

  if (!detail || !settings) return null;

  const completion = Math.max(0, Math.min(100, Math.round(detail.requirement.completeness ?? detail.thread.completeness ?? 0)));
  const topbarProgressStyle = { '--completion': `${completion}%` } as CSSProperties;
  const hasEmailGuard = detail.emails.some((email) => email.do_not_reply);

  return (
    <section className={styles.shell} aria-label="需求工作台">
      <header className={styles.topbar}>
        <button className={styles.iconButton} type="button" onClick={onClose} aria-label="返回工作台">
          <Icon name="arrow-left" />
        </button>
        <div className={styles.titleBlock}>
          <p className={styles.eyebrow}><span className={styles.eyebrowPulse} /> 需求工作台 <span>/</span> {categoryLabel(detail.thread.category)}</p>
          <div className={styles.titleRow}>
            <h1>{detail.thread.title}</h1>
            <StatusPill status={detail.thread.status} />
          </div>
          <p className={styles.titleSubject}>{detail.thread.subject}</p>
        </div>
        <div className={styles.topbarControls}>
          <div className={styles.autoReplyControl}>
            <span className={styles.autoReplyLabel}>自动回复</span>
            <Toggle
              checked={settings.auto_reply}
              disabled={busyAction === 'settings'}
              label={`自动回复${settings.auto_reply ? '已开启' : '已关闭'}`}
              onChange={() => { void runSettingsAction(!settings.auto_reply); }}
            />
            <span className={`${styles.toggleState} ${settings.auto_reply ? styles.toggleStateOn : ''}`}>
              {settings.auto_reply ? '开' : '关'}
            </span>
          </div>
          <button className={`${styles.topGuardButton} ${detail.thread.do_not_reply || hasEmailGuard ? styles.topGuardButtonActive : ''}`} type="button" onClick={handleThreadGuard} disabled={busyAction !== null}>
            <Icon name="shield" size={15} />
            {detail.thread.do_not_reply ? '线程已禁止回复' : hasEmailGuard ? '消息回复保护已开启' : '禁止回复'}
          </button>
        </div>
      </header>

      <div className={styles.progressRail} aria-hidden="true"><span style={topbarProgressStyle} /></div>

      {actionError ? (
        <div className={styles.actionError} role="alert">
          <span className={styles.errorMarkSmall}>!</span>
          <span>{actionError}</span>
          <button type="button" onClick={() => retryActionRef.current?.()}><Icon name="refresh" size={14} /> 重试</button>
          <button type="button" className={styles.dismissError} onClick={() => setActionError(null)} aria-label="关闭错误提示"><Icon name="x" size={14} /></button>
        </div>
      ) : null}

      <main className={styles.workbenchGrid}>
        <ThreadRail detail={detail} selectedEmailId={selectedEmailId} onSelect={setSelectedEmailId} />
        <EmailPanel
          email={selectedEmail}
          busy={busyAction === 'email-guard'}
          onToggleNoReply={handleEmailGuard}
          onOpenAttachment={handleAttachmentOpen}
          onDownloadAttachment={handleAttachmentDownload}
        />
        <EmployeePanel
          detail={detail}
          settings={settings}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          answer={answer}
          onAnswerChange={setAnswer}
          onAnswer={handleAnswer}
          onAnalyze={handleAnalyze}
          onReply={handleReply}
          onCopyMarkdown={() => { void handleCopyMarkdown(); }}
          onDownloadMarkdown={() => { void handleDownloadMarkdown(); }}
          onRetryMarkdown={retryMarkdown}
          markdown={markdown}
          markdownLoading={markdownLoading}
          markdownError={markdownError}
          copied={copied}
          busyAction={busyAction}
          replyDisabledReason={replyDisabledReason}
        />
      </main>

      <footer className={styles.shellFooter}>
        <span>本地 / {detail.thread.id}</span>
        <span>附件不会参与智能分析</span>
        <span>{completion}% 已确认</span>
      </footer>
    </section>
  );
}

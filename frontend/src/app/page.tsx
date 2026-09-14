'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { Settings, Thread } from '../lib/api';
import { api } from '../lib/api';
import { InfiniteWorkspace, type WorkbenchShellProps } from '../components/spatial/InfiniteWorkspace';
import WorkbenchShell from '../components/workbench/WorkbenchShell';
import { DEMO_THREADS } from '../components/spatial/demoData';

const RefreshContext = createContext<() => void>(() => {});

function friendlyError(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : '';
  if (!message || /failed to fetch|networkerror|load failed/i.test(message)) return fallback;
  if (/^Mail provider error:/i.test(message)) {
    if (/configuration is incomplete/i.test(message)) return '邮箱同步失败：邮箱配置不完整，请检查 backend/.env。';
    if (/SMTP send failed/i.test(message)) return '邮件发送失败：请检查 SMTP 地址、端口和账号配置。';
    return '邮箱同步失败：请检查 IMAP 地址、端口、账号和密码配置。';
  }
  if (/^LLM provider error:/i.test(message)) {
    return 'DeepSeek 调用失败：请检查 API Key、模型和网络配置。';
  }
  return message;
}

function ConnectedWorkbench({ threadId, onClose }: WorkbenchShellProps) {
  const refresh = useContext(RefreshContext);
  return <WorkbenchShell threadId={threadId} onUpdated={refresh} onClose={() => { refresh(); onClose(); }} />;
}

export default function HomePage() {
  const [threads, setThreads] = useState<Thread[]>(DEMO_THREADS);
  const [settings, setSettings] = useState<Settings>({ auto_reply: false, llm_provider: 'mock', mail_provider: 'mock' });
  const [connection, setConnection] = useState<'demo' | 'live'>('demo');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [mailSyncPending, setMailSyncPending] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextThreads, nextSettings] = await Promise.all([api.threads(), api.settings()]);
      setThreads(nextThreads);
      setSettings(nextSettings);
      setConnection('live');
      setError(null);
    } catch (cause) {
      setConnection('demo');
      setError(friendlyError(cause, '无法连接到需求工作台服务，请确认本地后端已启动。'));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function handleAutoReplyChange(enabled: boolean) {
    if (saving) return;
    setSaving(true);
    try {
      setSettings(await api.setAutoReply(enabled));
      setError(null);
    } catch (cause) {
      setError(friendlyError(cause, '自动回复设置未能更新。'));
    } finally {
      setSaving(false);
    }
  }

  async function handleSyncMail() {
    if (mailSyncPending || connection !== 'live') return;
    setMailSyncPending(true);
    setSyncNotice(null);
    try {
      const result = await api.syncMail();
      await refresh();
      setSyncNotice(result.imported > 0 ? `已同步 ${result.imported} 封新邮件。` : '邮箱已同步，没有新的邮件。');
      setError(null);
    } catch (cause) {
      setError(friendlyError(cause, '邮箱同步失败，请检查邮箱配置。'));
    } finally {
      setMailSyncPending(false);
    }
  }

  return (
    <RefreshContext.Provider value={refresh}>
      <main>
        <InfiniteWorkspace threads={threads} settings={settings} connection={connection}
          onAutoReplyChange={handleAutoReplyChange} onSyncMail={handleSyncMail}
          autoReplyPending={saving || connection !== 'live'} mailSyncPending={mailSyncPending}
          WorkbenchShell={ConnectedWorkbench} />
        {error && <div role="alert" style={{ position: 'fixed', bottom: 56, left: '50%', transform: 'translateX(-50%)', zIndex: 100, maxWidth: '90vw', padding: '12px 18px', background: '#28251f', border: '1px solid #75634e', borderRadius: 12, color: '#ece5d7', fontSize: 13 }}>
          {error} <button type="button" onClick={() => void refresh()} style={{ marginLeft: 16, textDecoration: 'underline' }}>重试连接</button>
        </div>}
        {syncNotice && <div role="status" style={{ position: 'fixed', bottom: 56, left: '50%', transform: 'translateX(-50%)', zIndex: 99, maxWidth: '90vw', padding: '12px 18px', background: '#173c43', border: '1px solid #72c8d1', borderRadius: 12, color: '#e1fbfb', fontSize: 13 }}>
          {syncNotice}
        </div>}
      </main>
    </RefreshContext.Provider>
  );
}

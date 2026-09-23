'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { Settings, Thread } from '../lib/api';
import { api } from '../lib/api';
import { errorLabel } from '../lib/i18n';
import { InfiniteWorkspace, type WorkbenchShellProps } from '../components/spatial/InfiniteWorkspace';
import WorkbenchShell from '../components/workbench/WorkbenchShell';
import { DEMO_THREADS } from '../components/spatial/demoData';

const RefreshContext = createContext<() => void>(() => {});

function friendlyError(error: unknown, fallback: string): string {
  return errorLabel(error, fallback);
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

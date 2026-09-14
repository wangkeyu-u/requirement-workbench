import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '需求工作台 · 无限空间',
  description: '把邮件整理成可靠、可执行的需求。',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

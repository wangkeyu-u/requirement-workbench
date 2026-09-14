export type ThreadStatus = 'waiting_for_me' | 'ready' | 'replied' | 'no_action' | 'do_not_reply';
export interface Thread { id:string; title:string; sender:string; subject:string; preview:string; status:ThreadStatus; completeness:number; unread_count:number; question_count:number; updated_at:string; do_not_reply:boolean; requirement_id:string; category:string }
export interface Attachment { id:string; filename:string; content_type:string; size:number }
export interface Email { id:string; thread_id:string; sender:string; sender_email:string; subject:string; body:string; received_at:string; direction:'inbound'|'outbound'; do_not_reply:boolean; attachments:Attachment[] }
export interface Requirement { id:string; title:string; requester:string; background:string; business_problem:string; goal:string; stakeholders:string[]; users:string[]; scope:string[]; out_of_scope:string[]; functional_requirements:string[]; non_functional_requirements:string[]; constraints:string[]; dependencies:string[]; data_sources:string[]; deadline:string|null; priority:string|null; acceptance_criteria:string[]; assumptions:string[]; open_questions:string[]; risks:string[]; status:string; completeness:number }
export interface Question { field:string; text:string }
export interface Reply { id:string; body:string; status:string; created_at:string }
export interface ThreadDetail { thread:Thread; emails:Email[]; requirement:Requirement; question:Question|null; reply_log:Reply[] }
export interface Settings { auto_reply:boolean; llm_provider:string; mail_provider:string }
export interface MailSyncResult { provider:string; fetched:number; imported:number; skipped:number; threads:number }
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
export async function request<T>(path:string,init?:RequestInit):Promise<T> {
  const response=await fetch(`${API_BASE}${path}`,{...init,headers:{'Content-Type':'application/json',...init?.headers},cache:'no-store'});
  if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(typeof body?.detail==='string'?body.detail:`Request failed (${response.status})`);}
  return response.json() as Promise<T>;
}
export const api = {
  threads:()=>request<Thread[]>('/api/threads'),
  syncMail:()=>request<MailSyncResult>('/api/mail/sync',{method:'POST'}),
  thread:(id:string)=>request<ThreadDetail>(`/api/threads/${encodeURIComponent(id)}`),
  analyze:(id:string)=>request<ThreadDetail>(`/api/threads/${encodeURIComponent(id)}/analyze`,{method:'POST'}),
  answer:(id:string,answer:string)=>request<ThreadDetail>(`/api/threads/${encodeURIComponent(id)}/answer`,{method:'POST',body:JSON.stringify({answer})}),
  setThreadNoReply:(id:string,do_not_reply:boolean)=>request<ThreadDetail>(`/api/threads/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({do_not_reply})}),
  setEmailNoReply:(id:string,do_not_reply:boolean)=>request<{ok:boolean}>(`/api/emails/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({do_not_reply})}),
  settings:()=>request<Settings>('/api/settings'),
  setAutoReply:(auto_reply:boolean)=>request<Settings>('/api/settings',{method:'PATCH',body:JSON.stringify({auto_reply})}),
  reply:(id:string)=>request<ThreadDetail>(`/api/threads/${encodeURIComponent(id)}/reply`,{method:'POST'}),
  markdown:(id:string)=>request<{markdown:string}>(`/api/requirements/${encodeURIComponent(id)}/markdown`),
  attachment:(id:string,download=false)=>`${API_BASE}/api/attachments/${encodeURIComponent(id)}${download?'?download=true':''}`,
};

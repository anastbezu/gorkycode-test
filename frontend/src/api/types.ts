// Типы — один в один из docs/contracts/ (api.md, data-model.md, agent-tools.md).
// Других полей интерфейс не использует.

export type RecordType = 'task' | 'meeting' | 'reminder';
export type RecordStatus = 'active' | 'done' | 'cancelled';

/** Запись — data-model.md, «Запись». Даты — строки ISO 8601 со смещением или Z. */
export interface Record {
  id: string;
  user_id: string;
  type: RecordType;
  title: string;
  start: string | null;
  end: string | null;
  all_day: boolean;
  deadline: string | null;
  status: RecordStatus;
  created_at: string;
}

/** Результат действия — agent-tools.md, «Результат действия». */
export interface ActionResult {
  action: string;
  ok: boolean;
  records: Record[];
  conflicts: Record[];
  candidates: Record[];
  restored: Record[];
  missing: string[];
  error: string | null;
}

export interface LLMConfig {
  base_url: string | null;
  api_key: string | null;
  model: string | null;
}

export interface ChatRequest {
  conversation_id: string | null;
  text: string;
  timezone: string;
  llm_config?: LLMConfig;
}

export type AwaitingKind = 'answer' | 'choice' | 'confirm' | 'time' | null;

export interface ChatResponse {
  conversation_id: string;
  reply: string;
  result: ActionResult | null;
  awaiting: AwaitingKind;
}

export interface Credentials {
  login: string;
  password: string;
}

export interface Account {
  id: string;
  login: string;
  demo: boolean;
}

export interface AuthResponse {
  token: string;
  account: Account;
}

export interface CreateItem {
  type: RecordType;
  title: string;
  start?: string | null;
  end?: string | null;
  time_given?: boolean;
  deadline?: string | null;
}

export interface UpdateItem {
  title?: string;
  start?: string;
  end?: string;
  time_given?: boolean;
  deadline?: string;
}

export interface SetItemStatus {
  status: RecordStatus;
}

export type GoogleCalendarState = 'not_connected' | 'connected' | 'error';

export interface GoogleCalendarStatus {
  state: GoogleCalendarState;
  email: string | null;
  error: string | null;
  pending: number;
  unavailable?: boolean;
}

export interface GoogleConnectResponse {
  auth_url: string;
}

// Клиент API: /api/chat, /api/items (и /api/stt в frontend-02). Отвечает за три вещи:
// 1. Пользователь. X-User-Id выдаёт сервер в ответе на первый запрос без заголовка и тогда же
//    загружает новому пользователю 1000 записей стартового набора. Пока id не получен, следующий
//    запрос ждёт первый — иначе два параллельных запроса создадут двух пользователей.
// 2. Восстановление: 400 (испорченный X-User-Id) — забыть id и повторить без него;
//    404 на чате (разговор не найден) — забыть разговор и повторить с conversation_id = null.
// 3. Ошибки в два вида: «результат неизвестен» (сеть, таймаут, 5xx, не-JSON — сервер мог успеть
//    выполнить) и «сервер не принял» (4xx с detail — точно ничего не сделано).

import { loadAuth, loadUserId, saveAuth, saveUserId } from '../lib/storage';
import type {
  Account,
  ActionResult,
  AuthResponse,
  ChatRequest,
  ChatResponse,
  CreateItem,
  Credentials,
  LLMConfig,
  Record,
  RecordStatus,
  UpdateItem,
} from './types';

const USER_HEADER = 'X-User-Id';
const CHAT_TIMEOUT_MS = 60_000; // агент: таймаут LLM 15 с и повтор — ответ бывает до ~30 с
const ITEMS_TIMEOUT_MS = 30_000;
const AUTH_TIMEOUT_MS = 30_000;

export type ApiErrorKind = 'unknown' | 'rejected';

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
    readonly detail: string,
  ) {
    super(detail);
  }
}

// --- пользователь -------------------------------------------------------------------------

let userId: string | null = loadUserId();
let auth: AuthResponse | null = loadAuth();
let firstRequest: Promise<void> | null = null;
const profileResetListeners = new Set<() => void>();
const sessionExpiredListeners = new Set<() => void>();

/** Подписка на «начат новый профиль» (сохранённый id оказался испорчен). */
export function onProfileReset(listener: () => void): () => void {
  profileResetListeners.add(listener);
  return () => profileResetListeners.delete(listener);
}

export function onSessionExpired(listener: () => void): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

function rememberUser(res: Response): void {
  const id = res.headers.get(USER_HEADER);
  if (id && id !== userId) {
    userId = id;
    saveUserId(id);
  }
}

function forgetUser(): void {
  userId = null;
  saveUserId(null);
  profileResetListeners.forEach((listener) => listener());
}

function forgetAuth(): void {
  auth = null;
  saveAuth(null);
  sessionExpiredListeners.forEach((listener) => listener());
}

/**
 * Выполнить запрос от имени пользователя. Если id ещё нет, первый такой запрос идёт один,
 * остальные ждут его ответа и уходят уже с полученным id. Возвращает и id, с которым ушёл запрос.
 */
async function asUser(
  send: (id: string | null, token: string | null) => Promise<Response>,
): Promise<{ res: Response; sentId: string | null }> {
  if (auth) {
    const token = auth.token;
    const res = await send(null, token);
    if (res.status === 401) {
      forgetAuth();
      throw new ApiError('rejected', 401, 'Сессия входа истекла — вы снова гость. Войдите ещё раз.');
    }
    return { res, sentId: null };
  }

  while (!userId && firstRequest) {
    await firstRequest;
  }
  if (userId) {
    const sentId = userId;
    const res = await send(sentId, null);
    rememberUser(res);
    return { res, sentId };
  }
  let done!: () => void;
  firstRequest = new Promise<void>((resolve) => (done = resolve));
  try {
    const res = await send(null, null);
    rememberUser(res);
    return { res, sentId: null };
  } finally {
    // При ошибке сервер id не выдаёт — тогда следующий запрос снова пойдёт «первым»
    firstRequest = null;
    done();
  }
}

/**
 * 400 на запрос с X-User-Id — сохранённый id испорчен. Забыть его, если это ещё не сделал
 * параллельный запрос (иначе два запроса начнут два новых профиля), и вернуть true — повторить.
 */
function recoverBadUser(res: Response, sentId: string | null): boolean {
  if (res.status !== 400 || !sentId) return false;
  if (sentId === userId) forgetUser();
  return true;
}

// --- общий fetch --------------------------------------------------------------------------

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    // Обрыв сети, отказ в соединении, таймаут — результат неизвестен
    throw new ApiError('unknown', null, 'Нет ответа от сервера');
  } finally {
    clearTimeout(timer);
  }
}

function headersFor(id: string | null, token: string | null = null, extra: HeadersInit = {}): Headers {
  const headers = new Headers(extra);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  } else if (id) {
    headers.set(USER_HEADER, id);
  }
  return headers;
}

/** Текст из `detail`: строка или список ошибок валидации FastAPI (`[{msg, loc, ...}]`). */
function detailText(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const { msg, loc } = item as { msg?: string; loc?: unknown[] };
        const where = Array.isArray(loc) ? loc.filter((p) => p !== 'body' && p !== 'query').join('.') : '';
        return where ? `${where}: ${msg ?? ''}` : (msg ?? '');
      })
      .join('; ');
  }
  return '';
}

/** Разобрать ответ: 2xx — JSON, 5xx и не-JSON — «неизвестно», остальные 4xx — «не принял». */
async function parse<T>(res: Response): Promise<T> {
  if (res.status >= 500) throw new ApiError('unknown', res.status, 'Нет ответа от сервера');
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    // Например, HTML-страница 502 от nginx или обрыв на середине тела
    throw new ApiError('unknown', res.status, 'Нет ответа от сервера');
  }
  if (!res.ok) {
    throw new ApiError('rejected', res.status, detailText(body) || `Код ответа ${res.status}`);
  }
  return body as T;
}

// --- /api/chat ----------------------------------------------------------------------------

/** Пустые поля → null; все пусты → настройки не отправляются, сервер берёт свои. */
export function llmConfigForRequest(cfg: LLMConfig): LLMConfig | undefined {
  const clean = (v: string | null) => (v && v.trim() ? v.trim() : null);
  const result = { base_url: clean(cfg.base_url), model: clean(cfg.model), api_key: clean(cfg.api_key) };
  return result.base_url || result.model || result.api_key ? result : undefined;
}

export interface SendChatArgs {
  text: string;
  conversationId: string | null;
  timezone: string;
  llmConfig: LLMConfig;
}

/**
 * Отправить реплику. 404 — разговор не найден: повторить один раз с conversation_id = null
 * (сервер отвечает 404 до любого действия, повтор безопасен). 400 — повторить без X-User-Id.
 */
export async function sendChat(args: SendChatArgs): Promise<ChatResponse> {
  let conversationId = args.conversationId;
  let retriedConversation = false;
  let retriedUser = false;

  for (;;) {
    const body: ChatRequest = {
      conversation_id: conversationId,
      text: args.text,
      timezone: args.timezone,
    };
    const llm = llmConfigForRequest(args.llmConfig);
    if (llm) body.llm_config = llm;

    const { res, sentId } = await asUser((id, token) =>
      fetchWithTimeout(
        '/api/chat',
        {
          method: 'POST',
          headers: headersFor(id, token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify(body),
        },
        CHAT_TIMEOUT_MS,
      ),
    );

    if (res.status === 404 && conversationId && !retriedConversation) {
      retriedConversation = true;
      conversationId = null;
      continue;
    }
    if (!retriedUser && recoverBadUser(res, sentId)) {
      retriedUser = true;
      continue;
    }
    return parse<ChatResponse>(res);
  }
}

// --- /api/items ---------------------------------------------------------------------------

export interface ItemsQuery {
  from: string; // ISO 8601 со смещением
  to: string;
  tz: string;
  /** Добавить в конец записи без даты — для блока «Без срока» в «Мои дела». */
  includeUndated: boolean;
}

export async function fetchItems(query: ItemsQuery): Promise<Record[]> {
  const params = new URLSearchParams({
    from: query.from,
    to: query.to,
    tz: query.tz,
    include_undated: String(query.includeUndated),
  });
  let retriedUser = false;
  for (;;) {
    const { res, sentId } = await asUser((id, token) =>
      fetchWithTimeout(`/api/items?${params}`, { headers: headersFor(id, token) }, ITEMS_TIMEOUT_MS),
    );
    if (!retriedUser && recoverBadUser(res, sentId)) {
      retriedUser = true;
      continue;
    }
    return parse<Record[]>(res);
  }
}

export async function createItem(body: CreateItem, tz: string): Promise<ActionResult> {
  let retriedUser = false;
  for (;;) {
    const { res, sentId } = await asUser((id, token) =>
      fetchWithTimeout(
        `/api/items?tz=${encodeURIComponent(tz)}`,
        {
          method: 'POST',
          headers: headersFor(id, token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify(body),
        },
        ITEMS_TIMEOUT_MS,
      ),
    );
    if (!retriedUser && recoverBadUser(res, sentId)) {
      retriedUser = true;
      continue;
    }
    return parse<ActionResult>(res);
  }
}

export async function updateItem(id: string, body: UpdateItem, tz: string): Promise<ActionResult> {
  let retriedUser = false;
  for (;;) {
    const { res, sentId } = await asUser((userId, token) =>
      fetchWithTimeout(
        `/api/items/${encodeURIComponent(id)}?tz=${encodeURIComponent(tz)}`,
        {
          method: 'PATCH',
          headers: headersFor(userId, token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify(body),
        },
        ITEMS_TIMEOUT_MS,
      ),
    );
    if (!retriedUser && recoverBadUser(res, sentId)) {
      retriedUser = true;
      continue;
    }
    return parse<ActionResult>(res);
  }
}

export async function setItemStatus(id: string, status: RecordStatus, tz: string): Promise<ActionResult> {
  let retriedUser = false;
  for (;;) {
    const { res, sentId } = await asUser((userId, token) =>
      fetchWithTimeout(
        `/api/items/${encodeURIComponent(id)}/status?tz=${encodeURIComponent(tz)}`,
        {
          method: 'POST',
          headers: headersFor(userId, token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify({ status }),
        },
        ITEMS_TIMEOUT_MS,
      ),
    );
    if (!retriedUser && recoverBadUser(res, sentId)) {
      retriedUser = true;
      continue;
    }
    return parse<ActionResult>(res);
  }
}

// --- /api/stt -----------------------------------------------------------------------------

const STT_TIMEOUT_MS = 60_000;

/**
 * Распознать запись: multipart, одно поле `audio`. 200 — `{text}`; ошибки (413, 415, 422, 429, 503)
 * приходят с `detail` для пользователя — ApiError 'rejected'. В чат при ошибке ничего не уходит.
 */
export async function transcribe(audio: File): Promise<string> {
  let retriedUser = false;
  for (;;) {
    const form = new FormData();
    form.append('audio', audio);
    const { res, sentId } = await asUser((id, token) =>
      fetchWithTimeout('/api/stt', { method: 'POST', headers: headersFor(id, token), body: form }, STT_TIMEOUT_MS),
    );
    if (!retriedUser && recoverBadUser(res, sentId)) {
      retriedUser = true;
      continue;
    }
    if (res.status === 503) {
      // 503 у распознавания — не «результат неизвестен», а «сервис недоступен» с detail (api.md)
      const body = await res.json().catch(() => null);
      throw new ApiError('rejected', 503, detailText(body) || 'Сервис распознавания недоступен.');
    }
    const { text } = await parse<{ text: string }>(res);
    return text;
  }
}

export async function login(c: Credentials): Promise<AuthResponse> {
  const res = await fetchWithTimeout(
    '/api/auth/login',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(c),
    },
    AUTH_TIMEOUT_MS,
  );
  const data = await parse<AuthResponse>(res);
  auth = data;
  saveAuth(data);
  return data;
}

export async function register(c: Credentials): Promise<AuthResponse> {
  const res = await fetchWithTimeout(
    '/api/auth/register',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(c),
    },
    AUTH_TIMEOUT_MS,
  );
  const data = await parse<AuthResponse>(res);
  auth = data;
  saveAuth(data);
  return data;
}

export async function logout(): Promise<void> {
  const token = auth?.token;
  auth = null;
  saveAuth(null);
  if (!token) return;
  try {
    await fetchWithTimeout(
      '/api/auth/logout',
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      },
      AUTH_TIMEOUT_MS,
    );
  } catch {
  }
}

export async function fetchMe(): Promise<Account> {
  if (!auth) {
    throw new ApiError('rejected', 401, 'Не выполнен вход');
  }
  const { res } = await asUser((_id, token) =>
    fetchWithTimeout('/api/auth/me', { headers: headersFor(null, token) }, AUTH_TIMEOUT_MS),
  );
  const account = await parse<Account>(res);
  if (auth) {
    auth = { token: auth.token, account };
    saveAuth(auth);
  }
  return account;
}

export function currentAccount(): Account | null {
  return auth?.account ?? null;
}

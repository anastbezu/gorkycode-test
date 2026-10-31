// Состояние в браузере (localStorage). Сервер не хранит ни ленту для показа, ни настройки LLM.
//   gorky.userId — X-User-Id, выданный сервером;
//   gorky.auth   — токен и данные авторизованного пользователя;
//   gorky.chat   — conversation_id и сообщения ленты этого разговора (эндпоинта истории нет);
//   gorky.llm    — настройки LLM пользователя;
//   gorky.theme  — выбранная пользователем тема оформления ('light' | 'dark' | null для системной).
// localStorage бывает недоступен (приватный режим, запрет сайта) — тогда страница работает,
// но ничего не переживает перезагрузку. Ошибки чтения не роняют страницу.

import type { ActionResult, AuthResponse, LLMConfig } from '../api/types';

const KEY_USER = 'gorky.userId';
const KEY_AUTH = 'gorky.auth';
const KEY_CHAT = 'gorky.chat';
const KEY_LLM = 'gorky.llm';
export const KEY_THEME = 'gorky.theme';
const KEY_SPEECH = 'gorky.speechEnabled';

export function loadSpeechEnabled(): boolean {
  return read<boolean>(KEY_SPEECH) !== false;
}

export function saveSpeechEnabled(enabled: boolean): void {
  write(KEY_SPEECH, enabled);
}

export interface UserMessage {
  id: string;
  role: 'user';
  text: string;
}

export interface AssistantMessage {
  id: string;
  role: 'assistant';
  reply: string;
  result: ActionResult | null;
  awaiting: 'answer' | 'choice' | null;
}

export interface ErrorMessage {
  id: string;
  role: 'error';
  kind: 'unknown' | 'rejected';
  userText: string;
  detail?: string;
}

export type ChatMessage = UserMessage | AssistantMessage | ErrorMessage;

export interface StoredChat {
  conversationId: string | null;
  messages: ChatMessage[];
}

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    // Испорченное значение или нет доступа — как будто его нет
    return null;
  }
}

function write(key: string, value: unknown): boolean {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function loadUserId(): string | null {
  return read<string>(KEY_USER);
}

export function saveUserId(id: string | null): void {
  write(KEY_USER, id);
}

export function loadAuth(): AuthResponse | null {
  return read<AuthResponse>(KEY_AUTH);
}

export function saveAuth(auth: AuthResponse | null): void {
  write(KEY_AUTH, auth);
}

export function loadChat(): StoredChat {
  const chat = read<StoredChat>(KEY_CHAT);
  if (!chat || !Array.isArray(chat.messages)) return { conversationId: null, messages: [] };
  return chat;
}

/**
 * Сохранить разговор. Если места не хватило (списки бывают на сотни записей),
 * отбрасываются самые старые сообщения, пока не влезет: последние важнее — к ним
 * относятся номера, которые пользователь называет следующей репликой.
 * Карточки ошибок в ленте эфемерны и в localStorage не сохраняются.
 */
export function saveChat(chat: StoredChat): void {
  const cleanMessages = chat.messages.filter((m) => m.role !== 'error');
  let messages = cleanMessages;
  while (!write(KEY_CHAT, { ...chat, messages })) {
    if (messages.length === 0) return;
    messages = messages.slice(Math.ceil(messages.length / 2));
  }
}

export function loadLLMConfig(): LLMConfig {
  const cfg = read<LLMConfig>(KEY_LLM);
  return {
    base_url: cfg?.base_url ?? null,
    model: cfg?.model ?? null,
    api_key: cfg?.api_key ?? null,
  };
}

export function saveLLMConfig(cfg: LLMConfig): void {
  const empty = !cfg.base_url && !cfg.model && !cfg.api_key;
  write(KEY_LLM, empty ? null : cfg);
}

export type ThemeChoice = 'light' | 'dark';

export function loadTheme(): ThemeChoice | null {
  try {
    const raw = localStorage.getItem(KEY_THEME);
    if (raw === 'light' || raw === 'dark') return raw;
    return null;
  } catch {
    return null;
  }
}

export function saveTheme(theme: ThemeChoice | null): void {
  try {
    if (!theme) localStorage.removeItem(KEY_THEME);
    else localStorage.setItem(KEY_THEME, theme);
  } catch {}
}

export function applyTheme(theme: ThemeChoice | null): void {
  try {
    if (theme) {
      document.documentElement.setAttribute('data-theme', theme);
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
  } catch {}
}

/**
 * Определить активную тему: если задана явно в localStorage — она,
 * иначе — текущая системная настройка.
 */
export function getActiveTheme(): ThemeChoice {
  const stored = loadTheme();
  if (stored) return stored;
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

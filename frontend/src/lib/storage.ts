// Состояние в браузере (localStorage). Сервер не хранит ни ленту для показа, ни настройки LLM.
//   gorky.userId — X-User-Id, выданный сервером;
//   gorky.chat   — conversation_id и сообщения ленты этого разговора (эндпоинта истории нет);
//   gorky.llm    — настройки LLM пользователя.
// localStorage бывает недоступен (приватный режим, запрет сайта) — тогда страница работает,
// но ничего не переживает перезагрузку. Ошибки чтения не роняют страницу.

import type { ActionResult, LLMConfig } from '../api/types';

const KEY_USER = 'gorky.userId';
const KEY_CHAT = 'gorky.chat';
const KEY_LLM = 'gorky.llm';

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

export type ChatMessage = UserMessage | AssistantMessage;

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

export function loadChat(): StoredChat {
  const chat = read<StoredChat>(KEY_CHAT);
  if (!chat || !Array.isArray(chat.messages)) return { conversationId: null, messages: [] };
  return chat;
}

/**
 * Сохранить разговор. Если места не хватило (списки бывают на сотни записей),
 * отбрасываются самые старые сообщения, пока не влезет: последние важнее — к ним
 * относятся номера, которые пользователь называет следующей репликой.
 */
export function saveChat(chat: StoredChat): void {
  let messages = chat.messages;
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

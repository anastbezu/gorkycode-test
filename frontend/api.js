// api.js — работа с бэкендом по контракту api.md

import { getBrowserTimezone } from './dates.js';

const STORAGE_KEYS = {
  USER_ID: 'gorky_user_id',
  CONVERSATION_ID: 'gorky_conversation_id',
  LLM_CONFIG: 'gorky_llm_config',
  CHAT_MESSAGES: 'gorky_chat_messages'
};

export function getUserId() {
  return localStorage.getItem(STORAGE_KEYS.USER_ID) || null;
}

export function setUserId(id) {
  if (id) {
    localStorage.setItem(STORAGE_KEYS.USER_ID, id);
  } else {
    localStorage.removeItem(STORAGE_KEYS.USER_ID);
  }
}

export function getConversationId() {
  return localStorage.getItem(STORAGE_KEYS.CONVERSATION_ID) || null;
}

export function setConversationId(id) {
  if (id) {
    localStorage.setItem(STORAGE_KEYS.CONVERSATION_ID, id);
  } else {
    localStorage.removeItem(STORAGE_KEYS.CONVERSATION_ID);
  }
}

export function getStoredLLMConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.LLM_CONFIG);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

export function saveStoredLLMConfig(config) {
  if (config) {
    localStorage.setItem(STORAGE_KEYS.LLM_CONFIG, JSON.stringify(config));
  } else {
    localStorage.removeItem(STORAGE_KEYS.LLM_CONFIG);
  }
}

/**
 * Подготавливает llm_config для передачи на сервер:
 * пустые поля -> null, если все пусты -> null
 */
function prepareLLMConfigForRequest() {
  const cfg = getStoredLLMConfig();
  if (!cfg) return null;

  const base_url = cfg.base_url?.trim() || null;
  const api_key = cfg.api_key?.trim() || null;
  const model = cfg.model?.trim() || null;

  if (!base_url && !api_key && !model) {
    return null;
  }

  return { base_url, api_key, model };
}

/**
 * Форматирует Date в ISO 8601 со смещением часового пояса
 * Пример: 2026-10-26T00:00:00+03:00
 */
function toLocalIsoWithOffset(date, timeZone) {
  const tz = timeZone || getBrowserTimezone();
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23'
  });

  const parts = formatter.formatToParts(date);
  const map = {};
  for (const p of parts) map[p.type] = p.value;

  const localDateStr = `${map.year}-${map.month}-${map.day}T${map.hour}:${map.minute}:${map.second}`;

  // Получаем смещение часового пояса
  const localDate = new Date(`${map.year}-${map.month}-${map.day}T${map.hour}:${map.minute}:${map.second}Z`);
  const offsetMin = Math.round((localDate.getTime() - date.getTime()) / 60000);
  const sign = offsetMin >= 0 ? '+' : '-';
  const absHours = String(Math.floor(Math.abs(offsetMin) / 60)).padStart(2, '0');
  const absMinutes = String(Math.abs(offsetMin) % 60).padStart(2, '0');
  const offsetStr = `${sign}${absHours}:${absMinutes}`;

  return `${localDateStr}${offsetStr}`;
}

/**
 * Отправка реплики пользователя в POST /api/chat
 */
export async function sendChatMessage(text, isRetry = false) {
  const tz = getBrowserTimezone();
  const userId = getUserId();
  const conversationId = getConversationId();
  const llmConfig = prepareLLMConfigForRequest();

  const headers = {
    'Content-Type': 'application/json'
  };

  if (userId) {
    headers['X-User-Id'] = userId;
  }

  const payload = {
    text,
    timezone: tz,
    conversation_id: conversationId,
    llm_config: llmConfig
  };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60000); // 60 секунд таймаут

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    // Сохраняем выданный сервером X-User-Id
    const newUserId = res.headers.get('x-user-id') || res.headers.get('X-User-Id');
    if (newUserId) {
      setUserId(newUserId);
    }

    // Обработка 404 — разговор не найден
    if (res.status === 404 && !isRetry) {
      setConversationId(null);
      return sendChatMessage(text, true);
    }

    // Обработка 400 — поврежденный X-User-Id
    if (res.status === 400 && !isRetry) {
      setUserId(null);
      return sendChatMessage(text, true);
    }

    if (!res.ok) {
      const errorData = await res.json().catch(() => null);
      let detailMsg = 'Сервер вернул ошибку';
      if (errorData?.detail) {
        detailMsg = typeof errorData.detail === 'string'
          ? errorData.detail
          : JSON.stringify(errorData.detail);
      }
      throw new Error(detailMsg);
    }

    const data = await res.json();
    if (data.conversation_id) {
      setConversationId(data.conversation_id);
    }

    return { ok: true, data };
  } catch (err) {
    clearTimeout(timeoutId);
    return {
      ok: false,
      error: err.name === 'AbortError'
        ? 'Таймаут ответа от сервера'
        : err.message || 'Ошибка сети'
    };
  }
}

/**
 * Получение списка дел на 7 дней вперед для боковой панели: GET /api/items
 */
export async function fetchCalendarItems() {
  const tz = getBrowserTimezone();
  const userId = getUserId();

  const headers = {};
  if (userId) {
    headers['X-User-Id'] = userId;
  }

  // Границы периода: сегодня 00:00 -> 8-й день 00:00
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
  const eighthDayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 8, 0, 0, 0);

  const fromStr = toLocalIsoWithOffset(todayStart, tz);
  const toStr = toLocalIsoWithOffset(eighthDayStart, tz);

  const url = `/api/items?from=${encodeURIComponent(fromStr)}&to=${encodeURIComponent(toStr)}&tz=${encodeURIComponent(tz)}&include_undated=true`;

  try {
    const res = await fetch(url, { headers });

    const newUserId = res.headers.get('x-user-id') || res.headers.get('X-User-Id');
    if (newUserId) {
      setUserId(newUserId);
    }

    if (!res.ok) {
      throw new Error(`Ошибка загрузки дел: ${res.status}`);
    }

    const items = await res.json();
    return { ok: true, items };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

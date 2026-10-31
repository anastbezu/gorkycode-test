// Поведение клиента на поддельном сервере: что уходит в запросах и как клиент восстанавливается.
// fetch подменяется функцией, которая отвечает как бэкенд по api.md.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthResponse } from './types';

const NEW_ID = '9c5896b5-9632-4dda-8002-05fd22573310';

interface Call {
  url: string;
  userId: string | null;
  authHeader: string | null;
  body: { conversation_id: string | null; llm_config?: unknown; login?: string; password?: string } | null;
}

let calls: Call[];

/** Сервер: без X-User-Id выдаёт NEW_ID; не-UUID — 400; разговор `gone` — 404. */
function fakeServer(delayMs = 5) {
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    const userId = headers.get('X-User-Id');
    const authHeader = headers.get('Authorization');
    const body = init.body ? (typeof init.body === 'string' ? JSON.parse(init.body) : null) : null;
    calls.push({ url, userId, authHeader, body });
    await new Promise((r) => setTimeout(r, delayMs));
    const json = (status: number, data: unknown, extra: { [k: string]: string } = {}) =>
      new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...extra } });

    if (url === '/api/auth/login') {
      if (body?.password === 'wrong') return json(401, { detail: 'Неверный логин или пароль' });
      return json(200, { token: 'jwt-123', account: { id: 'acc-1', login: body?.login ?? 'demo', demo: false } });
    }
    if (url === '/api/auth/register') {
      if (body?.login === 'taken') return json(409, { detail: 'Логин уже занят' });
      if (body?.login === 'bad') return json(422, { detail: 'Логин от 3 до 32 символов' });
      return json(201, { token: 'jwt-456', account: { id: 'acc-2', login: body?.login ?? 'newuser', demo: false } });
    }
    if (url === '/api/auth/logout') {
      return new Response(null, { status: 204 });
    }
    if (url === '/api/auth/me') {
      if (authHeader !== 'Bearer jwt-123') return json(401, { detail: 'Токен недействителен' });
      return json(200, { id: 'acc-1', login: 'demo', demo: false });
    }
    if (authHeader === 'Bearer jwt-expired') {
      return json(401, { detail: 'Сессия входа истекла — вы снова гость. Войдите ещё раз.' });
    }

    if (userId && !/^[0-9a-f-]{36}$/.test(userId)) return json(400, { detail: 'X-User-Id должен быть UUID' });
    const issued: { [k: string]: string } = (userId || authHeader) ? {} : { 'X-User-Id': NEW_ID };
    if (url.startsWith('/api/items')) {
      const method = init.method ?? 'GET';
      if (method === 'POST') {
        if (body?.title === 'invalid') return json(422, { detail: 'Неверные данные' });
        return json(201, {
          action: 'create_record',
          ok: true,
          records: [{ id: 'new-id', title: body?.title ?? '', status: body?.status ?? 'active', user_id: NEW_ID }],
          conflicts: [],
          candidates: [],
          restored: [],
          missing: [],
          error: null,
        }, issued);
      }
      if (method === 'PATCH') {
        if (url.includes('missing-id')) return json(404, { detail: 'Запись не найдена' });
        return json(200, {
          action: 'update_record',
          ok: true,
          records: [{ id: 'upd-id', title: body?.title ?? '', status: 'active', user_id: NEW_ID }],
          conflicts: [],
          candidates: [],
          restored: [],
          missing: [],
          error: null,
        }, issued);
      }
      return json(200, [], issued);
    }
    if (url.startsWith('/api/calendar/google')) {
      if (url.includes('unavailable')) return json(503, { detail: 'Подключение не настроено' });
      if (!authHeader) return json(403, { detail: 'Нужен вход' });
      if (init.method === 'POST') {
        return json(200, { auth_url: 'https://accounts.google.com/auth-url' });
      }
      if (init.method === 'DELETE') {
        return new Response(null, { status: 204 });
      }
      return json(200, { state: 'connected', email: 'user@example.com', error: null, pending: 2 });
    }
    if (body?.conversation_id === 'gone') return json(404, { detail: 'Разговор не найден' });
    return json(200, { conversation_id: 'c1', reply: 'ок', result: null, awaiting: null }, issued);
  });
}

async function freshClient(
  storedUserId: string | null = null,
  storedAuth: AuthResponse | null = null,
) {
  vi.resetModules();
  const data = new Map<string, string>();
  if (storedUserId) data.set('gorky.userId', JSON.stringify(storedUserId));
  if (storedAuth) data.set('gorky.auth', JSON.stringify(storedAuth));
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  });
  return import('./client');
}

const items = {
  from: '2026-10-26T00:00:00+03:00',
  to: '2026-11-02T00:00:00+03:00',
  tz: 'Europe/Moscow',
  includeUndated: true,
};
const noLlm = { base_url: null, model: null, api_key: null };

describe('TTS', () => {
  it('передаёт текст, токен и сигнал отмены; возвращает WAV', async () => {
    const client = await freshClient(null, { token: 'jwt-123', account: { id: 'acc-1', login: 'demo', demo: false } });
    const fetcher = vi.fn().mockResolvedValue(new Response('wav', { headers: { 'Content-Type': 'audio/wav' } }));
    vi.stubGlobal('fetch', fetcher);
    const signal = new AbortController().signal;
    const blob = await client.synthesizeSpeech('Ответ', signal);
    expect(await blob.text()).toBe('wav');
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe('/api/tts');
    expect(init.headers.get('Authorization')).toBe('Bearer jwt-123');
    expect(JSON.parse(init.body)).toEqual({ text: 'Ответ' });
    expect(init.signal).toBe(signal);
  });

  it('сохраняет выданный гостевой id', async () => {
    const client = await freshClient();
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response('wav', { headers: { 'Content-Type': 'audio/wav', 'X-User-Id': NEW_ID } })));
    vi.stubGlobal('fetch', fetcher);
    await client.synthesizeSpeech('Ответ', new AbortController().signal);
    await client.synthesizeSpeech('Ещё ответ', new AbortController().signal);
    expect(fetcher.mock.calls[1][1].headers.get('X-User-Id')).toBe(NEW_ID);
  });

  it.each([429, 503])('не повторяет TTS после %s', async (status) => {
    const client = await freshClient(NEW_ID);
    const fetcher = vi.fn().mockResolvedValue(new Response('', { status }));
    vi.stubGlobal('fetch', fetcher);
    await expect(client.synthesizeSpeech('Ответ', new AbortController().signal)).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it('401 сохраняет общую обработку истечения сессии', async () => {
    const client = await freshClient(null, { token: 'jwt-expired', account: { id: 'acc-1', login: 'demo', demo: false } });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));
    const expired = vi.fn();
    client.onSessionExpired(expired);
    await expect(client.synthesizeSpeech('Ответ', new AbortController().signal)).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
  });

  it.each([['text/html', 'html'], ['audio/wav', '']])('отклоняет неверный ответ %s', async (type, body) => {
    const client = await freshClient(NEW_ID);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { headers: { 'Content-Type': type } })));
    await expect(client.synthesizeSpeech('Ответ', new AbortController().signal)).rejects.toThrow();
  });

  it('уже отменённый запрос не уходит в сеть', async () => {
    const client = await freshClient(NEW_ID);
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    controller.abort();
    await expect(client.synthesizeSpeech('Ответ', controller.signal)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
});

beforeEach(() => {
  calls = [];
  vi.stubGlobal('fetch', fakeServer());
});

describe('пользователь', () => {
  it('новый браузер: без заголовка уходит ровно один запрос, остальные ждут id', async () => {
    const client = await freshClient();
    await Promise.all([
      client.fetchItems(items),
      client.fetchItems(items),
      client.sendChat({ text: 'привет', conversationId: null, timezone: 'Europe/Moscow', llmConfig: noLlm }),
    ]);
    expect(calls.filter((c) => c.userId === null)).toHaveLength(1);
    expect(calls.slice(1).every((c) => c.userId === NEW_ID)).toBe(true);
  });

  it('испорченный id: параллельные запросы начинают один новый профиль, а не два', async () => {
    const client = await freshClient('not-a-uuid');
    const resets = vi.fn();
    client.onProfileReset(resets);
    await Promise.all([client.fetchItems(items), client.fetchItems(items)]);
    expect(resets).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.userId === null)).toHaveLength(1);
  });
});

describe('разговор', () => {
  it('404: один повтор с conversation_id = null', async () => {
    const client = await freshClient(NEW_ID);
    const res = await client.sendChat({ text: 'x', conversationId: 'gone', timezone: 'Europe/Moscow', llmConfig: noLlm });
    expect(res.conversation_id).toBe('c1');
    expect(calls.map((c) => c.body?.conversation_id)).toEqual(['gone', null]);
  });
});

describe('настройки LLM', () => {
  it('все поля пусты — llm_config не отправляется', async () => {
    const client = await freshClient(NEW_ID);
    await client.sendChat({ text: 'x', conversationId: null, timezone: 'Europe/Moscow', llmConfig: noLlm });
    expect(calls[0].body).not.toHaveProperty('llm_config');
  });
  it('заполнено одно поле — остальные null', async () => {
    const client = await freshClient(NEW_ID);
    const llmConfig = { base_url: '', model: 'gpt-4o-mini', api_key: '  ' };
    await client.sendChat({ text: 'x', conversationId: null, timezone: 'Europe/Moscow', llmConfig });
    expect(calls[0].body?.llm_config).toEqual({ base_url: null, model: 'gpt-4o-mini', api_key: null });
  });
});

describe('ошибки', () => {
  it('5xx и HTML от nginx — «результат неизвестен»', async () => {
    const client = await freshClient(NEW_ID);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>502 Bad Gateway</html>', { status: 502 })));
    await expect(client.fetchItems(items)).rejects.toMatchObject({ kind: 'unknown' });
  });
  it('сеть недоступна — «результат неизвестен»', async () => {
    const client = await freshClient(NEW_ID);
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    await expect(
      client.sendChat({ text: 'x', conversationId: null, timezone: 'Europe/Moscow', llmConfig: noLlm }),
    ).rejects.toMatchObject({ kind: 'unknown' });
  });
  it('422 со списком detail — «не принял» и тексты msg', async () => {
    const client = await freshClient(NEW_ID);
    const detail = [{ type: 'timezone_aware', loc: ['query', 'from'], msg: 'Input should have timezone info' }];
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 422 })));
    await expect(client.fetchItems(items)).rejects.toMatchObject({
      kind: 'rejected',
      detail: 'from: Input should have timezone info',
    });
  });
});

describe('распознавание речи', () => {
  it('запись уходит полем audio с X-User-Id, ответ — текст', async () => {
    const client = await freshClient(NEW_ID);
    let sent: FormData | null = null;
    let userHeader: string | null = null;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        sent = init.body as FormData;
        userHeader = new Headers(init.headers).get('X-User-Id');
        return new Response(JSON.stringify({ text: 'Что у меня завтра?' }), { status: 200 });
      }),
    );
    const file = new File(['x'], 'speech.webm', { type: 'audio/webm' });
    await expect(client.transcribe(file)).resolves.toBe('Что у меня завтра?');
    expect((sent as FormData | null)?.get('audio')).toBeInstanceOf(File);
    expect(userHeader).toBe(NEW_ID);
  });

  it.each([413, 415, 422, 429, 503])('%i — detail для пользователя, вид «не принял»', async (status) => {
    const client = await freshClient(NEW_ID);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: `ошибка ${status}` }), { status })),
    );
    const file = new File(['x'], 'speech.webm', { type: 'audio/webm' });
    await expect(client.transcribe(file)).rejects.toMatchObject({ kind: 'rejected', detail: `ошибка ${status}` });
  });
});

describe('учётки и вход', () => {
  it('без входа: запрос уходит с X-User-Id и без Authorization', async () => {
    const client = await freshClient(NEW_ID);
    await client.fetchItems(items);
    expect(calls[0].userId).toBe(NEW_ID);
    expect(calls[0].authHeader).toBeNull();
  });

  it('после login: запросы идут с Authorization и без X-User-Id, гостевой id в хранилище сохранён', async () => {
    const client = await freshClient(NEW_ID);
    const authRes = await client.login({ login: 'alice', password: 'password123' });
    expect(authRes.token).toBe('jwt-123');
    expect(client.currentAccount()?.login).toBe('alice');

    await client.fetchItems(items);
    const lastCall = calls[calls.length - 1];
    expect(lastCall.authHeader).toBe('Bearer jwt-123');
    expect(lastCall.userId).toBeNull();
    expect(localStorage.getItem('gorky.userId')).toBe(JSON.stringify(NEW_ID));
  });

  it('401 на запрос с токеном: вход забыт, подписчик вызван, запрос не повторён, rejected 401', async () => {
    const client = await freshClient(NEW_ID, {
      token: 'jwt-expired',
      account: { id: 'acc-1', login: 'alice', demo: false },
    });
    const expired = vi.fn();
    client.onSessionExpired(expired);

    await expect(client.fetchItems(items)).rejects.toMatchObject({
      kind: 'rejected',
      status: 401,
      detail: 'Сессия входа истекла — вы снова гость. Войдите ещё раз.',
    });

    expect(expired).toHaveBeenCalledTimes(1);
    expect(client.currentAccount()).toBeNull();
    expect(localStorage.getItem('gorky.auth')).toBeNull();
    expect(calls.filter((c) => c.url.startsWith('/api/items'))).toHaveLength(1);
  });

  it('401 на login: вход не забывается (его и не было), подписчик не вызван, ошибка с detail сервера', async () => {
    const client = await freshClient(NEW_ID);
    const expired = vi.fn();
    client.onSessionExpired(expired);

    await expect(client.login({ login: 'alice', password: 'wrong' })).rejects.toMatchObject({
      kind: 'rejected',
      status: 401,
      detail: 'Неверный логин или пароль',
    });

    expect(expired).not.toHaveBeenCalled();
    expect(client.currentAccount()).toBeNull();
  });

  it('logout: забывает вход и при 204, и при обрыве сети', async () => {
    const client1 = await freshClient(NEW_ID, {
      token: 'jwt-123',
      account: { id: 'acc-1', login: 'alice', demo: false },
    });
    await client1.logout();
    expect(client1.currentAccount()).toBeNull();
    expect(localStorage.getItem('gorky.auth')).toBeNull();

    const client2 = await freshClient(NEW_ID, {
      token: 'jwt-123',
      account: { id: 'acc-1', login: 'alice', demo: false },
    });
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Network down'))));
    await expect(client2.logout()).resolves.toBeUndefined();
    expect(client2.currentAccount()).toBeNull();
    expect(localStorage.getItem('gorky.auth')).toBeNull();
  });

  it('register: 409 и 422 возвращают ApiError(rejected) с detail', async () => {
    const client = await freshClient(NEW_ID);

    await expect(client.register({ login: 'taken', password: 'password123' })).rejects.toMatchObject({
      kind: 'rejected',
      status: 409,
      detail: 'Логин уже занят',
    });

    await expect(client.register({ login: 'bad', password: '123' })).rejects.toMatchObject({
      kind: 'rejected',
      status: 422,
      detail: 'Логин от 3 до 32 символов',
    });
  });

  it('fetchMe: обновляет профиль при валидном токене, 401 сбрасывает сессию', async () => {
    const client = await freshClient(NEW_ID, {
      token: 'jwt-123',
      account: { id: 'acc-old', login: 'alice', demo: false },
    });
    const me = await client.fetchMe();
    expect(me.id).toBe('acc-1');
    expect(client.currentAccount()?.id).toBe('acc-1');

    const clientBad = await freshClient(NEW_ID, {
      token: 'jwt-bad',
      account: { id: 'acc-bad', login: 'bob', demo: false },
    });
    const expired = vi.fn();
    clientBad.onSessionExpired(expired);
    await expect(clientBad.fetchMe()).rejects.toMatchObject({ kind: 'rejected', status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
    expect(clientBad.currentAccount()).toBeNull();
  });
});

describe('действия с записями', () => {
  it('createItem: отправляет POST на /api/items?tz=... с телом и разбирает 201', async () => {
    const client = await freshClient(NEW_ID);
    const res = await client.createItem({ type: 'task', title: 'Новая задача' }, 'Europe/Moscow');
    expect(res.ok).toBe(true);
    expect(res.records[0].id).toBe('new-id');
    const lastCall = calls[calls.length - 1];
    expect(lastCall.url).toBe('/api/items?tz=Europe%2FMoscow');
    expect(lastCall.body).toEqual({ type: 'task', title: 'Новая задача' });
  });

  it('updateItem: отправляет PATCH на /api/items/{id}?tz=... и разбирает 200', async () => {
    const client = await freshClient(NEW_ID);
    const res = await client.updateItem('rec-123', { title: 'Обновлено' }, 'Europe/Moscow');
    expect(res.ok).toBe(true);
    const lastCall = calls[calls.length - 1];
    expect(lastCall.url).toBe('/api/items/rec-123?tz=Europe%2FMoscow');
    expect(lastCall.body).toEqual({ title: 'Обновлено' });
  });

  it('updateItem: 404 возвращает rejected с detail', async () => {
    const client = await freshClient(NEW_ID);
    await expect(client.updateItem('missing-id', { title: 'X' }, 'Europe/Moscow')).rejects.toMatchObject({
      kind: 'rejected',
      status: 404,
      detail: 'Запись не найдена',
    });
  });

  it('setItemStatus: отправляет POST на /api/items/{id}/status?tz=...', async () => {
    const client = await freshClient(NEW_ID);
    const res = await client.setItemStatus('rec-123', 'done', 'Europe/Moscow');
    expect(res.ok).toBe(true);
    const lastCall = calls[calls.length - 1];
    expect(lastCall.url).toBe('/api/items/rec-123/status?tz=Europe%2FMoscow');
    expect(lastCall.body).toEqual({ status: 'done' });
  });
});

describe('Google Календарь', () => {
  it('fetchGoogleCalendarStatus: у гостя (нет токена) возвращает null без запроса', async () => {
    const client = await freshClient(NEW_ID, null);
    const initialCallCount = calls.length;
    const status = await client.fetchGoogleCalendarStatus();

    expect(status).toBeNull();
    expect(calls.length).toBe(initialCallCount);
  });

  it('fetchGoogleCalendarStatus: у авторизованного возвращает статус с почтой и pending', async () => {
    const client = await freshClient(null, {
      token: 'jwt-123',
      account: { id: 'acc-1', login: 'demo', demo: false },
    });
    const status = await client.fetchGoogleCalendarStatus();

    expect(status).toEqual({
      state: 'connected',
      email: 'user@example.com',
      error: null,
      pending: 2,
    });
    const lastCall = calls[calls.length - 1];
    expect(lastCall.url).toBe('/api/calendar/google');
    expect(lastCall.authHeader).toBe('Bearer jwt-123');
  });

  it('connectGoogleCalendar: отправляет POST с tz и возвращает auth_url', async () => {
    const client = await freshClient(null, {
      token: 'jwt-123',
      account: { id: 'acc-1', login: 'demo', demo: false },
    });
    const url = await client.connectGoogleCalendar('Europe/Moscow');

    expect(url).toBe('https://accounts.google.com/auth-url');
    const lastCall = calls[calls.length - 1];
    expect(lastCall.url).toBe('/api/calendar/google/connect?tz=Europe%2FMoscow');
    expect(lastCall.authHeader).toBe('Bearer jwt-123');
  });

  it('disconnectGoogleCalendar: отправляет DELETE на /api/calendar/google', async () => {
    const client = await freshClient(null, {
      token: 'jwt-123',
      account: { id: 'acc-1', login: 'demo', demo: false },
    });
    await client.disconnectGoogleCalendar();

    const lastCall = calls[calls.length - 1];
    expect(lastCall.url).toBe('/api/calendar/google');
    expect(lastCall.authHeader).toBe('Bearer jwt-123');
  });
});

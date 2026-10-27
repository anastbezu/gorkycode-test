// Поведение клиента на поддельном сервере: что уходит в запросах и как клиент восстанавливается.
// fetch подменяется функцией, которая отвечает как бэкенд по api.md.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const NEW_ID = '9c5896b5-9632-4dda-8002-05fd22573310';

interface Call {
  url: string;
  userId: string | null;
  body: { conversation_id: string | null; llm_config?: unknown } | null;
}

let calls: Call[];

/** Сервер: без X-User-Id выдаёт NEW_ID; не-UUID — 400; разговор `gone` — 404. */
function fakeServer(delayMs = 5) {
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    const userId = headers.get('X-User-Id');
    const body = init.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, userId, body });
    await new Promise((r) => setTimeout(r, delayMs));
    const json = (status: number, data: unknown, extra: { [k: string]: string } = {}) =>
      new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...extra } });

    if (userId && !/^[0-9a-f-]{36}$/.test(userId)) return json(400, { detail: 'X-User-Id должен быть UUID' });
    const issued: { [k: string]: string } = userId ? {} : { 'X-User-Id': NEW_ID };
    if (url.startsWith('/api/items')) return json(200, [], issued);
    if (body?.conversation_id === 'gone') return json(404, { detail: 'Разговор не найден' });
    return json(200, { conversation_id: 'c1', reply: 'ок', result: null, awaiting: null }, issued);
  });
}

async function freshClient(storedUserId: string | null = null) {
  vi.resetModules();
  const data = new Map<string, string>(storedUserId ? [['gorky.userId', JSON.stringify(storedUserId)]] : []);
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

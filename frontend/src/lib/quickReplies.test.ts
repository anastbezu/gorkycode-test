import { describe, expect, it } from 'vitest';
import type { Record } from '../api/types';
import { resolveQuickReplies } from './quickReplies';

const TZ = 'Europe/Moscow';
const NOW = new Date('2026-10-30T10:00:00Z');

function makeRecord(partial: Partial<Record>): Record {
  return {
    id: 'rec-1',
    user_id: 'user-1',
    type: 'meeting',
    title: 'Планёрка',
    start: '2026-10-30T07:00:00Z',
    end: '2026-10-30T07:30:00Z',
    all_day: false,
    deadline: null,
    status: 'active',
    created_at: '2026-10-30T06:00:00Z',
    ...partial,
  };
}

describe('resolveQuickReplies', () => {
  it('awaiting = "time" возвращает 4 чипа с отправляемыми текстами по контракту', () => {
    const res = resolveQuickReplies('time', null, TZ, NOW);
    expect(res).not.toBeNull();
    expect(res?.kind).toBe('time');
    expect(res?.chips).toHaveLength(4);

    expect(res?.chips[0]).toEqual({
      id: 'time-09:00',
      label: '09:00',
      subLabel: 'утром',
      sendText: 'в 09:00',
      variant: 'time',
    });
    expect(res?.chips[1]).toEqual({
      id: 'time-13:00',
      label: '13:00',
      subLabel: 'в обед',
      sendText: 'в 13:00',
      variant: 'time',
    });
    expect(res?.chips[2]).toEqual({
      id: 'time-15:00',
      label: '15:00',
      subLabel: 'днём',
      sendText: 'в 15:00',
      variant: 'time',
    });
    expect(res?.chips[3]).toEqual({
      id: 'time-18:00',
      label: '18:00',
      subLabel: 'вечером',
      sendText: 'в 18:00',
      variant: 'time',
    });
  });

  it('awaiting = "choice" с 3 кандидатами возвращает чипы «номер 1..3» в порядке candidates', () => {
    const candidates = [
      makeRecord({ id: 'r1', title: 'Планёрка' }),
      makeRecord({ id: 'r2', title: 'Созвон с клиентом' }),
      makeRecord({ id: 'r3', title: 'Встреча с архитектором' }),
    ];

    const res = resolveQuickReplies('choice', candidates, TZ, NOW);
    expect(res).not.toBeNull();
    expect(res?.kind).toBe('choice');
    expect(res?.candidates).toHaveLength(3);
    expect(res?.chips).toHaveLength(3);

    expect(res?.chips[0].sendText).toBe('номер 1');
    expect(res?.chips[0].indexBadge).toBe(1);
    expect(res?.chips[0].label).toBe('Планёрка');

    expect(res?.chips[1].sendText).toBe('номер 2');
    expect(res?.chips[1].indexBadge).toBe(2);
    expect(res?.chips[1].label).toBe('Созвон с клиентом');

    expect(res?.chips[2].sendText).toBe('номер 3');
    expect(res?.chips[2].indexBadge).toBe(3);
    expect(res?.chips[2].label).toBe('Встреча с архитектором');
  });

  it('awaiting = "choice" без кандидатов возвращает null', () => {
    expect(resolveQuickReplies('choice', [], TZ, NOW)).toBeNull();
    expect(resolveQuickReplies('choice', null, TZ, NOW)).toBeNull();
  });

  it('awaiting = "confirm" возвращает кнопки «Да, все» и «Отмена»', () => {
    const candidates = [
      makeRecord({ id: 'r1', title: 'Дело 1' }),
      makeRecord({ id: 'r2', title: 'Дело 2' }),
    ];

    const res = resolveQuickReplies('confirm', candidates, TZ, NOW);
    expect(res).not.toBeNull();
    expect(res?.kind).toBe('confirm');
    expect(res?.candidates).toHaveLength(2);
    expect(res?.chips).toHaveLength(2);

    expect(res?.chips[0]).toEqual({
      id: 'confirm-yes',
      label: 'Да, все',
      sendText: 'да, все',
      variant: 'confirm-yes',
    });
    expect(res?.chips[1]).toEqual({
      id: 'confirm-cancel',
      label: 'Отмена',
      sendText: 'отмена',
      variant: 'confirm-cancel',
    });
  });

  it('awaiting = "answer" или null возвращает null', () => {
    expect(resolveQuickReplies('answer', [makeRecord({})], TZ, NOW)).toBeNull();
    expect(resolveQuickReplies(null, [makeRecord({})], TZ, NOW)).toBeNull();
  });
});

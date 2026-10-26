// Показ дат по правилам data-model.md («Правила») и постановки frontend-01 («Даты»).
// «Сейчас» и пояс задаются явно — результат не зависит от машины, где идут тесты.
import { describe, expect, it } from 'vitest';
import type { Record } from '../api/types';
import { addDaysToKey, dayKey, recordWhen, recordWhenInDay } from './dates';

const MSK = 'Europe/Moscow';
const TOKYO = 'Asia/Tokyo';
// Понедельник, 26 октября 2026, 12:00 по Москве
const NOW = new Date('2026-10-26T09:00:00Z');

function rec(fields: Partial<Record>): Record {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    user_id: '00000000-0000-0000-0000-000000000002',
    type: 'task',
    title: 'Запись',
    start: null,
    end: null,
    all_day: false,
    deadline: null,
    status: 'active',
    created_at: '2026-10-20T10:00:00Z',
    ...fields,
  };
}

describe('один момент в разной записи', () => {
  it('UTC из /api/chat и смещение из /api/items дают одно местное время', () => {
    const fromChat = rec({ start: '2026-10-26T13:45:00Z' });
    const fromItems = rec({ start: '2026-10-26T16:45:00+03:00' });
    expect(recordWhen(fromChat, MSK, NOW)).toBe('Сегодня · 16:45');
    expect(recordWhen(fromItems, MSK, NOW)).toBe('Сегодня · 16:45');
  });

  it('другой пояс браузера сдвигает время и день', () => {
    // 16:45 по Москве — 22:45 в Токио; «сейчас» в Токио — тоже 26-е
    expect(recordWhen(rec({ start: '2026-10-26T13:45:00Z' }), TOKYO, NOW)).toBe('Сегодня · 22:45');
    // 20:30 по Москве — 02:30 следующего дня в Токио
    expect(recordWhen(rec({ start: '2026-10-26T17:30:00Z' }), TOKYO, NOW)).toBe('Завтра, 27 октября · 02:30');
  });
});

describe('дни словами', () => {
  it('завтра — с датой', () => {
    expect(recordWhen(rec({ start: '2026-10-27T12:00:00Z' }), MSK, NOW)).toBe('Завтра, 27 октября · 15:00');
  });
  it('дальше — день недели и дата', () => {
    expect(recordWhen(rec({ start: '2026-10-30T09:30:00Z' }), MSK, NOW)).toBe('Пт, 30 октября · 12:30');
  });
  it('другой год — с годом', () => {
    expect(recordWhen(rec({ start: '2027-01-15T07:00:00Z' }), MSK, NOW)).toBe('Пт, 15 января 2027 · 10:00');
  });
  it('время 24-часовое с ведущим нулём', () => {
    expect(recordWhen(rec({ start: '2026-10-26T06:05:00Z' }), MSK, NOW)).toBe('Сегодня · 09:05');
  });
});

describe('весь день', () => {
  it('только дата, без 00:00', () => {
    // all_day: start — начало дня в поясе пользователя
    const r = rec({ start: '2026-10-28T00:00:00+03:00', all_day: true });
    expect(recordWhen(r, MSK, NOW)).toBe('Ср, 28 октября');
    expect(recordWhen(r, MSK, NOW)).not.toContain('00:00');
  });
  it('под заголовком дня — «весь день»', () => {
    const r = rec({ start: '2026-10-28T00:00:00+03:00', all_day: true });
    expect(recordWhenInDay(r, MSK, NOW)).toBe('весь день');
  });
});

describe('интервал', () => {
  it('встреча с окончанием — «15:00–16:30»', () => {
    const r = rec({ type: 'meeting', start: '2026-10-27T12:00:00Z', end: '2026-10-27T13:30:00Z' });
    expect(recordWhen(r, MSK, NOW)).toBe('Завтра, 27 октября · 15:00–16:30');
    expect(recordWhenInDay(r, MSK, NOW)).toBe('15:00–16:30');
  });
  it('через полночь — у конца своя дата', () => {
    const r = rec({ type: 'meeting', start: '2026-10-26T20:00:00Z', end: '2026-10-26T22:00:00Z' });
    expect(recordWhenInDay(r, MSK, NOW)).toBe('23:00 – 27 октября 01:00');
  });
});

describe('срок', () => {
  it('«до конца недели» — воскресенье 23:59:59, время не показывается', () => {
    const r = rec({ deadline: '2026-11-01T23:59:59+03:00' });
    expect(recordWhen(r, MSK, NOW)).toBe('до 1 ноября');
  });
  it('время срока не 23:59 — показывается', () => {
    const r = rec({ deadline: '2026-10-30T15:00:00Z' });
    expect(recordWhen(r, MSK, NOW)).toBe('до 30 октября, 18:00');
  });
  it('срок из UTC переводится в пояс до проверки на 23:59', () => {
    // 23:59 по Москве = 20:59 UTC
    expect(recordWhen(rec({ deadline: '2026-11-01T20:59:59Z' }), MSK, NOW)).toBe('до 1 ноября');
  });
  it('под заголовком дня срок показывается полностью', () => {
    expect(recordWhenInDay(rec({ deadline: '2026-11-01T23:59:59+03:00' }), MSK, NOW)).toBe('до 1 ноября');
  });
});

describe('без даты', () => {
  it('нет ни начала, ни срока', () => {
    expect(recordWhen(rec({}), MSK, NOW)).toBe('без даты');
    expect(recordWhenInDay(rec({}), MSK, NOW)).toBe('без даты');
  });
});

describe('ключи дней', () => {
  it('день — в поясе браузера', () => {
    expect(dayKey(new Date('2026-10-26T21:30:00Z'), MSK)).toBe('2026-10-27');
    expect(dayKey(new Date('2026-10-26T21:30:00Z'), 'Europe/London')).toBe('2026-10-26');
  });
  it('сдвиг через конец месяца и года', () => {
    expect(addDaysToKey('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDaysToKey('2026-12-28', 7)).toBe('2027-01-04');
  });
});

describe('календарь', () => {
  it('сетка октября 2026 — 5 недель с понедельника 28 сентября по воскресенье 1 ноября', async () => {
    const { monthGrid } = await import('./dates');
    const grid = monthGrid(2026, 10);
    expect(grid).toHaveLength(35);
    expect(grid[0]).toBe('2026-09-28');
    expect(grid[34]).toBe('2026-11-01');
  });
  it('месяц, начинающийся в понедельник и кончающийся в воскресенье, — без чужих дней', async () => {
    const { monthGrid } = await import('./dates');
    // Февраль 2027: 1-е — понедельник, 28-е — воскресенье
    const grid = monthGrid(2027, 2);
    expect(grid).toHaveLength(28);
    expect(grid[0]).toBe('2027-02-01');
  });
  it('декабрь переходит в январь следующего года', async () => {
    const { monthGrid } = await import('./dates');
    expect(monthGrid(2026, 12).at(-1)).toBe('2027-01-03');
  });
  it('заголовки: месяц и день словами', async () => {
    const { monthTitle, dayTitle, weekOf } = await import('./dates');
    expect(monthTitle(2026, 10)).toBe('Октябрь 2026');
    expect(dayTitle('2026-10-25', '2026-10-26')).toBe('Воскресенье, 25 октября');
    expect(dayTitle('2027-01-04', '2026-10-26')).toBe('Понедельник, 4 января 2027');
    expect(weekOf('2026-10-25')).toEqual([
      '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24', '2026-10-25',
    ]);
  });
});

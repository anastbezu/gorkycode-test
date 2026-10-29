import { describe, expect, it } from 'vitest';
import type { Record } from '../api/types';
import { activeTodayCount, activeUndatedCount, groupByDay, panelDayKeys } from './TasksPanel';

const MSK = 'Europe/Moscow';
const NOW = new Date('2026-10-26T09:00:00Z'); // 2026-10-26 12:00 MSK

function makeRec(fields: Partial<Record>): Record {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    user_id: '00000000-0000-0000-0000-000000000002',
    type: 'task',
    title: 'Задача',
    start: null,
    end: null,
    all_day: false,
    deadline: null,
    status: 'active',
    created_at: '2026-10-20T10:00:00Z',
    ...fields,
  };
}

describe('TasksPanel helpers', () => {
  it('panelDayKeys возвращает 5 дней от переданной даты', () => {
    const keys = panelDayKeys('2026-10-25', 5);
    expect(keys).toEqual(['2026-10-25', '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29']);
  });

  it('panelDayKeys возвращает 5 дней от сегодня при передаче пояса', () => {
    const keys = panelDayKeys(MSK, NOW);
    expect(keys).toEqual(['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30']);
  });

  it('activeUndatedCount считает только активные записи без даты', () => {
    const records: Record[] = [
      makeRec({ id: '1', title: 'Активная без срока', start: null, deadline: null, status: 'active' }),
      makeRec({ id: '2', title: 'Выполненная без срока', start: null, deadline: null, status: 'done' }),
      makeRec({ id: '3', title: 'Отмененная без срока', start: null, deadline: null, status: 'cancelled' }),
      makeRec({ id: '4', title: 'С датой старта', start: '2026-10-26T10:00:00Z', status: 'active' }),
      makeRec({ id: '5', title: 'Со сроком', deadline: '2026-10-26T18:00:00Z', status: 'active' }),
      makeRec({ id: '6', title: 'Вторая активная без срока', start: null, deadline: null, status: 'active' }),
    ];

    expect(activeUndatedCount(records)).toBe(2);
  });

  it('groupByDay разделяет записи по дням и в undated', () => {
    const records: Record[] = [
      makeRec({ id: '1', title: 'Без срока', start: null, deadline: null }),
      makeRec({ id: '2', title: 'Сегодня 10:00', start: '2026-10-26T07:00:00Z' }), // 10:00 MSK
      makeRec({ id: '3', title: 'Завтра', start: '2026-10-27T07:00:00Z' }),
    ];

    const { byDay, undated } = groupByDay(records, MSK);
    expect(undated).toHaveLength(1);
    expect(undated[0].title).toBe('Без срока');
    expect(byDay.get('2026-10-26')).toHaveLength(1);
    expect(byDay.get('2026-10-27')).toHaveLength(1);
  });

  it('activeTodayCount считает только активные записи на сегодня', () => {
    const records: Record[] = [
      makeRec({ id: '1', start: '2026-10-26T07:00:00Z', status: 'active' }),
      makeRec({ id: '2', start: '2026-10-26T08:00:00Z', status: 'done' }),
      makeRec({ id: '3', start: '2026-10-27T07:00:00Z', status: 'active' }),
      makeRec({ id: '4', start: null, status: 'active' }),
    ];

    expect(activeTodayCount(records, MSK, NOW)).toBe(1);
  });
});

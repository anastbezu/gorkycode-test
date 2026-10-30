import { describe, expect, it } from 'vitest';
import type { Record } from '../api/types';
import {
  LIST_COLLAPSE_LIMIT,
  buildListRows,
  formatExpandButtonText,
} from './ResultView';

const MSK = 'Europe/Moscow';
const NOW = new Date('2026-10-26T09:00:00Z');

function makeRec(id: string, title: string, start?: string): Record {
  return {
    id,
    user_id: 'user-1',
    type: 'task',
    title,
    start: start ?? null,
    end: null,
    all_day: false,
    deadline: null,
    status: 'active',
    created_at: '2026-10-26T09:00:00Z',
  };
}

describe('NumberedList — сворачивание длинного списка и нумерация', () => {
  it('константа ограничения равна 8 строкам', () => {
    expect(LIST_COLLAPSE_LIMIT).toBe(8);
  });

  it('список из 8 строк не сворачивается (hiddenCount = 0)', () => {
    const records = Array.from({ length: 8 }, (_, i) =>
      makeRec(`rec-${i + 1}`, `Дело ${i + 1}`),
    );
    const { visibleRows, hiddenCount } = buildListRows(records, MSK, NOW, false);

    expect(visibleRows).toHaveLength(8);
    expect(hiddenCount).toBe(0);
    expect(visibleRows.map((r) => r.displayIndex)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it('список из 9 строк в свёрнутом виде показывает 8 строк и «Показать ещё 1»', () => {
    const records = Array.from({ length: 9 }, (_, i) =>
      makeRec(`rec-${i + 1}`, `Дело ${i + 1}`),
    );
    const { visibleRows, hiddenCount } = buildListRows(records, MSK, NOW, false);

    expect(visibleRows).toHaveLength(8);
    expect(hiddenCount).toBe(1);
    expect(formatExpandButtonText(hiddenCount)).toBe('Показать ещё 1');
    expect(visibleRows.map((r) => r.displayIndex)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it('список из 34 строк в свёрнутом виде показывает 8 строк и «Показать ещё 26»', () => {
    const records = Array.from({ length: 34 }, (_, i) =>
      makeRec(`rec-${i + 1}`, `Дело ${i + 1}`),
    );
    const { visibleRows, hiddenCount } = buildListRows(records, MSK, NOW, false);

    expect(visibleRows).toHaveLength(8);
    expect(hiddenCount).toBe(26);
    expect(formatExpandButtonText(hiddenCount)).toBe('Показать ещё 26');
    expect(visibleRows.map((r) => r.displayIndex)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it('развёрнутый список из 34 строк показывает все строки подряд от 1 до 34', () => {
    const records = Array.from({ length: 34 }, (_, i) =>
      makeRec(`rec-${i + 1}`, `Дело ${i + 1}`),
    );
    const { visibleRows, hiddenCount } = buildListRows(records, MSK, NOW, true);

    expect(visibleRows).toHaveLength(34);
    expect(hiddenCount).toBe(0);
    const expectedIndices = Array.from({ length: 34 }, (_, i) => i + 1);
    expect(visibleRows.map((r) => r.displayIndex)).toEqual(expectedIndices);
  });

  it('заголовки дней группируют строки без нарушения нумерации 1..N', () => {
    const records = [
      makeRec('1', 'Сегодня дело 1', '2026-10-26T07:00:00Z'),
      makeRec('2', 'Сегодня дело 2', '2026-10-26T08:00:00Z'),
      makeRec('3', 'Завтра дело 3', '2026-10-27T07:00:00Z'),
      makeRec('4', 'Завтра дело 4', '2026-10-27T08:00:00Z'),
      makeRec('5', 'Среда дело 5', '2026-10-28T07:00:00Z'),
    ];

    const { visibleRows } = buildListRows(records, MSK, NOW, false);
    expect(visibleRows).toHaveLength(5);
    expect(visibleRows[0].dayHeader).toBe('Сегодня, 26 октября');
    expect(visibleRows[0].displayIndex).toBe(1);
    expect(visibleRows[1].dayHeader).toBeUndefined();
    expect(visibleRows[1].displayIndex).toBe(2);
    expect(visibleRows[2].dayHeader).toBe('Завтра, 27 октября');
    expect(visibleRows[2].displayIndex).toBe(3);
    expect(visibleRows[3].dayHeader).toBeUndefined();
    expect(visibleRows[3].displayIndex).toBe(4);
    expect(visibleRows[4].dayHeader).toBe('Среда, 28 октября');
    expect(visibleRows[4].displayIndex).toBe(5);
  });

  it('confirm с 12 кандидатами сворачивает список до 8 и оставляет 4 скрытыми', () => {
    const records = Array.from({ length: 12 }, (_, i) =>
      makeRec('rec-' + (i + 1), 'Дело ' + (i + 1)),
    );
    const { visibleRows, hiddenCount } = buildListRows(records, MSK, NOW, false);

    expect(visibleRows).toHaveLength(8);
    expect(hiddenCount).toBe(4);
    expect(formatExpandButtonText(hiddenCount)).toBe('Показать ещё 4');
  });
});

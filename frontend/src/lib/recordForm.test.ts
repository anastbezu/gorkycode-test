import { describe, expect, it } from 'vitest';
import type { Record } from '../api/types';
import { buildCreateItem, buildUpdateItem, initialFormValues } from './recordForm';

const MSK = 'Europe/Moscow';

function makeRec(fields: Partial<Record>): Record {
  return {
    id: 'rec-1',
    user_id: 'user-1',
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

describe('buildCreateItem', () => {
  it('пустое название — ошибка', () => {
    const res = buildCreateItem({
      type: 'task',
      title: '   ',
      day: '',
      time: '',
      allDay: false,
      deadlineDay: '',
      deadlineTime: '',
    });
    expect(res.valid).toBe(false);
    expect(res.error).toBe('Введите название');
  });

  it('встреча без времени или дня — ошибка', () => {
    const res1 = buildCreateItem({
      type: 'meeting',
      title: 'Встреча',
      day: '2026-10-31',
      time: '',
      allDay: false,
      deadlineDay: '',
      deadlineTime: '',
    });
    expect(res1.valid).toBe(false);
    expect(res1.error).toBe('Для встречи нужны день и время');

    const res2 = buildCreateItem({
      type: 'meeting',
      title: 'Встреча',
      day: '',
      time: '15:00',
      allDay: false,
      deadlineDay: '',
      deadlineTime: '',
    });
    expect(res2.valid).toBe(false);
  });

  it('напоминание без дня — ошибка', () => {
    const res = buildCreateItem({
      type: 'reminder',
      title: 'Полить цветы',
      day: '',
      time: '',
      allDay: false,
      deadlineDay: '',
      deadlineTime: '',
    });
    expect(res.valid).toBe(false);
    expect(res.error).toBe('Для напоминания нужен день');
  });

  it('успешное создание встречи', () => {
    const res = buildCreateItem({
      type: 'meeting',
      title: 'Синхрон',
      day: '2026-10-31',
      time: '14:30',
      allDay: false,
      deadlineDay: '',
      deadlineTime: '',
    });
    expect(res.valid).toBe(true);
    expect(res.item?.type).toBe('meeting');
    expect(res.item?.title).toBe('Синхрон');
    expect(res.item?.time_given).toBe(true);
    expect(res.item?.start).toContain('2026-10-31T14:30:00');
  });

  it('задача со сроком без времени — конец дня 23:59', () => {
    const res = buildCreateItem({
      type: 'task',
      title: 'Сдать отчёт',
      day: '',
      time: '',
      allDay: false,
      deadlineDay: '2026-11-05',
      deadlineTime: '',
    });
    expect(res.valid).toBe(true);
    expect(res.item?.deadline).toContain('2026-11-05T23:59:00');
  });
});

describe('buildUpdateItem', () => {
  it('нет изменений — item равен null', () => {
    const rec = makeRec({ title: 'Купить хлеб' });
    const values = initialFormValues(rec, MSK);
    const res = buildUpdateItem(rec, values, MSK);
    expect(res.valid).toBe(true);
    expect(res.item).toBeNull();
  });

  it('изменено только название', () => {
    const rec = makeRec({ title: 'Купить хлеб' });
    const values = { ...initialFormValues(rec, MSK), title: 'Купить батон' };
    const res = buildUpdateItem(rec, values, MSK);
    expect(res.valid).toBe(true);
    expect(res.item).toEqual({ title: 'Купить батон' });
  });

  it('перенос встречи не передаёт end', () => {
    const rec = makeRec({
      type: 'meeting',
      title: 'Встреча',
      start: '2026-10-26T12:00:00Z',
      end: '2026-10-26T13:00:00Z',
    });
    const values = { ...initialFormValues(rec, MSK), time: '16:00' };
    const res = buildUpdateItem(rec, values, MSK);
    expect(res.valid).toBe(true);
    expect(res.item?.start).toContain('16:00:00');
    expect(res.item?.time_given).toBe(true);
    expect(res.item).not.toHaveProperty('end');
  });
});

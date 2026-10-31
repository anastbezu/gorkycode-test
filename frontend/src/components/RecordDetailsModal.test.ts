import { describe, expect, it } from 'vitest';
import type { Record } from '../api/types';
import { formatRecordDay, formatRecordTimeRange } from './RecordDetailsModal';

describe('RecordDetailsModal helpers', () => {
  it('formatRecordTimeRange: all_day returns весь день', () => {
    const r: Record = {
      id: '1',
      user_id: 'u1',
      type: 'task',
      title: 'Test',
      status: 'active',
      start: null,
      end: null,
      deadline: null,
      all_day: true,
      created_at: '2026-10-25T10:00:00Z',
    };
    expect(formatRecordTimeRange(r, 'Europe/Moscow')).toBe('весь день');
  });

  it('formatRecordTimeRange: start and end returns range', () => {
    const r: Record = {
      id: '2',
      user_id: 'u1',
      type: 'meeting',
      title: 'Meeting',
      status: 'active',
      start: '2026-10-25T11:00:00Z',
      end: '2026-10-25T12:00:00Z',
      deadline: null,
      all_day: false,
      created_at: '2026-10-25T10:00:00Z',
    };
    // in UTC: 11:00–12:00, in Europe/Moscow (+3): 14:00–15:00
    expect(formatRecordTimeRange(r, 'Europe/Moscow')).toBe('14:00–15:00');
  });

  it('formatRecordDay: returns formatted title', () => {
    const r: Record = {
      id: '3',
      user_id: 'u1',
      type: 'task',
      title: 'No date',
      status: 'active',
      start: null,
      end: null,
      deadline: null,
      all_day: false,
      created_at: '2026-10-25T10:00:00Z',
    };
    expect(formatRecordDay(r, 'Europe/Moscow')).toBe('без срока');
  });
});

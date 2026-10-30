import { describe, expect, it } from 'vitest';
import { formatWeekTitle } from './CalendarView';

describe('CalendarView helper functions', () => {
  it('formats week title within single month', () => {
    const week = [
      '2026-10-19',
      '2026-10-20',
      '2026-10-21',
      '2026-10-22',
      '2026-10-23',
      '2026-10-24',
      '2026-10-25',
    ];
    const title = formatWeekTitle(week);
    expect(title).toBe('19 – 25 октября 2026');
  });

  it('formats week title across two months', () => {
    const week = [
      '2026-10-26',
      '2026-10-27',
      '2026-10-28',
      '2026-10-29',
      '2026-10-30',
      '2026-10-31',
      '2026-11-01',
    ];
    const title = formatWeekTitle(week);
    expect(title).toContain('26 октября');
    expect(title).toContain('1 ноября');
  });
});

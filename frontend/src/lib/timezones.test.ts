import { describe, expect, it } from 'vitest';
import {
  findTimezone,
  formatTzLabel,
  getTimezoneOffset,
  searchTimezones,
} from './timezones';

describe('timezones', () => {
  it('contains popular Russian timezones', () => {
    expect(findTimezone('Europe/Moscow')?.city).toBe('Москва');
    expect(findTimezone('Asia/Yekaterinburg')?.city).toBe('Екатеринбург');
    expect(findTimezone('Asia/Novosibirsk')?.city).toBe('Новосибирск');
    expect(findTimezone('Europe/Kaliningrad')?.city).toBe('Калининград');
  });

  it('formats timezone label properly', () => {
    const label = formatTzLabel('Europe/Moscow');
    expect(label).toContain('Москва');
    expect(label).toMatch(/UTC\+3/);
  });

  it('searches by city and abbreviation', () => {
    const byEkat = searchTimezones('екат');
    expect(byEkat.length).toBeGreaterThan(0);
    expect(byEkat[0].iana).toBe('Asia/Yekaterinburg');

    const byMoscow = searchTimezones('москва');
    expect(byMoscow.some((t) => t.iana === 'Europe/Moscow')).toBe(true);

    const byOffset = searchTimezones('UTC+7');
    expect(byOffset.some((t) => t.iana === 'Asia/Novosibirsk')).toBe(true);
  });

  it('returns empty array for empty search', () => {
    expect(searchTimezones('')).toEqual([]);
    expect(searchTimezones('   ')).toEqual([]);
  });

  it('calculates fallback or dynamic offset', () => {
    const offset = getTimezoneOffset('Europe/Moscow');
    expect(offset).toMatch(/UTC\+3/);
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Record } from '../api/types';
import {
  checkUpcomingReminders,
  formatReminderBody,
  getNotificationStatus,
  requestNotificationPermission,
} from './notifications';

describe('notifications', () => {
  let mockNotificationConstructor: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockNotificationConstructor = vi.fn();
    vi.stubGlobal('Notification', mockNotificationConstructor as unknown as typeof Notification);
    (Notification as unknown as { permission: string }).permission = 'granted';
    (Notification as unknown as { requestPermission: () => Promise<string> }).requestPermission =
      vi.fn().mockResolvedValue('granted');
  });

  it('checks status correctly', () => {
    expect(getNotificationStatus()).toBe('granted');
  });

  it('requests permission', async () => {
    const res = await requestNotificationPermission();
    expect(res).toBe('granted');
  });

  it('formats reminder body for 0 and 15 mins', () => {
    const rec: Record = {
      id: 'rec-1',
      user_id: 'u-1',
      title: 'Планёрка',
      type: 'meeting',
      status: 'active',
      start: '2026-10-30T10:00:00Z',
      end: '2026-10-30T10:30:00Z',
      deadline: null,
      all_day: false,
      created_at: '2026-10-30T09:00:00Z',
    };

    const body0 = formatReminderBody(rec, 0, 'UTC');
    expect(body0).toContain('Сейчас');
    expect(body0).toContain('10:00');

    const body15 = formatReminderBody(rec, 15, 'UTC');
    expect(body15).toContain('Через 15 мин');
    expect(body15).toContain('10:00');
  });

  it('triggers notification in the matching window', () => {
    const notified = new Set<string>();
    const rec: Record = {
      id: 'rec-meeting',
      user_id: 'u-1',
      title: 'Встреча с Игорем',
      type: 'meeting',
      status: 'active',
      start: '2026-10-30T15:00:00Z',
      end: '2026-10-30T16:00:00Z',
      deadline: null,
      all_day: false,
      created_at: '2026-10-30T09:00:00Z',
    };

    // Exactly 15 minutes before 15:00 is 14:45
    const now = new Date('2026-10-30T14:45:30Z');
    checkUpcomingReminders([rec], 15, notified, 'UTC', now);

    expect(mockNotificationConstructor).toHaveBeenCalledTimes(1);
    expect(notified.size).toBe(1);

    // Second check within the same window does not notify again
    checkUpcomingReminders([rec], 15, notified, 'UTC', now);
    expect(mockNotificationConstructor).toHaveBeenCalledTimes(1);
  });

  it('ignores all_day and task types', () => {
    const notified = new Set<string>();
    const task: Record = {
      id: 'rec-task',
      user_id: 'u-1',
      title: 'Отчёт',
      type: 'task',
      status: 'active',
      start: '2026-10-30T15:00:00Z',
      end: null,
      deadline: null,
      all_day: false,
      created_at: '2026-10-30T09:00:00Z',
    };

    const now = new Date('2026-10-30T14:45:00Z');
    checkUpcomingReminders([task], 15, notified, 'UTC', now);
    expect(mockNotificationConstructor).not.toHaveBeenCalled();
  });
});

import type { Record } from '../api/types';
import { recordAnchor } from './dates';

export type NotificationStatus = 'default' | 'granted' | 'denied' | 'unsupported';

export function getNotificationStatus(): NotificationStatus {
  if (typeof globalThis === 'undefined' || !('Notification' in globalThis)) {
    return 'unsupported';
  }
  return Notification.permission as NotificationStatus;
}

export async function requestNotificationPermission(): Promise<NotificationStatus> {
  if (typeof globalThis === 'undefined' || !('Notification' in globalThis)) {
    return 'unsupported';
  }
  try {
    const res = await Notification.requestPermission();
    return res as NotificationStatus;
  } catch {
    return 'denied';
  }
}

export function formatReminderBody(record: Record, leadMinutes: number, tz: string): string {
  const anchor = recordAnchor(record);
  let timeStr = '';
  if (anchor) {
    try {
      timeStr = new Intl.DateTimeFormat('ru-RU', {
        timeZone: tz,
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(anchor));
    } catch {}
  }

  if (leadMinutes === 0) {
    return timeStr ? `Сейчас в ${timeStr}` : 'Сейчас';
  }
  return timeStr ? `Через ${leadMinutes} мин в ${timeStr}` : `Через ${leadMinutes} мин`;
}

export function showNotification(record: Record, leadMinutes: number, tz: string): void {
  if (getNotificationStatus() !== 'granted') return;
  const typeTitle = record.type === 'meeting' ? 'Встреча' : 'Напоминание';
  const title = `${typeTitle}: ${record.title}`;
  const body = formatReminderBody(record, leadMinutes, tz);

  try {
    new Notification(title, {
      body,
      icon: '/favicon.ico',
    });
  } catch {}
}

/**
 * Проверить ближайшие записи и показать уведомления.
 * Задачи без времени и события на весь день не напоминаются.
 */
export function checkUpcomingReminders(
  records: Record[],
  leadMinutes: number,
  notifiedIds: Set<string>,
  tz: string,
  now: Date = new Date(),
): void {
  if (getNotificationStatus() !== 'granted') return;

  const nowMs = now.getTime();
  const twoMinutesMs = 2 * 60 * 1000;

  for (const record of records) {
    if (record.status !== 'active') continue;
    if (record.type !== 'meeting' && record.type !== 'reminder') continue;
    if (record.all_day) continue;

    const anchor = recordAnchor(record);
    if (!anchor) continue;

    const eventTime = Date.parse(anchor);
    if (isNaN(eventTime)) continue;

    const alertTime = eventTime - leadMinutes * 60 * 1000;
    // Окно срабатывания: от alertTime до alertTime + 2 минуты
    if (nowMs >= alertTime && nowMs <= alertTime + twoMinutesMs) {
      const key = `${record.id}_${alertTime}`;
      if (!notifiedIds.has(key)) {
        notifiedIds.add(key);
        showNotification(record, leadMinutes, tz);
      }
    }
  }
}

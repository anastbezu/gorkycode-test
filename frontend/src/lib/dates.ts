// Показ дат записей словами — как в макете: «Сегодня · 10:00», «Завтра, 26 октября · 15:00»,
// «Пт, 30 октября · 12:30», «до 25 октября», «без даты».
//
// Сервер присылает моменты времени в разной записи: /api/chat — в UTC (`...Z`),
// /api/items — со смещением пояса (`...+03:00`). Это один и тот же момент, поэтому
// всё переводится в пояс браузера через Intl и дальше работает только с его «стенными» частями.
// Все функции принимают пояс и «сейчас» параметрами — так их можно проверить тестами.

import type { Record } from '../api/types';

const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];
const WEEKDAYS_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

/** Пояс браузера, IANA-имя (`Europe/Moscow`). Уходит в `timezone` и `tz`. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Части момента времени «на стенных часах» в поясе `tz`. */
export interface WallTime {
  year: number;
  month: number; // 1–12
  day: number;
  hour: number;
  minute: number;
}

const partsFormatters = new Map<string, Intl.DateTimeFormat>();

export function wallTime(moment: Date, tz: string): WallTime {
  let fmt = partsFormatters.get(tz);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric', hourCycle: 'h23',
    });
    partsFormatters.set(tz, fmt);
  }
  const get = (type: string) =>
    Number(fmt!.formatToParts(moment).find((p) => p.type === type)?.value);
  return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour'), minute: get('minute') };
}

/** Ключ календарного дня `YYYY-MM-DD` в поясе `tz` — для группировки по дням. */
export function dayKey(moment: Date, tz: string): string {
  const w = wallTime(moment, tz);
  return `${w.year}-${pad(w.month)}-${pad(w.day)}`;
}

/** Сдвиг ключа дня на `days` календарных дней (без учёта поясов — это просто дата). */
export function addDaysToKey(key: string, days: number): string {
  const [y, m, d] = key.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

/** День недели по ключу дня: 0 — воскресенье. */
export function weekdayOfKey(key: string): number {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

export function weekdayShort(key: string): string {
  return WEEKDAYS_SHORT[weekdayOfKey(key)];
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function timeText(w: WallTime): string {
  return `${pad(w.hour)}:${pad(w.minute)}`;
}

/** Срок «до конца дня» хранится как 23:59(:59) — время такого срока не показывается. */
function isEndOfDay(w: WallTime): boolean {
  return w.hour === 23 && w.minute === 59;
}

/** «26 октября», для другого года — «26 октября 2027». */
function dateText(key: string, todayKey: string): string {
  const [y, m, d] = key.split('-').map(Number);
  const sameYear = y === Number(todayKey.slice(0, 4));
  return `${d} ${MONTHS_GENITIVE[m - 1]}${sameYear ? '' : ` ${y}`}`;
}

/**
 * Название дня: «Сегодня», «Завтра, 26 октября», «Пт, 30 октября», «Пт, 30 октября 2027».
 * Вчера и раньше — днём недели и датой: «Вчера» в макете нет.
 */
export function dayLabel(key: string, todayKey: string): string {
  if (key === todayKey) return 'Сегодня';
  if (key === addDaysToKey(todayKey, 1)) return `Завтра, ${dateText(key, todayKey)}`;
  return `${weekdayShort(key)}, ${dateText(key, todayKey)}`;
}

/** Время записи без даты: «15:00», «15:00–16:30», «весь день». Для строк под заголовком дня. */
export function recordTime(record: Record, tz: string): string | null {
  if (!record.start) return null;
  if (record.all_day) return 'весь день';
  const start = wallTime(new Date(record.start), tz);
  if (!record.end) return timeText(start);
  const endMoment = new Date(record.end);
  const end = wallTime(endMoment, tz);
  const sameDay = dayKey(new Date(record.start), tz) === dayKey(endMoment, tz);
  // Встреча через полночь — у конца своя дата, иначе «23:00–01:00» читается как ошибка
  return sameDay
    ? `${timeText(start)}–${timeText(end)}`
    : `${timeText(start)} – ${dayLabelShort(dayKey(endMoment, tz))} ${timeText(end)}`;
}

function dayLabelShort(key: string): string {
  const [, m, d] = key.split('-').map(Number);
  return `${d} ${MONTHS_GENITIVE[m - 1]}`;
}

/** «до 25 октября», «до 25 октября, 18:00» — срок задачи без начала. */
function deadlineText(record: Record, tz: string, todayKey: string): string {
  const moment = new Date(record.deadline!);
  const w = wallTime(moment, tz);
  const base = `до ${dateText(dayKey(moment, tz), todayKey)}`;
  return isEndOfDay(w) ? base : `${base}, ${timeText(w)}`;
}

/**
 * Когда — полностью, для карточек и строк без заголовка дня:
 * «Сегодня · 10:00», «Завтра, 26 октября · 15:00–16:30», «Пт, 30 октября» (весь день),
 * «до 25 октября», «без даты».
 */
export function recordWhen(record: Record, tz: string, now: Date = new Date()): string {
  const todayKey = dayKey(now, tz);
  if (record.start) {
    const label = dayLabel(dayKey(new Date(record.start), tz), todayKey);
    return record.all_day ? label : `${label} · ${recordTime(record, tz)}`;
  }
  if (record.deadline) return deadlineText(record, tz, todayKey);
  return 'без даты';
}

/**
 * Когда — для строки под заголовком дня: дата уже в заголовке, остаётся время.
 * Срок и «без даты» показываются полностью — у них нет времени начала.
 */
export function recordWhenInDay(record: Record, tz: string, now: Date = new Date()): string {
  if (record.start) return recordTime(record, tz)!;
  return recordWhen(record, tz, now);
}

/** Момент, по которому запись раскладывается по дням: начало, а если его нет — срок. */
export function recordAnchor(record: Record): string | null {
  return record.start ?? record.deadline;
}

/**
 * Локальная полночь дня `key` в ISO 8601 со смещением, напр. `2026-10-26T00:00:00+03:00`.
 * Смещение — своё для этой даты (переход на летнее время меняет его).
 * Пояс браузера совпадает с локальным поясом `Date`, поэтому считаем через `new Date(y, m, d)`.
 */
export function localMidnightIso(key: string): string {
  const [y, m, d] = key.split('-').map(Number);
  const midnight = new Date(y, m - 1, d);
  const offsetMin = -midnight.getTimezoneOffset();
  const sign = offsetMin >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMin);
  const hh = pad(midnight.getHours());
  const mm = pad(midnight.getMinutes());
  return `${key}T${hh}:${mm}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

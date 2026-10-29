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
export function localDateTimeIso(key: string, time = '00:00'): string {
  const [year, month, day] = key.split('-').map(Number);
  const [hStr, mStr] = time.split(':');
  const hours = Number(hStr) || 0;
  const minutes = Number(mStr) || 0;
  const dt = new Date(year, month - 1, day, hours, minutes, 0);
  const offsetMin = -dt.getTimezoneOffset();
  const sign = offsetMin >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMin);
  const hh = pad(dt.getHours());
  const mm = pad(dt.getMinutes());
  return `${key}T${hh}:${mm}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export function localMidnightIso(key: string): string {
  return localDateTimeIso(key, '00:00');
}

export function recordDayKey(record: Record, tz: string): string | null {
  const anchor = recordAnchor(record);
  return anchor ? dayKey(new Date(anchor), tz) : null;
}

export function recordTimeField(record: Record, tz: string): string {
  if (!record.start || record.all_day) return '';
  const w = wallTime(new Date(record.start), tz);
  return `${pad(w.hour)}:${pad(w.minute)}`;
}

export function recordDeadlineField(record: Record, tz: string): { day: string; time: string } | null {
  if (!record.deadline) return null;
  const moment = new Date(record.deadline);
  const w = wallTime(moment, tz);
  const day = dayKey(moment, tz);
  const time = isEndOfDay(w) ? '' : `${pad(w.hour)}:${pad(w.minute)}`;
  return { day, time };
}

const MONTHS_NOMINATIVE = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
const WEEKDAYS_FULL = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'];

/** «Октябрь 2026» — заголовок месяца в календаре. */
export function monthTitle(year: number, month: number): string {
  return `${MONTHS_NOMINATIVE[month - 1]} ${year}`;
}

/** «Воскресенье, 25 октября», другой год — с годом. Заголовок дня в календаре. */
export function dayTitle(key: string, todayKey: string): string {
  return `${WEEKDAYS_FULL[weekdayOfKey(key)]}, ${dateText(key, todayKey)}`;
}

/** Номер дня недели с понедельника: 0 — Пн, 6 — Вс. */
export function mondayIndex(key: string): number {
  return (weekdayOfKey(key) + 6) % 7;
}

/**
 * Дни сетки месяца — целые недели с понедельника по воскресенье, от недели с 1-м числом
 * до недели с последним. Дни соседних месяцев входят, чтобы строки были полными.
 */
export function monthGrid(year: number, month: number): string[] {
  const first = `${year}-${pad(month)}-01`;
  const start = addDaysToKey(first, -mondayIndex(first));
  const nextMonthFirst = month === 12 ? `${year + 1}-01-01` : `${year}-${pad(month + 1)}-01`;
  const days: string[] = [];
  for (let key = start; key < nextMonthFirst || days.length % 7 !== 0; key = addDaysToKey(key, 1)) {
    days.push(key);
  }
  return days;
}

/** Неделя (Пн–Вс), в которой лежит день. */
export function weekOf(key: string): string[] {
  const start = addDaysToKey(key, -mondayIndex(key));
  return Array.from({ length: 7 }, (_, i) => addDaysToKey(start, i));
}

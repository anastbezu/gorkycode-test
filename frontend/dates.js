// dates.js — правила форматирования дат и времени по контракту data-model.md и frontend-01.md

const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
];

const WEEKDAYS_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

export function getBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Moscow';
  } catch (e) {
    return 'Europe/Moscow';
  }
}

/**
 * Парсит ISO-строку с учетом смещения и приводит к Date
 */
export function parseIsoDate(isoStr) {
  if (!isoStr) return null;
  return new Date(isoStr);
}

/**
 * 24-часовое время (HH:MM)
 */
export function formatTime(date, timeZone) {
  if (!date) return '';
  const tz = timeZone || getBrowserTimezone();
  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: tz
  }).format(date);
}

/**
 * Форматирование даты словами по правилам ТЗ:
 * - «Сегодня · 10:00»
 * - «Завтра, 26 октября · 15:00»
 * - «Пт, 30 октября · 12:30»
 * - `all_day`: только дата, без времени
 * - `end`: интервал «15:00–16:30»
 * - `start` пуст, `deadline` есть: «до 25 октября» (если не 23:59:59)
 * - `start` и `deadline` пусты: «без даты»
 */
export function formatRecordDate(record, timeZone) {
  const tz = timeZone || getBrowserTimezone();

  if (!record.start && !record.deadline) {
    return 'без даты';
  }

  // Если start нет, но есть deadline
  if (!record.start && record.deadline) {
    const dDate = parseIsoDate(record.deadline);
    const dayStr = formatDateWords(dDate, tz);
    const hours = dDate.getHours();
    const mins = dDate.getMinutes();
    const isEndOfDay = (hours === 23 && mins >= 59);

    if (isEndOfDay) {
      return `до ${dayStr}`;
    } else {
      const timeStr = formatTime(dDate, tz);
      return `до ${dayStr} · ${timeStr}`;
    }
  }

  const sDate = parseIsoDate(record.start);
  const dayStr = formatDateWords(sDate, tz);

  // all_day = true: время не показываем вообще
  if (record.all_day) {
    return dayStr;
  }

  // Время начала
  const startTimeStr = formatTime(sDate, tz);

  // Интервал end
  if (record.end) {
    const eDate = parseIsoDate(record.end);
    const endTimeStr = formatTime(eDate, tz);
    return `${dayStr} · ${startTimeStr}–${endTimeStr}`;
  }

  return `${dayStr} · ${startTimeStr}`;
}

/**
 * Возвращает «Сегодня», «Завтра», «Пт, 30 октября» и т.п.
 */
export function formatDateWords(date, timeZone) {
  const tz = timeZone || getBrowserTimezone();
  const now = new Date();

  const nowParts = getDateParts(now, tz);
  const targetParts = getDateParts(date, tz);

  const diffDays = getCalendarDayDiff(nowParts, targetParts);

  if (diffDays === 0) {
    return 'Сегодня';
  } else if (diffDays === 1) {
    return `Завтра, ${targetParts.day} ${MONTHS_GENITIVE[targetParts.month]}`;
  } else if (diffDays === -1) {
    return `Вчера, ${targetParts.day} ${MONTHS_GENITIVE[targetParts.month]}`;
  }

  const weekday = WEEKDAYS_SHORT[targetParts.weekday];
  const yearStr = targetParts.year !== nowParts.year ? ` ${targetParts.year}` : '';
  return `${weekday}, ${targetParts.day} ${MONTHS_GENITIVE[targetParts.month]}${yearStr}`;
}

/**
 * Вспомогательное: части даты в заданном часовом поясе
 */
export function getDateParts(date, timeZone) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    weekday: 'short'
  });

  const parts = formatter.formatToParts(date);
  const res = {};
  for (const p of parts) {
    if (p.type === 'year') res.year = parseInt(p.value, 10);
    if (p.type === 'month') res.month = parseInt(p.value, 10) - 1;
    if (p.type === 'day') res.day = parseInt(p.value, 10);
  }

  res.weekday = date.getDay();
  return res;
}

function getCalendarDayDiff(p1, p2) {
  const d1 = new Date(Date.UTC(p1.year, p1.month, p1.day));
  const d2 = new Date(Date.UTC(p2.year, p2.month, p2.day));
  return Math.round((d2 - d1) / (1000 * 60 * 60 * 24));
}

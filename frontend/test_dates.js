// test_dates.js — тесты форматирования дат по критериям frontend-01.md

import { formatRecordDate, getBrowserTimezone } from './dates.js';

function assert(condition, message) {
  if (!condition) {
    console.error('FAIL:', message);
    throw new Error(message);
  } else {
    console.log('PASS:', message);
  }
}

console.log('=== Запуск тестов дат и времени ===');
const tz = 'Europe/Moscow';

// 1. «Без даты»
const recUndated = { start: null, deadline: null };
assert(formatRecordDate(recUndated, tz) === 'без даты', 'без даты отображается верно');

// 2. «all_day = true» (время не показывается, только дата)
const recAllDay = {
  start: '2026-10-30T00:00:00+03:00',
  all_day: true
};
const resAllDay = formatRecordDate(recAllDay, tz);
assert(!resAllDay.includes('00:00'), 'all_day не показывает время 00:00');
assert(resAllDay.includes('30 октября'), 'all_day содержит дату');

// 3. Срок «до …» (23:59 не показывается)
const recDeadline2359 = {
  start: null,
  deadline: '2026-10-25T23:59:59+03:00'
};
const resDeadline = formatRecordDate(recDeadline2359, tz);
assert(!resDeadline.includes('23:59'), 'срок на 23:59 не показывает время');
assert(resDeadline.startsWith('до '), 'срок начинается со слова "до"');

// 4. Интервал с end («15:00–16:30»)
const recInterval = {
  start: '2026-10-30T15:00:00+03:00',
  end: '2026-10-30T16:30:00+03:00',
  all_day: false
};
const resInterval = formatRecordDate(recInterval, tz);
assert(resInterval.includes('15:00–16:30'), 'интервал с end формирует 15:00–16:30');

// 5. UTC и смещение дают одно и то же местное время
const recUtc = {
  start: '2026-10-30T12:00:00Z',
  all_day: false
};
const recOffset = {
  start: '2026-10-30T15:00:00+03:00',
  all_day: false
};
assert(formatRecordDate(recUtc, tz) === formatRecordDate(recOffset, tz), 'UTC и пояс дают одинаковое местное время');

console.log('=== Все проверки успешно пройдены! ===');

import type { CreateItem, Record, RecordType, UpdateItem } from '../api/types';
import {
  localDateTimeIso,
  localMidnightIso,
  recordDayKey,
  recordDeadlineField,
  recordTimeField,
} from './dates';

export interface RecordFormValues {
  type: RecordType;
  title: string;
  day: string;
  time: string;
  allDay: boolean;
  deadlineDay: string;
  deadlineTime: string;
}

export interface BuildResult<T> {
  valid: boolean;
  item: T | null;
  error?: string;
}

export function initialFormValues(record?: Record | null, tz?: string): RecordFormValues {
  if (!record || !tz) {
    return {
      type: 'task',
      title: '',
      day: '',
      time: '',
      allDay: false,
      deadlineDay: '',
      deadlineTime: '',
    };
  }
  const dl = recordDeadlineField(record, tz);
  return {
    type: record.type,
    title: record.title,
    day: recordDayKey(record, tz) ?? '',
    time: recordTimeField(record, tz),
    allDay: Boolean(record.all_day),
    deadlineDay: dl?.day ?? '',
    deadlineTime: dl?.time ?? '',
  };
}

export function buildCreateItem(values: RecordFormValues): BuildResult<CreateItem> {
  const title = values.title.trim();
  if (!title) {
    return { valid: false, item: null, error: 'Введите название' };
  }

  if (values.type === 'meeting') {
    if (!values.day || !values.time) {
      return { valid: false, item: null, error: 'Для встречи нужны день и время' };
    }
  }

  if (values.type === 'reminder') {
    if (!values.day) {
      return { valid: false, item: null, error: 'Для напоминания нужен день' };
    }
  }

  const item: CreateItem = {
    type: values.type,
    title,
  };

  if (values.day) {
    if (values.type === 'meeting') {
      item.start = localDateTimeIso(values.day, values.time);
      item.time_given = true;
    } else if (values.allDay) {
      item.start = localMidnightIso(values.day);
      item.time_given = false;
    } else if (values.time) {
      item.start = localDateTimeIso(values.day, values.time);
      item.time_given = true;
    } else {
      item.start = localMidnightIso(values.day);
      item.time_given = false;
    }
  }

  if (values.type === 'task' && values.deadlineDay) {
    const time = values.deadlineTime ? values.deadlineTime : '23:59';
    item.deadline = localDateTimeIso(values.deadlineDay, time);
  }

  return { valid: true, item };
}

export function buildUpdateItem(
  original: Record,
  values: RecordFormValues,
  tz: string,
): BuildResult<UpdateItem> {
  const title = values.title.trim();
  if (!title) {
    return { valid: false, item: null, error: 'Название не может быть пустым' };
  }

  const item: UpdateItem = {};

  if (title !== original.title) {
    item.title = title;
  }

  const origDay = recordDayKey(original, tz) ?? '';
  const origTime = recordTimeField(original, tz);
  const origAllDay = Boolean(original.all_day);

  const startChanged =
    values.day !== origDay ||
    values.allDay !== origAllDay ||
    (!values.allDay && values.time !== origTime);

  if (startChanged && values.day) {
    if (original.type === 'meeting') {
      if (!values.time) {
        return { valid: false, item: null, error: 'Для встречи нужны день и время' };
      }
      item.start = localDateTimeIso(values.day, values.time);
      item.time_given = true;
    } else if (values.allDay) {
      item.start = localMidnightIso(values.day);
      item.time_given = false;
    } else if (values.time) {
      item.start = localDateTimeIso(values.day, values.time);
      item.time_given = true;
    } else {
      item.start = localMidnightIso(values.day);
      item.time_given = false;
    }
  }

  if (original.type === 'task') {
    const origDl = recordDeadlineField(original, tz);
    const origDlDay = origDl?.day ?? '';
    const origDlTime = origDl?.time ?? '';

    const dlChanged =
      values.deadlineDay !== origDlDay ||
      (values.deadlineDay && values.deadlineTime !== origDlTime);

    if (dlChanged && values.deadlineDay) {
      const time = values.deadlineTime ? values.deadlineTime : '23:59';
      item.deadline = localDateTimeIso(values.deadlineDay, time);
    }
  }

  if (Object.keys(item).length === 0) {
    return { valid: true, item: null };
  }

  return { valid: true, item };
}

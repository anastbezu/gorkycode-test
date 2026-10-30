// docs/contracts/api.md, раздел «Быстрые ответы» (awaiting).
// Поля и тексты, которые отправляют чипы, — строго по контракту:
// - awaiting = "choice"  -> «номер N» (1..N в порядке candidates)
// - awaiting = "confirm" -> «да, все» / «отмена»
// - awaiting = "time"    -> «в 09:00», «в 13:00», «в 15:00», «в 18:00»
// - awaiting = "answer" | null -> быстрых ответов нет

import type { AwaitingKind, Record } from '../api/types';
import { recordWhen } from './dates';

export interface QuickChip {
  id: string;
  label: string;
  subLabel?: string;
  indexBadge?: number;
  sendText: string;
  variant: 'choice' | 'confirm-yes' | 'confirm-cancel' | 'time';
}

export interface QuickReplyModel {
  kind: 'choice' | 'confirm' | 'time';
  chips: QuickChip[];
  candidates?: Record[];
}

export const TIME_REPLIES = [
  { time: '09:00', period: 'утром', sendText: 'в 09:00' },
  { time: '13:00', period: 'в обед', sendText: 'в 13:00' },
  { time: '15:00', period: 'днём', sendText: 'в 15:00' },
  { time: '18:00', period: 'вечером', sendText: 'в 18:00' },
] as const;

export const CONFIRM_REPLIES = [
  { key: 'confirm-yes', label: 'Да, все', sendText: 'да, все', variant: 'confirm-yes' as const },
  { key: 'confirm-cancel', label: 'Отмена', sendText: 'отмена', variant: 'confirm-cancel' as const },
] as const;

export function resolveQuickReplies(
  awaiting: AwaitingKind,
  candidates: Record[] | undefined | null,
  tz: string,
  now: Date = new Date(),
): QuickReplyModel | null {
  if (awaiting === 'time') {
    return {
      kind: 'time',
      chips: TIME_REPLIES.map((t) => ({
        id: `time-${t.time}`,
        label: t.time,
        subLabel: t.period,
        sendText: t.sendText,
        variant: 'time',
      })),
    };
  }

  if (awaiting === 'choice') {
    if (!candidates || candidates.length === 0) return null;
    return {
      kind: 'choice',
      candidates,
      chips: candidates.map((rec, idx) => {
        const num = idx + 1;
        const when = recordWhen(rec, tz, now);
        return {
          id: `choice-${num}`,
          label: rec.title,
          subLabel: when,
          indexBadge: num,
          sendText: `номер ${num}`,
          variant: 'choice',
        };
      }),
    };
  }

  if (awaiting === 'confirm') {
    return {
      kind: 'confirm',
      candidates: candidates ?? [],
      chips: CONFIRM_REPLIES.map((c) => ({
        id: c.key,
        label: c.label,
        sendText: c.sendText,
        variant: c.variant,
      })),
    };
  }

  return null;
}

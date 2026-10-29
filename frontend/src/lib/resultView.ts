import type { ActionResult, Record, RecordType } from '../api/types';
import { recordTime, recordWhen } from './dates';

export function formatRecordPlural(n: number): string {
  const abs = Math.abs(n) % 100;
  const rem = abs % 10;
  if (abs > 10 && abs < 20) return 'записей';
  if (rem > 1 && rem < 5) return 'записи';
  if (rem === 1) return 'запись';
  return 'записей';
}

export function formatCreatedCount(n: number): string {
  const abs = Math.abs(n) % 100;
  const rem = abs % 10;
  const word = formatRecordPlural(n);
  if (rem === 1 && abs !== 11) {
    return `Создана ${n} ${word}`;
  }
  return `Создано ${n} ${word}`;
}

export function formatDoneCount(n: number): string {
  return `Выполнено ${n} ${formatRecordPlural(n)}`;
}

export function formatCancelledCount(n: number): string {
  return `Отменено ${n} ${formatRecordPlural(n)}`;
}

const CREATED_TAG: { [K in RecordType]: string } = {
  task: 'Задача создана',
  meeting: 'Встреча создана',
  reminder: 'Напоминание создано',
};

const UPDATED_TAG: { [K in RecordType]: string } = {
  task: 'Задача изменена',
  meeting: 'Встреча изменена',
  reminder: 'Напоминание изменено',
};

export interface ConflictItem {
  id: string;
  title: string;
  time: string;
}

export interface SingleCardView {
  kind: 'single_card';
  record: Record;
  tag: string;
  tagVariant: 'lime' | 'violet' | 'gray';
  title: string;
  when: string;
  titleStrikethrough?: boolean;
  footerNote?: string;
  actionType?: 'default' | 'done' | 'cancelled';
  hasConflict: boolean;
  conflicts: ConflictItem[];
}

export interface MultiCreatedView {
  kind: 'multi_created';
  tag: string;
  tagVariant: 'lime';
  items: Array<{ id: string; title: string; when: string }>;
  hasConflict: boolean;
  conflicts: ConflictItem[];
}

export interface MultiStatusView {
  kind: 'multi_status';
  tag: string;
  tagVariant: 'gray';
  items: Array<{ id: string; title: string; when: string }>;
}

export type CardItemView = SingleCardView | MultiCreatedView | MultiStatusView;

export interface ListView {
  type: 'list';
  records: Record[];
}

export interface CardsView {
  type: 'cards';
  cards: CardItemView[];
}

export type ResultViewModel = CardsView | ListView;

export function formatItemWhen(record: Record, tz: string, now: Date): string {
  if (record.type === 'task' && !record.start && !record.deadline) {
    return 'без срока';
  }
  return recordWhen(record, tz, now);
}

export function formatConflictItem(record: Record, tz: string, now: Date): ConflictItem {
  const t = recordTime(record, tz);
  return {
    id: record.id,
    title: record.title,
    time: t || recordWhen(record, tz, now),
  };
}

/**
 * Чистая функция сопоставления результата действия и модели отображения под ответом.
 * Каждое правило соответствует строке в спецификации frontend-06.
 */
export function resolveResultView(
  result: ActionResult | null,
  awaiting: string | null = null,
  tz: string = 'Europe/Moscow',
  now: Date = new Date(),
): ResultViewModel | null {
  if (!result || !result.ok) {
    return null;
  }

  // Быстрые ответы (выбор, подтверждение, время) отрисовываются текстом (чипы — frontend-08)
  if (awaiting !== null || (result.candidates && result.candidates.length > 0)) {
    return null;
  }

  const conflicts: ConflictItem[] = (result.conflicts || []).map((c) =>
    formatConflictItem(c, tz, now),
  );
  const hasConflict = conflicts.length > 0;

  // 1. Создание записей
  if (result.action === 'create_record') {
    if (!result.records || result.records.length === 0) return null;

    if (result.records.length === 1) {
      const rec = result.records[0];
      return {
        type: 'cards',
        cards: [
          {
            kind: 'single_card',
            record: rec,
            tag: CREATED_TAG[rec.type] || 'Запись создана',
            tagVariant: 'lime',
            title: rec.title,
            when: formatItemWhen(rec, tz, now),
            actionType: 'default',
            hasConflict,
            conflicts,
          },
        ],
      };
    }

    // 2+ созданных записей — одна сводная карточка
    return {
      type: 'cards',
      cards: [
        {
          kind: 'multi_created',
          tag: formatCreatedCount(result.records.length),
          tagVariant: 'lime',
          items: result.records.map((r) => ({
            id: r.id,
            title: r.title,
            when: formatItemWhen(r, tz, now),
          })),
          hasConflict,
          conflicts,
        },
      ],
    };
  }

  // 2. Изменение записи
  if (result.action === 'update_record') {
    if (!result.records || result.records.length === 0) return null;
    const rec = result.records[0];
    return {
      type: 'cards',
      cards: [
        {
          kind: 'single_card',
          record: rec,
          tag: UPDATED_TAG[rec.type] || 'Запись изменена',
          tagVariant: 'violet',
          title: rec.title,
          when: formatItemWhen(rec, tz, now),
          actionType: 'default',
          hasConflict,
          conflicts,
        },
      ],
    };
  }

  // 3. Установка статуса (done, cancelled, active)
  if (result.action === 'set_status') {
    if (!result.records || result.records.length === 0) return null;

    if (result.records.length === 1) {
      const rec = result.records[0];
      if (rec.status === 'done') {
        return {
          type: 'cards',
          cards: [
            {
              kind: 'single_card',
              record: rec,
              tag: '✓ Выполнено',
              tagVariant: 'gray',
              title: rec.title,
              when: formatItemWhen(rec, tz, now),
              titleStrikethrough: true,
              actionType: 'done',
              hasConflict: false,
              conflicts: [],
            },
          ],
        };
      }
      if (rec.status === 'cancelled') {
        return {
          type: 'cards',
          cards: [
            {
              kind: 'single_card',
              record: rec,
              tag: 'Отменено',
              tagVariant: 'gray',
              title: rec.title,
              when: formatItemWhen(rec, tz, now),
              titleStrikethrough: true,
              footerNote: 'Передумали? Скажите «верни»',
              actionType: 'cancelled',
              hasConflict: false,
              conflicts: [],
            },
          ],
        };
      }
      // status === 'active'
      return {
        type: 'cards',
        cards: [
          {
            kind: 'single_card',
            record: rec,
            tag: 'Возвращено',
            tagVariant: 'violet',
            title: rec.title,
            when: formatItemWhen(rec, tz, now),
            titleStrikethrough: false,
            actionType: 'default',
            hasConflict: false,
            conflicts: [],
          },
        ],
      };
    }

    // Несколько записей при массовом действии
    const firstStatus = result.records[0].status;
    if (firstStatus === 'done') {
      return {
        type: 'cards',
        cards: [
          {
            kind: 'multi_status',
            tag: formatDoneCount(result.records.length),
            tagVariant: 'gray',
            items: result.records.map((r) => ({
              id: r.id,
              title: r.title,
              when: formatItemWhen(r, tz, now),
            })),
          },
        ],
      };
    }
    if (firstStatus === 'cancelled') {
      return {
        type: 'cards',
        cards: [
          {
            kind: 'multi_status',
            tag: formatCancelledCount(result.records.length),
            tagVariant: 'gray',
            items: result.records.map((r) => ({
              id: r.id,
              title: r.title,
              when: formatItemWhen(r, tz, now),
            })),
          },
        ],
      };
    }

    // Массовый возврат в active: карточка «Возвращено» на каждую запись
    return {
      type: 'cards',
      cards: result.records.map((rec) => ({
        kind: 'single_card',
        record: rec,
        tag: 'Возвращено',
        tagVariant: 'violet',
        title: rec.title,
        when: formatItemWhen(rec, tz, now),
        titleStrikethrough: false,
        actionType: 'default',
        hasConflict: false,
        conflicts: [],
      })),
    };
  }

  // 4. Откат последнего действия undo_last
  if (result.action === 'undo_last') {
    if (!result.restored || result.restored.length === 0) return null;
    return {
      type: 'cards',
      cards: result.restored.map((rec) => ({
        kind: 'single_card',
        record: rec,
        tag: 'Возвращено',
        tagVariant: 'violet',
        title: rec.title,
        when: formatItemWhen(rec, tz, now),
        titleStrikethrough: false,
        actionType: 'default',
        hasConflict: false,
        conflicts: [],
      })),
    };
  }

  // 5. Списки и поиск
  if (result.action === 'list_records' || result.action === 'search_records') {
    if (!result.records || result.records.length === 0) return null;
    return {
      type: 'list',
      records: result.records,
    };
  }

  return null;
}

import { useState } from 'react';
import type { ActionResult, Record } from '../api/types';
import {
  dayKey,
  listDayHeader,
  recordAnchor,
  recordWhen,
  recordWhenInDay,
} from '../lib/dates';
import {
  resolveResultView,
  type CardItemView,
  type SingleCardView,
  type MultiCreatedView,
  type MultiStatusView,
} from '../lib/resultView';
import {
  CalendarIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  TrashIcon,
  UndoIcon,
} from './icons';

export const LIST_COLLAPSE_LIMIT = 8;

export function formatExpandButtonText(hiddenCount: number): string {
  return `Показать ещё ${hiddenCount}`;
}

export interface ListRowItem {
  record: Record;
  displayIndex: number;
  dayHeader?: string;
}

export function buildListRows(
  records: Record[],
  tz: string,
  now: Date = new Date(),
  expanded = false,
  limit = LIST_COLLAPSE_LIMIT,
): { visibleRows: ListRowItem[]; hiddenCount: number } {
  const todayKey = dayKey(now, tz);
  const keyOf = (r: Record) => {
    const anchor = recordAnchor(r);
    return anchor ? dayKey(new Date(anchor), tz) : 'undated';
  };
  const multiDay = new Set(records.map(keyOf)).size > 1;

  const total = records.length;
  const isCollapsible = total > limit;
  const visibleCount = !isCollapsible || expanded ? total : limit;
  const hiddenCount = total - visibleCount;

  const visibleRows: ListRowItem[] = [];
  let prevKey: string | null = null;

  for (let i = 0; i < visibleCount; i++) {
    const record = records[i];
    const key = keyOf(record);
    let dayHeader: string | undefined;

    if (multiDay && key !== prevKey) {
      dayHeader = key === 'undated' ? 'Без даты' : listDayHeader(key, todayKey);
      prevKey = key;
    }

    visibleRows.push({
      record,
      displayIndex: i + 1,
      dayHeader,
    });
  }

  return { visibleRows, hiddenCount };
}

interface Props {
  result: ActionResult | null;
  awaiting: string | null;
  tz: string;
  onOpen?: (record: Record) => void;
  onSetStatus?: (record: Record, status: 'done' | 'active' | 'cancelled') => void;
  onDelete?: (record: Record) => void;
  onRestore?: (recordId: string) => void;
}

export function ResultView({
  result,
  awaiting,
  tz,
  onOpen,
  onSetStatus,
  onDelete,
  onRestore,
}: Props) {
  const model = resolveResultView(result, awaiting, tz);
  if (!model) return null;

  if (model.type === 'cards') {
    return (
      <div className="result-cards">
        {model.cards.map((card, idx) => (
          <ActionCard
            key={idx}
            card={card}
            onOpen={onOpen}
            onSetStatus={onSetStatus}
            onDelete={onDelete}
            onRestore={onRestore}
          />
        ))}
      </div>
    );
  }

  if (model.type === 'list') {
    return <NumberedList records={model.records} tz={tz} onOpen={onOpen} />;
  }

  return null;
}

function ActionCard({
  card,
  onOpen,
  onSetStatus,
  onDelete,
  onRestore,
}: {
  card: CardItemView;
  onOpen?: (record: Record) => void;
  onSetStatus?: (record: Record, status: 'done' | 'active' | 'cancelled') => void;
  onDelete?: (record: Record) => void;
  onRestore?: (recordId: string) => void;
}) {
  if (card.kind === 'single_card') {
    return (
      <SingleCard
        card={card}
        onOpen={onOpen}
        onSetStatus={onSetStatus}
        onDelete={onDelete}
        onRestore={onRestore}
      />
    );
  }

  if (card.kind === 'multi_created') {
    return <MultiCreatedCard card={card} />;
  }

  if (card.kind === 'multi_status') {
    return <MultiStatusCard card={card} />;
  }

  return null;
}

function SingleCard({
  card,
  onOpen,
  onSetStatus,
  onDelete,
  onRestore,
}: {
  card: SingleCardView;
  onOpen?: (record: Record) => void;
  onSetStatus?: (record: Record, status: 'done' | 'active' | 'cancelled') => void;
  onDelete?: (record: Record) => void;
  onRestore?: (recordId: string) => void;
}) {
  const { record } = card;

  return (
    <div className={`card card--action${card.hasConflict ? ' card--conflict' : ''}`}>
      <div className="card__header">
        <span className={`tag tag--${card.tagVariant}`}>{card.tag}</span>
      </div>

      <div
        className={`card__title${card.titleStrikethrough ? ' card__title--strikethrough' : ''}`}
      >
        {card.title}
      </div>

      <div className="card__when">{card.when}</div>

      {card.hasConflict && card.conflicts.length > 0 && (
        <div className="card__conflicts">
          <div className="card__conflicts-title">Пересекается с:</div>
          <div className="card__conflicts-list">
            {card.conflicts.map((c) => (
              <div key={c.id} className="card__conflict-row">
                <span className="card__conflict-name">{c.title}</span>
                <span className="card__conflict-time">{c.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card__divider" />

      {card.footerNote && <div className="card__footer-note">{card.footerNote}</div>}

      <div className="card__actions">
        {card.actionType === 'cancelled' ? (
          <button
            type="button"
            className="btn btn--card-action"
            onClick={() => {
              if (onRestore) onRestore(record.id);
              else if (onSetStatus) onSetStatus(record, 'active');
            }}
          >
            <UndoIcon width={16} height={16} />
            <span>Вернуть</span>
          </button>
        ) : (
          <>
            <button
              type="button"
              className="btn btn--card-action"
              onClick={() => onOpen?.(record)}
            >
              <CalendarIcon />
              <span>Перенести</span>
            </button>

            {card.actionType === 'done' ? (
              <button
                type="button"
                className="btn btn--card-action"
                onClick={() => onSetStatus?.(record, 'active')}
              >
                <UndoIcon width={16} height={16} />
                <span>Не выполнено</span>
              </button>
            ) : (
              <button
                type="button"
                className="btn btn--card-action"
                onClick={() => onSetStatus?.(record, 'done')}
              >
                <CheckIcon width={16} height={16} />
                <span>Выполнено</span>
              </button>
            )}

            <button
              type="button"
              className="btn btn--card-action btn--card-delete"
              aria-label="Удалить"
              onClick={() => onDelete?.(record)}
            >
              <TrashIcon width={16} height={16} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function MultiCreatedCard({ card }: { card: MultiCreatedView }) {
  return (
    <div className={`card card--action${card.hasConflict ? ' card--conflict' : ''}`}>
      <div className="card__header">
        <span className={`tag tag--${card.tagVariant}`}>{card.tag}</span>
      </div>

      <div className="card__multi-rows">
        {card.items.map((it) => (
          <div key={it.id} className="card__multi-row">
            <span className="card__multi-title">{it.title}</span>
            <span className="card__multi-when">{it.when}</span>
          </div>
        ))}
      </div>

      {card.hasConflict && card.conflicts.length > 0 && (
        <div className="card__conflicts">
          <div className="card__conflicts-title">Пересекается с:</div>
          <div className="card__conflicts-list">
            {card.conflicts.map((c) => (
              <div key={c.id} className="card__conflict-row">
                <span className="card__conflict-name">{c.title}</span>
                <span className="card__conflict-time">{c.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MultiStatusCard({ card }: { card: MultiStatusView }) {
  return (
    <div className="card card--action">
      <div className="card__header">
        <span className={`tag tag--${card.tagVariant}`}>{card.tag}</span>
      </div>

      <div className="card__multi-rows">
        {card.items.map((it) => (
          <div key={it.id} className="card__multi-row">
            <span className="card__multi-title">{it.title}</span>
            <span className="card__multi-when">{it.when}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Номер строки — тот, что пользователь назовёт («перенеси вторую»): с 1, в порядке ответа,
 * без пересортировки и свёртки. Заголовки дней — только если записи из разных дней.
 * Длинный список (> 8 элементов) сворачивается с кнопкой «⌄ Показать ещё N» / «⌃ Свернуть».
 */
export function NumberedList({
  records,
  tz,
  onOpen,
}: {
  records: Record[];
  tz: string;
  onOpen?: (record: Record) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const now = new Date();
  const { visibleRows, hiddenCount } = buildListRows(records, tz, now, expanded);
  const isCollapsible = records.length > LIST_COLLAPSE_LIMIT;

  const keyOf = (r: Record) => {
    const anchor = recordAnchor(r);
    return anchor ? dayKey(new Date(anchor), tz) : 'undated';
  };
  const multiDay = new Set(records.map(keyOf)).size > 1;

  return (
    <div className="list">
      {visibleRows.map((item) => {
        const { record, displayIndex, dayHeader } = item;
        const done = record.status === 'done';
        const cancelled = record.status === 'cancelled';
        const clickable = Boolean(onOpen);

        return (
          <div key={`group-${record.id}-${displayIndex}`}>
            {dayHeader && <div className="list__day">{dayHeader}</div>}
            <div
              className={`list__row${done ? ' list__row--done' : ''}${cancelled ? ' list__row--cancelled' : ''}${clickable ? ' list__row--clickable' : ''}`}
              onClick={clickable ? () => onOpen?.(record) : undefined}
              role={clickable ? 'button' : undefined}
              tabIndex={clickable ? 0 : undefined}
              onKeyDown={
                clickable
                  ? (e) => (e.key === 'Enter' || e.key === ' ') && onOpen?.(record)
                  : undefined
              }
            >
              <span className="list__num-badge">{displayIndex}</span>
              <span className="list__title">
                {record.title}
                {done && <span className="tag tag--done list__done">выполнено</span>}
                {cancelled && <span className="tag tag--cancelled list__cancelled">удалено</span>}
              </span>
              <span className="list__when">
                {multiDay ? recordWhenInDay(record, tz, now) : recordWhen(record, tz, now)}
              </span>
            </div>
          </div>
        );
      })}

      {isCollapsible && (
        <button
          type="button"
          className="list__expand-btn"
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? (
            <>
              <ChevronUpIcon width={16} height={16} />
              <span>Свернуть</span>
            </>
          ) : (
            <>
              <ChevronDownIcon width={16} height={16} />
              <span>{formatExpandButtonText(hiddenCount)}</span>
            </>
          )}
        </button>
      )}
    </div>
  );
}

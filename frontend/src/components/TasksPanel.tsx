// Панель «Мои дела»: лента из плитки «Без срока» и 5 дней, листание, карточки выбранного дня.
// Данные — один GET /api/items на 5 дней (usePanel в App), раскладка по дням — здесь.
import type { Record, RecordType } from '../api/types';
import { addDaysToKey, dayKey, formatDaysRange, recordAnchor, recordWhen, weekdayShort } from '../lib/dates';
import { CalendarIcon, CloseIcon, NextIcon, PlusIcon, PrevIcon } from './icons';

export type PanelState =
  | { status: 'loading'; records: Record[] }
  | { status: 'ready'; records: Record[] }
  | { status: 'error'; records: Record[]; message: string };

const TYPE_TAG: { [K in RecordType]: string } = {
  task: 'Задача',
  meeting: 'Встреча',
  reminder: 'Напоминание',
};

export const PANEL_DAYS = 5;

/** Ключи 5 дней страницы ленты в поясе браузера. Поддерживает как YYYY-MM-DD, так и IANA-пояс. */
export function panelDayKeys(startOrTz: string, nowOrCount?: Date | number): string[] {
  if (startOrTz.includes('/')) {
    const now = (nowOrCount as Date) ?? new Date();
    const today = dayKey(now, startOrTz);
    return Array.from({ length: PANEL_DAYS }, (_, i) => addDaysToKey(today, i));
  }
  const count = typeof nowOrCount === 'number' ? nowOrCount : PANEL_DAYS;
  return Array.from({ length: count }, (_, i) => addDaysToKey(startOrTz, i));
}

/** Разложить записи по дням (по началу, а без него — по сроку) и отдельно — без даты. */
export function groupByDay(records: Record[], tz: string): { byDay: Map<string, Record[]>; undated: Record[] } {
  const byDay = new Map<string, Record[]>();
  const undated: Record[] = [];
  for (const record of records) {
    const anchor = recordAnchor(record);
    if (!anchor) {
      undated.push(record);
      continue;
    }
    const key = dayKey(new Date(anchor), tz);
    byDay.set(key, [...(byDay.get(key) ?? []), record]);
  }
  // Порядок — по времени, выполненные — вниз, как в макете
  for (const list of byDay.values()) {
    list.sort((a, b) => {
      if ((a.status === 'done') !== (b.status === 'done')) return a.status === 'done' ? 1 : -1;
      return Date.parse(recordAnchor(a)!) - Date.parse(recordAnchor(b)!);
    });
  }
  undated.sort((a, b) => {
    if ((a.status === 'done') !== (b.status === 'done')) return a.status === 'done' ? 1 : -1;
    return a.title.localeCompare(b.title);
  });
  return { byDay, undated };
}

/** «Мои дела · N» — активные записи на сегодня. */
export function activeTodayCount(records: Record[], tz: string, now: Date = new Date()): number {
  const today = dayKey(now, tz);
  return records.filter((r) => {
    const anchor = recordAnchor(r);
    return r.status === 'active' && anchor !== null && dayKey(new Date(anchor), tz) === today;
  }).length;
}

/** Число активных записей без даты (для плитки «Без срока»). */
export function activeUndatedCount(records: Record[]): number {
  return records.filter((r) => r.status === 'active' && !recordAnchor(r)).length;
}

interface Props {
  state: PanelState;
  tz: string;
  firstDayKey: string;
  selectedDay: number | 'undated';
  onSelectDay: (selection: number | 'undated') => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onRetry: () => void;
  onClose: () => void;
  onOpen?: (record: Record) => void;
  onCreate?: (dayKey?: string) => void;
}

export function TasksPanel({
  state,
  tz,
  firstDayKey,
  selectedDay,
  onSelectDay,
  onPrevPage,
  onNextPage,
  onRetry,
  onClose,
  onOpen,
  onCreate,
}: Props) {
  const now = new Date();
  const todayKey = dayKey(now, tz);
  const tomorrowKey = addDaysToKey(todayKey, 1);
  const keys = panelDayKeys(firstDayKey, PANEL_DAYS);
  const { byDay, undated } = groupByDay(state.records, tz);
  const activeUndated = activeUndatedCount(state.records);

  const isUndatedSelected = selectedDay === 'undated';
  const currentDayKey = typeof selectedDay === 'number' ? keys[selectedDay] : null;
  const dayRecords = currentDayKey ? byDay.get(currentDayKey) ?? [] : [];
  const loaded = state.status === 'ready';

  return (
    <aside className="panel" aria-label="Мои дела">
      <div className="panel__handle" onClick={onClose} aria-hidden />
      <div className="panel__head">
        <h2 className="panel__title">Мои дела</h2>
        <div className="panel__pager">
          <button
            type="button"
            className="icon-btn panel__arrow"
            onClick={onPrevPage}
            aria-label="Предыдущие дни"
          >
            <PrevIcon />
          </button>
          <span className="panel__range">{formatDaysRange(firstDayKey, PANEL_DAYS)}</span>
          <button
            type="button"
            className="icon-btn panel__arrow"
            onClick={onNextPage}
            aria-label="Следующие дни"
          >
            <NextIcon />
          </button>
        </div>
        <div className="panel__head-actions">
          {onCreate && (
            <button
              type="button"
              className="btn btn--round panel__create-btn"
              onClick={() => onCreate(currentDayKey ?? undefined)}
              aria-label="Создать запись"
              title="Создать запись"
            >
              <PlusIcon />
            </button>
          )}
          <button type="button" className="icon-btn panel__close" onClick={onClose} aria-label="Закрыть">
            <CloseIcon />
          </button>
        </div>
      </div>

      <div className="days" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={isUndatedSelected}
          className={`days__day days__day--undated${isUndatedSelected ? ' days__day--selected' : ''}`}
          onClick={() => onSelectDay('undated')}
        >
          <span className="days__name">
            Без
            <br />
            срока
          </span>
          <span className="days__num">{activeUndated}</span>
        </button>

        {keys.map((key, i) => {
          const isToday = key === todayKey;
          const isTomorrow = key === tomorrowKey;
          const isSelected = selectedDay === i;
          const isTodayOutline = isToday && isUndatedSelected;
          const dayActiveCount = (byDay.get(key) ?? []).filter((r) => r.status === 'active').length;
          const hasActive = dayActiveCount > 0;

          let dayName = weekdayShort(key);
          if (isToday) dayName = 'Сегодня';
          else if (isTomorrow) dayName = 'Завтра';

          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={isSelected}
              className={`days__day${isSelected ? ' days__day--selected' : ''}${isTodayOutline ? ' days__day--today-outline' : ''}`}
              onClick={() => onSelectDay(i)}
            >
              <span className="days__name">{dayName}</span>
              <span className="days__num">{Number(key.slice(8))}</span>
              <span className={`days__dot${hasActive ? ' days__dot--on' : ''}`} />
            </button>
          );
        })}
      </div>

      <div className="panel__body">
        {state.status === 'error' && (
          <div className="panel__error-card">
            <p className="panel__error-text">Не удалось загрузить дела.</p>
            <button type="button" className="btn panel__error-btn" onClick={onRetry}>
              Повторить
            </button>
          </div>
        )}

        {state.status === 'loading' && state.records.length === 0 && (
          <div className="panel__skeletons" aria-label="Загрузка">
            <div className="card card--skeleton">
              <div className="skeleton-bar skeleton-bar--tag" />
              <div className="skeleton-bar skeleton-bar--title" />
              <div className="skeleton-bar skeleton-bar--time" />
            </div>
            <div className="card card--skeleton">
              <div className="skeleton-bar skeleton-bar--tag" />
              <div className="skeleton-bar skeleton-bar--title" />
              <div className="skeleton-bar skeleton-bar--time" />
            </div>
            <div className="card card--skeleton">
              <div className="skeleton-bar skeleton-bar--tag" />
              <div className="skeleton-bar skeleton-bar--title" />
              <div className="skeleton-bar skeleton-bar--time" />
            </div>
          </div>
        )}

        {loaded && !isUndatedSelected && dayRecords.length === 0 && (
          <div className="panel__empty">
            <div className="panel__empty-icon" aria-hidden>
              <CalendarIcon />
            </div>
            <p className="panel__empty-text">На этот день дел нет</p>
          </div>
        )}

        {loaded && isUndatedSelected && undated.length === 0 && (
          <div className="panel__empty">
            <div className="panel__empty-icon" aria-hidden>
              <CalendarIcon />
            </div>
            <p className="panel__empty-text">Нет дел без срока</p>
          </div>
        )}

        {!(state.status === 'loading' && state.records.length === 0) &&
          state.status !== 'error' &&
          (isUndatedSelected
            ? undated.map((record) => (
                <TaskCard key={record.id} record={record} tz={tz} now={now} when="" onOpen={onOpen} />
              ))
            : dayRecords.map((record) => (
                <TaskCard key={record.id} record={record} tz={tz} now={now} onOpen={onOpen} />
              )))}
      </div>
    </aside>
  );
}

/** Компонент «Карточка дела». `when` — своя подпись времени (в календаре — без даты: она в заголовке дня). */
export function TaskCard({
  record,
  tz,
  now,
  when,
  onOpen,
}: {
  record: Record;
  tz: string;
  now: Date;
  when?: string;
  onOpen?: (record: Record) => void;
}) {
  const done = record.status === 'done';
  const clickable = Boolean(onOpen);
  return (
    <div
      className={`card${done ? ' card--done' : ''}${clickable ? ' card--clickable' : ''}`}
      onClick={clickable ? () => onOpen?.(record) : undefined}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => (e.key === 'Enter' || e.key === ' ') && onOpen?.(record)
          : undefined
      }
    >
      <span className={`tag ${done ? 'tag--done' : 'tag--type'}`}>
        {TYPE_TAG[record.type]}
        {done ? ' · выполнено' : ''}
      </span>
      <div className="card__title">{record.title}</div>
      <div className="card__when">{when ?? recordWhen(record, tz, now)}</div>
    </div>
  );
}

// Панель «Мои дела»: лента из 7 дней с сегодняшнего, карточки выбранного дня, блок «Без срока».
// Данные — один GET /api/items на всю неделю (usePanel в App), раскладка по дням — здесь.
import type { Record, RecordType } from '../api/types';
import { addDaysToKey, dayKey, recordAnchor, recordWhen, weekdayShort } from '../lib/dates';
import { CloseIcon } from './icons';

export type PanelState =
  | { status: 'loading'; records: Record[] }
  | { status: 'ready'; records: Record[] }
  | { status: 'error'; records: Record[]; message: string };

const TYPE_TAG: { [K in RecordType]: string } = {
  task: 'Задача',
  meeting: 'Встреча',
  reminder: 'Напоминание',
};

export const PANEL_DAYS = 7;

/** Ключи 7 дней ленты, начиная с сегодняшнего, в поясе браузера. */
export function panelDayKeys(tz: string, now: Date = new Date()): string[] {
  const today = dayKey(now, tz);
  return Array.from({ length: PANEL_DAYS }, (_, i) => addDaysToKey(today, i));
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

interface Props {
  state: PanelState;
  tz: string;
  selectedDay: number;
  onSelectDay: (index: number) => void;
  onRetry: () => void;
  onClose: () => void;
}

export function TasksPanel({ state, tz, selectedDay, onSelectDay, onRetry, onClose }: Props) {
  const now = new Date();
  const keys = panelDayKeys(tz, now);
  const { byDay, undated } = groupByDay(state.records, tz);
  const dayRecords = byDay.get(keys[selectedDay]) ?? [];
  const loaded = state.status === 'ready';

  return (
    <aside className="panel" aria-label="Мои дела">
      <div className="panel__handle" onClick={onClose} aria-hidden />
      <div className="panel__head">
        <h2 className="panel__title">Мои дела</h2>
        <button type="button" className="icon-btn panel__close" onClick={onClose} aria-label="Закрыть">
          <CloseIcon />
        </button>
      </div>

      <div className="days" role="tablist">
        {keys.map((key, i) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={i === selectedDay}
            className={`days__day${i === selectedDay ? ' days__day--selected' : ''}`}
            onClick={() => onSelectDay(i)}
          >
            <span className="days__name">{i === 0 ? 'Сегодня' : i === 1 ? 'Завтра' : weekdayShort(key)}</span>
            <span className="days__num">{Number(key.slice(8))}</span>
            <span className={`days__dot${(byDay.get(key)?.length ?? 0) > 0 ? ' days__dot--on' : ''}`} />
          </button>
        ))}
      </div>

      <div className="panel__body">
        {state.status === 'error' && (
          <div className="panel__note">
            <p>Не удалось загрузить дела. {state.message}</p>
            <button type="button" className="btn btn--glass" onClick={onRetry}>
              Повторить
            </button>
          </div>
        )}
        {state.status === 'loading' && state.records.length === 0 && <p className="panel__note">Загружаю дела…</p>}
        {loaded && dayRecords.length === 0 && <p className="panel__note">На этот день дел нет.</p>}

        {dayRecords.map((record) => (
          <TaskCard key={record.id} record={record} tz={tz} now={now} />
        ))}

        {undated.length > 0 && (
          <>
            <h3 className="panel__section">Без срока</h3>
            {undated.map((record) => (
              <TaskCard key={record.id} record={record} tz={tz} now={now} />
            ))}
          </>
        )}
      </div>
    </aside>
  );
}

function TaskCard({ record, tz, now }: { record: Record; tz: string; now: Date }) {
  const done = record.status === 'done';
  return (
    <div className={`card${done ? ' card--done' : ''}`}>
      <span className={`tag ${done ? 'tag--done' : 'tag--type'}`}>
        {TYPE_TAG[record.type]}
        {done ? ' · выполнено' : ''}
      </span>
      <div className="card__title">{record.title}</div>
      <div className="card__when">{recordWhen(record, tz, now)}</div>
    </div>
  );
}

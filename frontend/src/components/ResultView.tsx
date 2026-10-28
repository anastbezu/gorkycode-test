// Что показывается под ответом ассистента — по постановке frontend-01, «Ответ чата → что видно в ленте»:
// - create_record, ok — карточка на каждую созданную запись;
// - list_records / search_records, ok, записи есть — пронумерованный список в полученном порядке;
// - всё остальное — только reply (карточки изменений, чипы выбора и т. п. — отдельные задачи).
import type { ActionResult, Record, RecordType } from '../api/types';
import { dayKey, dayLabel, recordAnchor, recordWhen, recordWhenInDay } from '../lib/dates';

const CREATED_TAG: { [K in RecordType]: string } = {
  task: 'Задача создана',
  meeting: 'Встреча создана',
  reminder: 'Напоминание создано',
};

interface Props {
  result: ActionResult | null;
  awaiting: 'answer' | 'choice' | null;
  tz: string;
  onOpen?: (record: Record) => void;
}

export function ResultView({ result, awaiting, tz, onOpen }: Props) {
  if (!result || !result.ok || awaiting) return null;
  // Пересечения, кандидаты, откат, нехватка данных — их вид ещё не нарисован: только reply
  const hasUnsupported =
    result.candidates.length > 0 ||
    result.conflicts.length > 0 ||
    result.restored.length > 0 ||
    result.missing.length > 0;
  if (hasUnsupported) return null;

  if (result.action === 'create_record' && result.records.length > 0) {
    return (
      <div className="result-created">
        {result.records.map((record) => (
          <div
            key={record.id}
            className={`card card--created${onOpen ? ' card--clickable' : ''}`}
            onClick={onOpen ? () => onOpen(record) : undefined}
            role={onOpen ? 'button' : undefined}
            tabIndex={onOpen ? 0 : undefined}
            onKeyDown={
              onOpen
                ? (e) => (e.key === 'Enter' || e.key === ' ') && onOpen(record)
                : undefined
            }
          >
            <span className="tag tag--success">{CREATED_TAG[record.type]}</span>
            <div className="card__title">{record.title}</div>
            <div className="card__when">{recordWhen(record, tz)}</div>
          </div>
        ))}
      </div>
    );
  }

  if ((result.action === 'list_records' || result.action === 'search_records') && result.records.length > 0) {
    return <NumberedList records={result.records} tz={tz} onOpen={onOpen} />;
  }

  return null;
}

/**
 * Номер строки — тот, что пользователь назовёт («перенеси вторую»): с 1, в порядке ответа,
 * без пересортировки и свёртки. Заголовки дней — только если записи из разных дней;
 * тогда в строке остаётся время, а номера идут подряд через заголовки.
 */
function NumberedList({
  records,
  tz,
  onOpen,
}: {
  records: Record[];
  tz: string;
  onOpen?: (record: Record) => void;
}) {
  const now = new Date();
  const todayKey = dayKey(now, tz);
  const keyOf = (r: Record) => {
    const anchor = recordAnchor(r);
    return anchor ? dayKey(new Date(anchor), tz) : 'undated';
  };
  const multiDay = new Set(records.map(keyOf)).size > 1;

  const rows: React.ReactNode[] = [];
  let prevKey: string | null = null;
  records.forEach((record, index) => {
    const key = keyOf(record);
    if (multiDay && key !== prevKey) {
      rows.push(
        <div key={`day-${index}`} className="list__day">
          {key === 'undated' ? 'Без даты' : dayLabel(key, todayKey)}
        </div>,
      );
      prevKey = key;
    }
    const done = record.status === 'done';
    const cancelled = record.status === 'cancelled';
    const clickable = Boolean(onOpen);
    rows.push(
      <div
        key={record.id + index}
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
        <span className="list__num">{index + 1}.</span>
        <span className="list__title">
          {record.title}
          {done && <span className="tag tag--done list__done">выполнено</span>}
          {cancelled && <span className="tag tag--cancelled list__cancelled">удалено</span>}
        </span>
        <span className="list__when">{multiDay ? recordWhenInDay(record, tz, now) : recordWhen(record, tz, now)}</span>
      </div>,
    );
  });

  return <div className="list">{rows}</div>;
}

import type { Record } from '../api/types';
import { dayKey, dayTitle, wallTime } from '../lib/dates';
import { CalendarIcon, CheckIcon, CloseIcon, TrashIcon, UndoIcon } from './icons';
import { TYPE_TAG } from './TasksPanel';

interface Props {
  record: Record | null;
  tz: string;
  onClose: () => void;
  onEdit: (record: Record) => void;
  onToggleStatus: (record: Record) => void;
  onDelete: (record: Record) => void;
}

function formatRecordTimeRange(record: Record, tz: string): string {
  if (record.all_day) return 'весь день';
  if (record.start && record.end) {
    const s = wallTime(new Date(record.start), tz);
    const e = wallTime(new Date(record.end), tz);
    const sStr = `${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')}`;
    const eStr = `${String(e.hour).padStart(2, '0')}:${String(e.minute).padStart(2, '0')}`;
    return `${sStr}–${eStr}`;
  }
  if (record.start) {
    const s = wallTime(new Date(record.start), tz);
    return `${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')}`;
  }
  if (record.deadline) {
    const d = wallTime(new Date(record.deadline), tz);
    return `до ${String(d.hour).padStart(2, '0')}:${String(d.minute).padStart(2, '0')}`;
  }
  return 'без времени';
}

function formatRecordDay(record: Record, tz: string): string {
  const now = new Date();
  const todayKey = dayKey(now, tz);
  const targetDateIso = record.start ?? record.deadline;
  if (!targetDateIso) return 'без срока';
  const targetKey = dayKey(new Date(targetDateIso), tz);
  return dayTitle(targetKey, todayKey);
}

export function RecordDetailsModal({
  record,
  tz,
  onClose,
  onEdit,
  onToggleStatus,
  onDelete,
}: Props) {
  if (!record) return null;

  const isDone = record.status === 'done';
  const timeStr = formatRecordTimeRange(record, tz);
  const dayStr = formatRecordDay(record, tz);
  const statusStr = isDone ? 'выполнена' : record.status === 'cancelled' ? 'отменена' : 'активна';

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="record-details-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="record-details-title"
      >
        <div className="record-details-modal__head">
          <span className={`tag ${isDone ? 'tag--done' : 'tag--type'}`}>
            {TYPE_TAG[record.type]}
            {isDone ? ' · выполнено' : ''}
          </span>
          <button
            type="button"
            className="icon-btn record-details-modal__close"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <CloseIcon />
          </button>
        </div>

        <h2 id="record-details-title" className={`record-details-modal__title ${isDone ? 'record-details-modal__title--done' : ''}`}>
          {record.title}
        </h2>

        <div className="record-details-modal__info">
          <div className="record-details-row">
            <span className="record-details-row__label">Когда</span>
            <span className="record-details-row__value">{dayStr}</span>
          </div>
          <div className="record-details-row">
            <span className="record-details-row__label">Время</span>
            <span className="record-details-row__value">{timeStr}</span>
          </div>
          <div className="record-details-row">
            <span className="record-details-row__label">Статус</span>
            <span className="record-details-row__value">{statusStr}</span>
          </div>
        </div>

        <div className="record-details-modal__actions">
          <button
            type="button"
            className="btn btn--glass"
            onClick={() => {
              onClose();
              onEdit(record);
            }}
          >
            <CalendarIcon />
            <span>Перенести</span>
          </button>

          <button
            type="button"
            className="btn btn--glass"
            onClick={() => onToggleStatus(record)}
          >
            {isDone ? (
              <>
                <UndoIcon />
                <span>Не выполнено</span>
              </>
            ) : (
              <>
                <CheckIcon />
                <span>Выполнено</span>
              </>
            )}
          </button>

          <button
            type="button"
            className="btn btn--glass btn--danger-icon"
            onClick={() => {
              onClose();
              onDelete(record);
            }}
            aria-label="Удалить запись"
            title="Удалить"
          >
            <TrashIcon />
          </button>
        </div>
      </div>
    </div>
  );
}

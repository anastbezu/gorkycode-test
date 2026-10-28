import { useEffect, useState } from 'react';
import { ApiError, createItem, setItemStatus, updateItem } from '../api/client';
import type { ActionResult, Record, RecordType } from '../api/types';
import { recordWhen } from '../lib/dates';
import {
  buildCreateItem,
  buildUpdateItem,
  initialFormValues,
  type RecordFormValues,
} from '../lib/recordForm';
import { CloseIcon } from './icons';

export type RecordDialogTarget =
  | { mode: 'create'; initialDay?: string }
  | { mode: 'edit'; record: Record };

interface Props {
  target: RecordDialogTarget;
  tz: string;
  onSuccess: (result: ActionResult) => void;
  onDelete: (record: Record) => void;
  onClose: () => void;
}

const TYPE_LABELS: { [k in RecordType]: string } = {
  task: 'Задача',
  meeting: 'Встреча',
  reminder: 'Напоминание',
};

export function RecordDialog({ target, tz, onSuccess, onDelete, onClose }: Props) {
  const isEdit = target.mode === 'edit';
  const originalRecord = isEdit ? target.record : null;

  const [values, setValues] = useState<RecordFormValues>(() => {
    if (isEdit) {
      return initialFormValues(target.record, tz);
    }
    const base = initialFormValues(null, tz);
    return { ...base, day: target.initialDay ?? '' };
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<Record[] | null>(null);
  const [pendingResult, setPendingResult] = useState<ActionResult | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const updateValidation = isEdit
    ? buildUpdateItem(originalRecord!, values, tz)
    : null;

  const handleSaveOrUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError(null);

    if (isEdit) {
      const { valid, item, error: valError } = updateValidation!;
      if (!valid) {
        setError(valError ?? 'Проверьте введённые данные');
        return;
      }
      if (!item) return;

      setLoading(true);
      try {
        const res = await updateItem(originalRecord!.id, item, tz);
        if (res.conflicts && res.conflicts.length > 0) {
          setConflicts(res.conflicts);
          setPendingResult(res);
        } else {
          onSuccess(res);
          onClose();
        }
      } catch (err) {
        handleApiError(err);
      } finally {
        setLoading(false);
      }
    } else {
      const { valid, item, error: valError } = buildCreateItem(values);
      if (!valid) {
        setError(valError ?? 'Проверьте введённые данные');
        return;
      }
      if (!item) return;

      setLoading(true);
      try {
        const res = await createItem(item, tz);
        if (res.conflicts && res.conflicts.length > 0) {
          setConflicts(res.conflicts);
          setPendingResult(res);
        } else {
          onSuccess(res);
          onClose();
        }
      } catch (err) {
        handleApiError(err);
      } finally {
        setLoading(false);
      }
    }
  };

  const handleToggleStatus = async () => {
    if (!originalRecord || loading) return;
    setLoading(true);
    setError(null);
    const nextStatus = originalRecord.status === 'done' ? 'active' : 'done';
    try {
      const res = await setItemStatus(originalRecord.id, nextStatus, tz);
      onSuccess(res);
      onClose();
    } catch (err) {
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = () => {
    if (!originalRecord || loading) return;
    onDelete(originalRecord);
    onClose();
  };

  const handleApiError = (err: unknown) => {
    if (err instanceof ApiError && err.kind === 'rejected') {
      setError(err.detail);
    } else {
      setError('Нет ответа от сервера, проверьте список.');
    }
  };

  if (conflicts && conflicts.length > 0) {
    return (
      <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
        <div className="modal__dialog" role="dialog" aria-modal="true">
          <div className="modal__head">
            <h2 className="modal__title">Пересечение встреч</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Закрыть">
              <CloseIcon />
            </button>
          </div>
          <div className="modal__conflict-warning">
            Встреча сохранена, но пересекается с другими записями:
          </div>
          <div className="modal__conflict-list">
            {conflicts.map((c) => (
              <div key={c.id} className="modal__conflict-item">
                <span className="modal__conflict-title">{c.title}</span>
                <span className="modal__conflict-time">{recordWhen(c, tz)}</span>
              </div>
            ))}
          </div>
          <div className="modal__actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => {
                if (pendingResult) onSuccess(pendingResult);
                onClose();
              }}
            >
              Понятно
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="modal__dialog"
        onSubmit={handleSaveOrUpdate}
        role="dialog"
        aria-modal="true"
        aria-labelledby="record-dialog-title"
      >
        <div className="modal__head">
          <h2 id="record-dialog-title" className="modal__title">
            {isEdit ? 'Запись' : 'Новая запись'}
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Закрыть" disabled={loading}>
            <CloseIcon />
          </button>
        </div>

        {!isEdit && (
          <div className="auth-tabs" role="tablist">
            {(['task', 'meeting', 'reminder'] as RecordType[]).map((type) => (
              <button
                key={type}
                type="button"
                role="tab"
                aria-selected={values.type === type}
                className={`auth-tab${values.type === type ? ' auth-tab--active' : ''}`}
                onClick={() =>
                  setValues((v) => ({
                    ...v,
                    type,
                    allDay: type === 'meeting' ? false : v.allDay,
                  }))
                }
                disabled={loading}
              >
                {TYPE_LABELS[type]}
              </button>
            ))}
          </div>
        )}

        {isEdit && (
          <div className="record-dialog__type-badge">
            <span className="tag tag--type">{TYPE_LABELS[values.type]}</span>
            <span className={`tag tag--${originalRecord!.status}`}>
              {originalRecord!.status === 'done' ? 'Выполнено' : 'Активно'}
            </span>
          </div>
        )}

        <label className="field">
          <span className="field__label">Название</span>
          <input
            className="field__input"
            value={values.title}
            onChange={(e) => setValues((v) => ({ ...v, title: e.target.value }))}
            placeholder="Название записи"
            autoFocus
            required
            disabled={loading}
          />
        </label>

        <div className="field__row">
          <label className="field" style={{ flex: 1 }}>
            <span className="field__label">
              {values.type === 'meeting' ? 'Дата встречи *' : 'Дата'}
            </span>
            <input
              type="date"
              className="field__input"
              value={values.day}
              onChange={(e) => setValues((v) => ({ ...v, day: e.target.value }))}
              disabled={loading}
            />
          </label>

          {values.type !== 'meeting' && (
            <label className="field__checkbox-label">
              <input
                type="checkbox"
                checked={values.allDay}
                onChange={(e) => setValues((v) => ({ ...v, allDay: e.target.checked }))}
                disabled={loading}
              />
              <span>Весь день</span>
            </label>
          )}

          {!values.allDay && (
            <label className="field" style={{ flex: 1 }}>
              <span className="field__label">
                {values.type === 'meeting' ? 'Время *' : 'Время'}
              </span>
              <input
                type="time"
                className="field__input"
                value={values.time}
                onChange={(e) => setValues((v) => ({ ...v, time: e.target.value }))}
                disabled={loading}
              />
            </label>
          )}
        </div>

        {values.type === 'task' && (
          <div className="field__row">
            <label className="field" style={{ flex: 1 }}>
              <span className="field__label">Срок (дедлайн)</span>
              <input
                type="date"
                className="field__input"
                value={values.deadlineDay}
                onChange={(e) => setValues((v) => ({ ...v, deadlineDay: e.target.value }))}
                disabled={loading}
              />
            </label>
            {values.deadlineDay && (
              <label className="field" style={{ flex: 1 }}>
                <span className="field__label">Время срока</span>
                <input
                  type="time"
                  className="field__input"
                  value={values.deadlineTime}
                  onChange={(e) => setValues((v) => ({ ...v, deadlineTime: e.target.value }))}
                  placeholder="23:59"
                  disabled={loading}
                />
              </label>
            )}
          </div>
        )}

        {error && (
          <div className="field__error" role="alert">
            {error}
          </div>
        )}

        <div className="modal__actions modal__actions--record">
          {isEdit ? (
            <>
              <button
                type="button"
                className="btn btn--danger"
                onClick={handleDelete}
                disabled={loading}
              >
                Удалить
              </button>
              <button
                type="button"
                className="btn btn--glass"
                onClick={handleToggleStatus}
                disabled={loading}
              >
                {originalRecord!.status === 'done' ? 'Не выполнено' : 'Выполнено'}
              </button>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={loading || !updateValidation?.item}
              >
                {loading ? 'Сохранение…' : 'Сохранить'}
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn--glass" onClick={onClose} disabled={loading}>
                Отмена
              </button>
              <button type="submit" className="btn btn--primary" disabled={loading}>
                {loading ? 'Создание…' : 'Создать'}
              </button>
            </>
          )}
        </div>
      </form>
    </div>
  );
}

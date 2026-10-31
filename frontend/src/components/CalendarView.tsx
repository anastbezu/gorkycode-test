// Календарь (фреймы «Календарь · месяц», «Календарь · неделя», «Календарь · день» и их мобильные версии):
// Переключатель режимов «День / Неделя / Месяц», сетка времени 00:00–23:00 (24 часа со скроллом и автоскроллом к утру),
// строка «весь день», красная полоска текущего времени, пустые состояния и мобильная адаптация.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, fetchItems } from '../api/client';
import type { Record } from '../api/types';
import {
  addDaysToKey,
  dayKey,
  dayTitle,
  localMidnightIso,
  monthGrid,
  monthTitle,
  MONTHS_GENITIVE,
  recordTime,
  recordWhenInDay,
  wallTime,
  weekOf,
} from '../lib/dates';
import { NextIcon, PrevIcon } from './icons';
import { groupByDay, TaskCard, type PanelState } from './TasksPanel';

export type CalendarMode = 'day' | 'week' | 'month';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const TIMELINE_START_HOUR = 0;
const TIMELINE_END_HOUR = 23;
const TIMELINE_HOURS = Array.from(
  { length: TIMELINE_END_HOUR - TIMELINE_START_HOUR + 1 },
  (_, i) => TIMELINE_START_HOUR + i,
);

interface Props {
  tz: string;
  reloadKey?: number;
  onOpen?: (record: Record) => void;
  onCreate?: (dayKey?: string) => void;
  onEdit?: (record: Record) => void;
  onToggleStatus?: (record: Record) => void;
  onDelete?: (record: Record) => void;
}

export function formatWeekTitle(weekDays: string[]): string {
  if (weekDays.length < 7) return '';
  const first = weekDays[0];
  const last = weekDays[6];
  const [y1, m1, d1] = first.split('-').map(Number);
  const [y2, m2, d2] = last.split('-').map(Number);

  if (m1 === m2 && y1 === y2) {
    return `${d1} – ${d2} ${MONTHS_GENITIVE[m1 - 1]} ${y1}`;
  }
  if (y1 === y2) {
    return `${d1} ${MONTHS_GENITIVE[m1 - 1]} – ${d2} ${MONTHS_GENITIVE[m2 - 1]} ${y1}`;
  }
  return `${d1} ${MONTHS_GENITIVE[m1 - 1]} ${y1} – ${d2} ${MONTHS_GENITIVE[m2 - 1]} ${y2}`;
}

export function CalendarView({
  tz,
  reloadKey,
  onOpen,
  onCreate,
  onEdit,
  onToggleStatus,
  onDelete,
}: Props) {
  const todayKey = dayKey(new Date(), tz);
  const [mode, setMode] = useState<CalendarMode>('month');
  const [month, setMonth] = useState(() => ({
    year: Number(todayKey.slice(0, 4)),
    month: Number(todayKey.slice(5, 7)),
  }));
  const [selectedDay, setSelectedDay] = useState(todayKey);
  const [state, setState] = useState<PanelState>({ status: 'loading', records: [] });
  const latest = useRef(0);
  const timelineScrollRef = useRef<HTMLDivElement>(null);

  const grid = monthGrid(month.year, month.month);
  const currentWeek = weekOf(selectedDay);

  // Определение диапазона дат для запроса /api/items в зависимости от режима
  const load = useCallback(async () => {
    const request = ++latest.current;
    setState({ status: 'loading', records: [] });

    let fromKey = grid[0];
    let toKey = addDaysToKey(grid[grid.length - 1], 1);

    if (mode === 'day') {
      fromKey = selectedDay;
      toKey = addDaysToKey(selectedDay, 1);
    } else if (mode === 'week') {
      const week = weekOf(selectedDay);
      fromKey = week[0];
      toKey = addDaysToKey(week[6], 1);
    }

    try {
      const records = await fetchItems({
        from: localMidnightIso(fromKey),
        to: localMidnightIso(toKey),
        tz,
        includeUndated: true,
      });
      if (request === latest.current) setState({ status: 'ready', records });
    } catch (err) {
      if (request !== latest.current) return;
      const message =
        err instanceof ApiError && err.kind === 'rejected' ? err.detail : 'Нет ответа от сервера.';
      setState({ status: 'error', records: [], message });
    }
  }, [mode, month, selectedDay, tz]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  const { byDay } = groupByDay(state.records, tz);

  // Переключение периодов назад/вперёд
  const handlePrev = () => {
    if (mode === 'month') {
      shiftMonth(-1);
    } else if (mode === 'week') {
      const nextDay = addDaysToKey(selectedDay, -7);
      setSelectedDay(nextDay);
      const [y, m] = nextDay.split('-').map(Number);
      setMonth({ year: y, month: m });
    } else {
      const nextDay = addDaysToKey(selectedDay, -1);
      setSelectedDay(nextDay);
      const [y, m] = nextDay.split('-').map(Number);
      setMonth({ year: y, month: m });
    }
  };

  const handleNext = () => {
    if (mode === 'month') {
      shiftMonth(1);
    } else if (mode === 'week') {
      const nextDay = addDaysToKey(selectedDay, 7);
      setSelectedDay(nextDay);
      const [y, m] = nextDay.split('-').map(Number);
      setMonth({ year: y, month: m });
    } else {
      const nextDay = addDaysToKey(selectedDay, 1);
      setSelectedDay(nextDay);
      const [y, m] = nextDay.split('-').map(Number);
      setMonth({ year: y, month: m });
    }
  };

  const shiftMonth = (delta: number) => {
    const index = month.year * 12 + (month.month - 1) + delta;
    const next = { year: Math.floor(index / 12), month: (index % 12) + 1 };
    setMonth(next);
    const nextKey = `${next.year}-${String(next.month).padStart(2, '0')}`;
    setSelectedDay(todayKey.startsWith(nextKey) ? todayKey : `${nextKey}-01`);
  };

  // Вычисление позиции события на временной шкале (в минутах от 00:00)
  const getEventPosition = (record: Record) => {
    if (!record.start) return null;
    const wt = wallTime(new Date(record.start), tz);
    const startMins = wt.hour * 60 + wt.minute;
    const top = Math.max(0, startMins);

    let durationMins = 60;
    if (record.end) {
      const endMins = (Date.parse(record.end) - Date.parse(record.start)) / (60 * 1000);
      if (endMins > 0) durationMins = endMins;
    }
    const height = Math.max(28, durationMins);
    return { top, height };
  };

  // Текущая красная линия времени
  const now = new Date();
  const nowWall = wallTime(now, tz);
  const nowMinutes = nowWall.hour * 60 + nowWall.minute;
  const nowLineTop = nowMinutes;

  // Автоскролл к утру (08:00) или к текущему часу при открытии дня/недели
  useEffect(() => {
    if (timelineScrollRef.current && (mode === 'day' || mode === 'week')) {
      const targetHour = selectedDay === todayKey ? Math.max(0, nowWall.hour - 1) : 8;
      timelineScrollRef.current.scrollTop = targetHour * 60;
    }
  }, [mode, selectedDay, todayKey, nowWall.hour]);

  // --- Рендер дня в сетке месяца ---
  const monthKey = `${month.year}-${String(month.month).padStart(2, '0')}`;
  const renderMonthDay = (key: string) => {
    const outside = !key.startsWith(monthKey);
    const isSelected = key === selectedDay;
    return (
      <button
        key={key}
        type="button"
        className={`cal__day${outside ? ' cal__day--outside' : ''}${isSelected ? ' cal__day--selected' : ''}`}
        onClick={() => setSelectedDay(key)}
        aria-pressed={isSelected}
        aria-label={dayTitle(key, todayKey)}
      >
        <span>{Number(key.slice(8))}</span>
        <span className={`days__dot${(byDay.get(key)?.length ?? 0) > 0 ? ' days__dot--on' : ''}`} />
      </button>
    );
  };

  const renderSegmentedControls = () => (
    <div className="cal-card__controls">
      <div className="segmented-control" role="group" aria-label="Режим календаря">
        <button
          type="button"
          className={`segmented-btn ${mode === 'day' ? 'segmented-btn--active' : ''}`}
          onClick={() => setMode('day')}
        >
          День
        </button>
        <button
          type="button"
          className={`segmented-btn ${mode === 'week' ? 'segmented-btn--active' : ''}`}
          onClick={() => setMode('week')}
        >
          Неделя
        </button>
        <button
          type="button"
          className={`segmented-btn ${mode === 'month' ? 'segmented-btn--active' : ''}`}
          onClick={() => setMode('month')}
        >
          Месяц
        </button>
      </div>

      <div className="cal-header__nav">
        <button type="button" className="icon-btn" onClick={handlePrev} aria-label="Назад">
          <PrevIcon />
        </button>
        <button type="button" className="icon-btn" onClick={handleNext} aria-label="Вперёд">
          <NextIcon />
        </button>
      </div>
    </div>
  );

  return (
    <div className={`calendar-container calendar-container--${mode}`}>
      {/* --- ВИД «МЕСЯЦ» --- */}
      {mode === 'month' && (
        <div className="cal-month-layout">
          <section className="cal-month-card">
            <div className="cal-card__head">
              <h2 className="cal-card__title">{monthTitle(month.year, month.month)}</h2>
              {renderSegmentedControls()}
            </div>

            <div className="cal__grid cal__grid--names" aria-hidden>
              {WEEKDAYS.map((name) => (
                <span key={name} className="cal__weekday">
                  {name}
                </span>
              ))}
            </div>
            <div className="cal__grid cal__grid--month">{grid.map(renderMonthDay)}</div>
          </section>

          <section className="cal-month-sidebar">
            <div className="cal-day__head">
              <h2 className="cal-day__title">{dayTitle(selectedDay, todayKey)}</h2>
              {onCreate && (
                <button
                  type="button"
                  className="btn btn--glass cal-day__create-btn"
                  onClick={() => onCreate(selectedDay)}
                >
                  + Создать
                </button>
              )}
            </div>

            <div className="cal-month-sidebar__list">
              {state.status === 'error' && (
                <div className="panel__note">
                  <p>Не удалось загрузить дела. {state.message}</p>
                  <button type="button" className="btn btn--glass" onClick={() => void load()}>
                    Повторить
                  </button>
                </div>
              )}
              {state.status === 'loading' && <p className="panel__note">Загружаю дела…</p>}
              {state.status === 'ready' && (byDay.get(selectedDay) ?? []).length === 0 && (
                <p className="panel__note">На этот день дел нет.</p>
              )}
              {(byDay.get(selectedDay) ?? []).map((record) => (
                <TaskCard
                  key={record.id}
                  record={record}
                  tz={tz}
                  now={now}
                  when={recordWhenInDay(record, tz)}
                  onOpen={onOpen}
                  onToggleStatus={onToggleStatus}
                  onEdit={onEdit}
                  onDelete={onDelete}
                />
              ))}
            </div>

            {onCreate && (
              <button
                type="button"
                className="cal-month-add-btn"
                onClick={() => onCreate(selectedDay)}
              >
                + Добавить на этот день
              </button>
            )}
          </section>
        </div>
      )}

      {/* --- ВИД «ДЕНЬ» --- */}
      {mode === 'day' && (
        <div className="cal-view-wrap">
          <div className="cal-card">
            <div className="cal-card__head">
              <h2 className="cal-card__title">{dayTitle(selectedDay, todayKey)}</h2>
              {renderSegmentedControls()}
            </div>

            <div className="cal-day-view__col-header">
              <span className="cal-day-view__col-weekday">
                {WEEKDAYS[(new Date(selectedDay).getDay() + 6) % 7]}
              </span>
              <span
                className={`cal-day-view__col-num ${selectedDay === todayKey ? 'cal-day-view__col-num--today' : ''}`}
              >
                {Number(selectedDay.slice(8))}
              </span>
            </div>

            {/* Строка «весь день» */}
            <div className="timeline-allday">
              <span className="timeline-allday__label">весь день</span>
              <div className="timeline-allday__content">
                {(byDay.get(selectedDay) ?? [])
                  .filter((r) => r.all_day || (!r.start && r.deadline))
                  .map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      className="timeline-badge"
                      onClick={() => onOpen?.(r)}
                    >
                      {r.title}
                    </button>
                  ))}
              </div>
            </div>

            {/* Временная шкала 00:00–23:00 со скроллом */}
            <div className="timeline-scroll-wrap" ref={timelineScrollRef}>
              <div className="timeline-wrap">
                <div className="timeline-hours">
                  {TIMELINE_HOURS.map((h) => (
                    <div key={h} className="timeline-hour">
                      <span>{String(h).padStart(2, '0')}:00</span>
                    </div>
                  ))}
                </div>

                <div className="timeline-grid">
                  {TIMELINE_HOURS.map((h) => (
                    <div key={h} className="timeline-grid__line" />
                  ))}

                  {/* Красная линия текущего времени */}
                  {selectedDay === todayKey && (
                    <div
                      className="timeline-now-line"
                      style={{ top: `${nowLineTop}px` }}
                      title="Текущее время"
                    />
                  )}

                  {/* События дня */}
                  {(byDay.get(selectedDay) ?? [])
                    .filter((r) => !r.all_day && r.start)
                    .map((record) => {
                      const pos = getEventPosition(record);
                      if (!pos) return null;
                      const timeLabel = recordTime(record, tz);
                      const isDone = record.status === 'done';

                      return (
                        <div
                          key={record.id}
                          className={`timeline-event timeline-event--${record.type}${isDone ? ' timeline-event--done' : ''}`}
                          style={{ top: `${pos.top}px`, height: `${pos.height}px` }}
                          onClick={() => onOpen?.(record)}
                          role="button"
                          tabIndex={0}
                        >
                          <span className="timeline-event__time">{timeLabel}</span>
                          <span className="timeline-event__title">{record.title}</span>
                        </div>
                      );
                    })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* --- ВИД «НЕДЕЛЯ» --- */}
      {mode === 'week' && (
        <div className="cal-view-wrap">
          <div className="cal-card">
            <div className="cal-card__head">
              <h2 className="cal-card__title">{formatWeekTitle(currentWeek)}</h2>
              {renderSegmentedControls()}
            </div>

            {/* Десктопная 7-колоночная сетка */}
            <div className="cal-week-desktop">
              <div className="cal-week-grid__header">
                <div className="cal-week-grid__gutter" />
                {currentWeek.map((key) => {
                  const dayNum = Number(key.slice(8));
                  const weekday = WEEKDAYS[(new Date(key).getDay() + 6) % 7];
                  const isToday = key === todayKey;
                  return (
                    <div key={key} className={`cal-week-col-header ${isToday ? 'cal-week-col-header--today' : ''}`}>
                      <span className="cal-week-col-header__day">{weekday}</span>
                      <span className="cal-week-col-header__num">{dayNum}</span>
                    </div>
                  );
                })}
              </div>

              {/* Строка «весь день» */}
              <div className="cal-week-allday">
                <div className="cal-week-allday__gutter">весь день</div>
                <div className="cal-week-allday__cols">
                  {currentWeek.map((key) => (
                    <div key={key} className="cal-week-allday__col">
                      {(byDay.get(key) ?? [])
                        .filter((r) => r.all_day || (!r.start && r.deadline))
                        .map((r) => (
                          <button
                            key={r.id}
                            type="button"
                            className="timeline-badge"
                            onClick={() => onOpen?.(r)}
                          >
                            {r.title}
                          </button>
                        ))}
                    </div>
                  ))}
                </div>
              </div>

              {/* 7-колоночный таймлайн 00:00–23:00 со скроллом */}
              <div className="timeline-scroll-wrap" ref={timelineScrollRef}>
                <div className="cal-week-timeline">
                  <div className="timeline-hours">
                    {TIMELINE_HOURS.map((h) => (
                      <div key={h} className="timeline-hour">
                        <span>{String(h).padStart(2, '0')}:00</span>
                      </div>
                    ))}
                  </div>

                  <div className="cal-week-cols">
                    {currentWeek.map((key) => {
                      const isToday = key === todayKey;
                      const dayRecords = (byDay.get(key) ?? []).filter((r) => !r.all_day && r.start);

                      return (
                        <div key={key} className="cal-week-col">
                          {TIMELINE_HOURS.map((h) => (
                            <div key={h} className="timeline-grid__line" />
                          ))}

                          {isToday && (
                            <div
                              className="timeline-now-line"
                              style={{ top: `${nowLineTop}px` }}
                              title="Текущее время"
                            />
                          )}

                          {dayRecords.map((record) => {
                            const pos = getEventPosition(record);
                            if (!pos) return null;
                            const timeLabel = recordTime(record, tz);
                            const isDone = record.status === 'done';

                            return (
                              <div
                                key={record.id}
                                className={`timeline-event timeline-event--${record.type}${isDone ? ' timeline-event--done' : ''}`}
                                style={{ top: `${pos.top}px`, height: `${pos.height}px` }}
                                onClick={() => onOpen?.(record)}
                                role="button"
                                tabIndex={0}
                              >
                                <span className="timeline-event__time">{timeLabel}</span>
                                <span className="timeline-event__title">{record.title}</span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>

            {/* Мобильный список по дням */}
            <div className="cal-week-mobile">
              {currentWeek.map((key) => {
                const records = byDay.get(key) ?? [];
                const isToday = key === todayKey;
                const title = dayTitle(key, todayKey);

                return (
                  <div key={key} className="cal-week-mobile__day-group">
                    <div className={`cal-week-mobile__day-title ${isToday ? 'cal-week-mobile__day-title--today' : ''}`}>
                      {title} {records.length === 0 ? '— дел нет' : ''}
                    </div>
                    {records.map((record) => (
                      <TaskCard
                        key={record.id}
                        record={record}
                        tz={tz}
                        now={now}
                        when={recordWhenInDay(record, tz)}
                        onOpen={onOpen}
                        onToggleStatus={onToggleStatus}
                        onEdit={onEdit}
                        onDelete={onDelete}
                      />
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

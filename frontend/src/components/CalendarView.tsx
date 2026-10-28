// Календарь (фреймы «Календарь» и «Мобильная · календарь»): месяц слева, дела выбранного дня справа.
// На телефоне — неделя выбранного дня; потянуть за полоску (нажать) — развернуть весь месяц.
// Данные — один GET /api/items на видимую сетку месяца, без записей «без даты»: у них нет дня.
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
  recordWhenInDay,
  weekOf,
} from '../lib/dates';
import { NextIcon, PrevIcon } from './icons';
import { groupByDay, TaskCard, type PanelState } from './TasksPanel';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

interface Props {
  tz: string;
  reloadKey?: number;
  onOpen?: (record: Record) => void;
  onCreate?: (dayKey?: string) => void;
}

export function CalendarView({ tz, reloadKey, onOpen, onCreate }: Props) {
  const todayKey = dayKey(new Date(), tz);
  const [month, setMonth] = useState(() => ({ year: Number(todayKey.slice(0, 4)), month: Number(todayKey.slice(5, 7)) }));
  const [selected, setSelected] = useState(todayKey);
  const [expanded, setExpanded] = useState(false);
  const [state, setState] = useState<PanelState>({ status: 'loading', records: [] });
  const latest = useRef(0);

  const grid = monthGrid(month.year, month.month);

  const load = useCallback(async () => {
    const request = ++latest.current;
    const days = monthGrid(month.year, month.month);
    setState({ status: 'loading', records: [] });
    try {
      const records = await fetchItems({
        from: localMidnightIso(days[0]),
        to: localMidnightIso(addDaysToKey(days[days.length - 1], 1)),
        tz,
        includeUndated: false,
      });
      if (request === latest.current) setState({ status: 'ready', records });
    } catch (err) {
      if (request !== latest.current) return;
      const message = err instanceof ApiError && err.kind === 'rejected' ? err.detail : 'Нет ответа от сервера.';
      setState({ status: 'error', records: [], message });
    }
  }, [month, tz]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  const { byDay } = groupByDay(state.records, tz);
  const dayRecords = byDay.get(selected) ?? [];
  const monthKey = `${month.year}-${String(month.month).padStart(2, '0')}`;

  const shiftMonth = (delta: number) => {
    const index = month.year * 12 + (month.month - 1) + delta;
    const next = { year: Math.floor(index / 12), month: (index % 12) + 1 };
    setMonth(next);
    // В текущем месяце — сегодня, в другом — его первое число
    const nextKey = `${next.year}-${String(next.month).padStart(2, '0')}`;
    setSelected(todayKey.startsWith(nextKey) ? todayKey : `${nextKey}-01`);
  };

  const renderDay = (key: string) => {
    const outside = !key.startsWith(monthKey);
    const isSelected = key === selected;
    return (
      <button
        key={key}
        type="button"
        className={`cal__day${outside ? ' cal__day--outside' : ''}${isSelected ? ' cal__day--selected' : ''}`}
        onClick={() => setSelected(key)}
        aria-pressed={isSelected}
        aria-label={dayTitle(key, todayKey)}
      >
        <span>{Number(key.slice(8))}</span>
        <span className={`days__dot${(byDay.get(key)?.length ?? 0) > 0 ? ' days__dot--on' : ''}`} />
      </button>
    );
  };

  // Свёрнутый вид телефона — неделя выбранного дня (если он в показанном месяце)
  const week = weekOf(selected.startsWith(monthKey) ? selected : grid[0]);

  return (
    <div className={`calendar${expanded ? ' calendar--expanded' : ''}`}>
      <section className="cal">
        <div className="cal__head">
          <h2 className="cal__title">{monthTitle(month.year, month.month)}</h2>
          <div className="cal__nav">
            <button type="button" className="icon-btn" onClick={() => shiftMonth(-1)} aria-label="Предыдущий месяц">
              <PrevIcon />
            </button>
            <button type="button" className="icon-btn" onClick={() => shiftMonth(1)} aria-label="Следующий месяц">
              <NextIcon />
            </button>
          </div>
        </div>
        <div className="cal__grid cal__grid--names" aria-hidden>
          {WEEKDAYS.map((name) => (
            <span key={name} className="cal__weekday">
              {name}
            </span>
          ))}
        </div>
        <div className="cal__grid cal__grid--month">{grid.map(renderDay)}</div>
        <div className="cal__grid cal__grid--week">{week.map(renderDay)}</div>
        <button
          type="button"
          className="cal__handle"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? 'Свернуть до недели' : 'Показать весь месяц'}
        />
      </section>

      <section className="cal-day">
        <div className="cal-day__head">
          <h2 className="cal-day__title">{dayTitle(selected, todayKey)}</h2>
          {onCreate && (
            <button
              type="button"
              className="btn btn--glass cal-day__create-btn"
              onClick={() => onCreate(selected)}
            >
              + Создать
            </button>
          )}
        </div>
        {state.status === 'error' && (
          <div className="panel__note">
            <p>Не удалось загрузить дела. {state.message}</p>
            <button type="button" className="btn btn--glass" onClick={() => void load()}>
              Повторить
            </button>
          </div>
        )}
        {state.status === 'loading' && <p className="panel__note">Загружаю дела…</p>}
        {state.status === 'ready' && dayRecords.length === 0 && <p className="panel__note">На этот день дел нет.</p>}
        {dayRecords.map((record) => (
          <TaskCard
            key={record.id}
            record={record}
            tz={tz}
            now={new Date()}
            when={recordWhenInDay(record, tz)}
            onOpen={onOpen}
          />
        ))}
      </section>
    </div>
  );
}

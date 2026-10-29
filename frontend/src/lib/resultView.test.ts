import { describe, expect, it } from 'vitest';
import type { ActionResult, Record } from '../api/types';
import {
  formatCancelledCount,
  formatCreatedCount,
  formatDoneCount,
  formatRecordPlural,
  resolveResultView,
} from './resultView';

const MSK = 'Europe/Moscow';
const NOW = new Date('2026-10-26T09:00:00Z');

function makeRecord(fields: Partial<Record>): Record {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    user_id: '00000000-0000-0000-0000-000000000002',
    type: 'task',
    title: 'Тестовая запись',
    start: null,
    end: null,
    all_day: false,
    deadline: null,
    status: 'active',
    created_at: '2026-10-26T09:00:00Z',
    ...fields,
  };
}

function makeResult(fields: Partial<ActionResult>): ActionResult {
  return {
    action: 'create_record',
    ok: true,
    records: [],
    conflicts: [],
    candidates: [],
    restored: [],
    missing: [],
    error: null,
    ...fields,
  };
}

describe('склонение числительных и подписи счётчиков', () => {
  it('форма слова «запись» для 1, 2, 5, 11, 21, 22', () => {
    expect(formatRecordPlural(1)).toBe('запись');
    expect(formatRecordPlural(2)).toBe('записи');
    expect(formatRecordPlural(5)).toBe('записей');
    expect(formatRecordPlural(11)).toBe('записей');
    expect(formatRecordPlural(21)).toBe('запись');
    expect(formatRecordPlural(22)).toBe('записи');
  });

  it('форма «Создано / Создана N записей»', () => {
    expect(formatCreatedCount(1)).toBe('Создана 1 запись');
    expect(formatCreatedCount(2)).toBe('Создано 2 записи');
    expect(formatCreatedCount(3)).toBe('Создано 3 записи');
    expect(formatCreatedCount(5)).toBe('Создано 5 записей');
    expect(formatCreatedCount(21)).toBe('Создана 21 запись');
  });

  it('форма «Выполнено / Отменено N записей»', () => {
    expect(formatDoneCount(2)).toBe('Выполнено 2 записи');
    expect(formatDoneCount(5)).toBe('Выполнено 5 записей');
    expect(formatCancelledCount(3)).toBe('Отменено 3 записи');
    expect(formatCancelledCount(10)).toBe('Отменено 10 записей');
  });
});

describe('resolveResultView — выбор вида по таблице требований', () => {
  it('ok = false — ничего не показывается (только текст)', () => {
    const res = makeResult({ ok: false, action: 'update_record' });
    expect(resolveResultView(res, null, MSK, NOW)).toBeNull();
  });

  it('awaiting не пусто — ничего не показывается', () => {
    const res = makeResult({
      action: 'create_record',
      records: [makeRecord({ title: 'Купить молоко' })],
    });
    expect(resolveResultView(res, 'answer', MSK, NOW)).toBeNull();
    expect(resolveResultView(res, 'choice', MSK, NOW)).toBeNull();
  });

  it('candidates не пусто — только текст', () => {
    const res = makeResult({
      action: 'update_record',
      candidates: [makeRecord({ title: 'Планёрка' })],
    });
    expect(resolveResultView(res, null, MSK, NOW)).toBeNull();
  });

  it('create_record, одна запись: задача без срока -> «без срока»', () => {
    const rec = makeRecord({ type: 'task', title: 'Починить кран' });
    const res = makeResult({ action: 'create_record', records: [rec] });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view).toEqual({
      type: 'cards',
      cards: [
        {
          kind: 'single_card',
          record: rec,
          tag: 'Задача создана',
          tagVariant: 'lime',
          title: 'Починить кран',
          when: 'без срока',
          actionType: 'default',
          hasConflict: false,
          conflicts: [],
        },
      ],
    });
  });

  it('create_record, одна запись: встреча с окончанием и пересечением', () => {
    const rec = makeRecord({
      type: 'meeting',
      title: 'Встреча с Игорем',
      start: '2026-10-27T12:00:00Z',
      end: '2026-10-27T13:30:00Z',
    });
    const conflict = makeRecord({
      id: 'conf-1',
      type: 'meeting',
      title: 'Созвон с клиентом',
      start: '2026-10-27T12:30:00Z',
      end: '2026-10-27T13:00:00Z',
    });
    const res = makeResult({
      action: 'create_record',
      records: [rec],
      conflicts: [conflict],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      const card = view.cards[0];
      expect(card.kind).toBe('single_card');
      if (card.kind === 'single_card') {
        expect(card.tag).toBe('Встреча создана');
        expect(card.tagVariant).toBe('lime');
        expect(card.hasConflict).toBe(true);
        expect(card.conflicts).toHaveLength(1);
        expect(card.conflicts[0].title).toBe('Созвон с клиентом');
        expect(card.conflicts[0].time).toBe('15:30–16:00');
      }
    }
  });

  it('create_record, 3 записи: одна сводная карточка «Создано 3 записи»', () => {
    const r1 = makeRecord({ id: '1', title: 'Планёрка', start: '2026-11-02T07:00:00Z' });
    const r2 = makeRecord({ id: '2', title: 'Отправить отчёт', deadline: '2026-11-02T23:59:59Z' });
    const r3 = makeRecord({ id: '3', title: 'Позвонить маме', start: '2026-11-02T17:00:00Z' });

    const res = makeResult({
      action: 'create_record',
      records: [r1, r2, r3],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      expect(view.cards).toHaveLength(1);
      const card = view.cards[0];
      expect(card.kind).toBe('multi_created');
      if (card.kind === 'multi_created') {
        expect(card.tag).toBe('Создано 3 записи');
        expect(card.items).toHaveLength(3);
        expect(card.items[0].title).toBe('Планёрка');
        expect(card.items[1].title).toBe('Отправить отчёт');
        expect(card.items[2].title).toBe('Позвонить маме');
      }
    }
  });

  it('update_record: карточка с тегом «… изменена» (фиолетовый)', () => {
    const rec = makeRecord({
      type: 'task',
      title: 'Позвонить в банк и в страховую',
      start: '2026-10-27T09:30:00Z',
    });
    const res = makeResult({
      action: 'update_record',
      records: [rec],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      const card = view.cards[0];
      expect(card.kind).toBe('single_card');
      if (card.kind === 'single_card') {
        expect(card.tag).toBe('Задача изменена');
        expect(card.tagVariant).toBe('violet');
      }
    }
  });

  it('update_record с restored («не эту, а ту») — только основная карточка изменения', () => {
    const rec = makeRecord({
      type: 'meeting',
      title: 'Планёрка',
      start: '2026-10-30T07:00:00Z',
    });
    const restored = makeRecord({
      type: 'meeting',
      title: 'Старая встреча',
      start: '2026-10-29T07:00:00Z',
    });
    const res = makeResult({
      action: 'update_record',
      records: [rec],
      restored: [restored],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      expect(view.cards).toHaveLength(1);
      expect(view.cards[0].kind).toBe('single_card');
      if (view.cards[0].kind === 'single_card') {
        expect(view.cards[0].title).toBe('Планёрка');
        expect(view.cards[0].tag).toBe('Встреча изменена');
      }
    }
  });

  it('set_status done: карточка «✓ Выполнено», название зачёркнуто', () => {
    const rec = makeRecord({
      type: 'reminder',
      title: 'Выпить таблетки',
      status: 'done',
    });
    const res = makeResult({
      action: 'set_status',
      records: [rec],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      const card = view.cards[0];
      expect(card.kind).toBe('single_card');
      if (card.kind === 'single_card') {
        expect(card.tag).toBe('✓ Выполнено');
        expect(card.tagVariant).toBe('gray');
        expect(card.titleStrikethrough).toBe(true);
        expect(card.actionType).toBe('done');
      }
    }
  });

  it('set_status cancelled: карточка «Отменено» с подсказкой «Скажите «верни»»', () => {
    const rec = makeRecord({
      type: 'meeting',
      title: 'Созвон с клиентом',
      status: 'cancelled',
    });
    const res = makeResult({
      action: 'set_status',
      records: [rec],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      const card = view.cards[0];
      expect(card.kind).toBe('single_card');
      if (card.kind === 'single_card') {
        expect(card.tag).toBe('Отменено');
        expect(card.tagVariant).toBe('gray');
        expect(card.titleStrikethrough).toBe(true);
        expect(card.footerNote).toBe('Передумали? Скажите «верни»');
        expect(card.actionType).toBe('cancelled');
      }
    }
  });

  it('set_status active: карточка «Возвращено» (фиолетовый тег)', () => {
    const rec = makeRecord({
      type: 'meeting',
      title: 'Созвон с клиентом',
      status: 'active',
    });
    const res = makeResult({
      action: 'set_status',
      records: [rec],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      const card = view.cards[0];
      expect(card.kind).toBe('single_card');
      if (card.kind === 'single_card') {
        expect(card.tag).toBe('Возвращено');
        expect(card.tagVariant).toBe('violet');
        expect(card.titleStrikethrough).toBe(false);
      }
    }
  });

  it('set_status с несколькими записями (массовое действие)', () => {
    const r1 = makeRecord({ id: '1', title: 'Дело 1', status: 'cancelled' });
    const r2 = makeRecord({ id: '2', title: 'Дело 2', status: 'cancelled' });
    const res = makeResult({
      action: 'set_status',
      records: [r1, r2],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      const card = view.cards[0];
      expect(card.kind).toBe('multi_status');
      if (card.kind === 'multi_status') {
        expect(card.tag).toBe('Отменено 2 записи');
        expect(card.items).toHaveLength(2);
      }
    }
  });

  it('undo_last с restored: карточка «Возвращено» на каждую запись', () => {
    const r1 = makeRecord({ id: '1', title: 'Встреча 1', status: 'active' });
    const r2 = makeRecord({ id: '2', title: 'Встреча 2', status: 'active' });
    const res = makeResult({
      action: 'undo_last',
      records: [],
      restored: [r1, r2],
    });
    const view = resolveResultView(res, null, MSK, NOW);

    expect(view?.type).toBe('cards');
    if (view?.type === 'cards') {
      expect(view.cards).toHaveLength(2);
      expect(view.cards[0].kind).toBe('single_card');
      if (view.cards[0].kind === 'single_card') {
        expect(view.cards[0].tag).toBe('Возвращено');
        expect(view.cards[0].title).toBe('Встреча 1');
      }
    }
  });

  it('list_records и search_records: тип list', () => {
    const r1 = makeRecord({ id: '1', title: 'Дело 1' });
    const resList = makeResult({ action: 'list_records', records: [r1] });
    expect(resolveResultView(resList, null, MSK, NOW)).toEqual({
      type: 'list',
      records: [r1],
    });

    const resSearch = makeResult({ action: 'search_records', records: [r1] });
    expect(resolveResultView(resSearch, null, MSK, NOW)).toEqual({
      type: 'list',
      records: [r1],
    });
  });

  it('help, ask_user — только текст (null)', () => {
    expect(resolveResultView(makeResult({ action: 'help' }), null, MSK, NOW)).toBeNull();
    expect(resolveResultView(makeResult({ action: 'ask_user' }), null, MSK, NOW)).toBeNull();
  });
});

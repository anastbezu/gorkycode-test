import { describe, expect, it, vi } from 'vitest';
import type { Record } from '../api/types';
import { RecordDetailsModal } from './RecordDetailsModal';

describe('RecordDetailsModal', () => {
  const sampleMeeting: Record = {
    id: 'rec_1',
    user_id: 'u1',
    type: 'meeting',
    title: 'Созвон с клиентом',
    status: 'active',
    start: '2026-10-25T11:00:00Z',
    end: '2026-10-25T12:00:00Z',
    all_day: false,
    deadline: null,
    created_at: '2026-10-25T00:00:00Z',
  };

  it('renders null if record is null', () => {
    const res = RecordDetailsModal({
      record: null,
      tz: 'Europe/Moscow',
      onClose: vi.fn(),
      onEdit: vi.fn(),
      onToggleStatus: vi.fn(),
      onDelete: vi.fn(),
    });
    expect(res).toBeNull();
  });

  it('renders record details properly', () => {
    const res = RecordDetailsModal({
      record: sampleMeeting,
      tz: 'Europe/Moscow',
      onClose: vi.fn(),
      onEdit: vi.fn(),
      onToggleStatus: vi.fn(),
      onDelete: vi.fn(),
    });
    expect(res).not.toBeNull();
  });
});

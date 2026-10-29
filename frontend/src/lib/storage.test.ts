import { beforeEach, describe, expect, it, vi } from 'vitest';
import { applyTheme, getActiveTheme, KEY_THEME, loadTheme, saveTheme } from './storage';

describe('theme storage and logic', () => {
  let store: Map<string, string>;
  let docAttrs: Map<string, string>;

  beforeEach(() => {
    store = new Map<string, string>();
    docAttrs = new Map<string, string>();

    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    });

    vi.stubGlobal('document', {
      documentElement: {
        getAttribute: (k: string) => docAttrs.get(k) ?? null,
        setAttribute: (k: string, v: string) => void docAttrs.set(k, v),
        removeAttribute: (k: string) => void docAttrs.delete(k),
        hasAttribute: (k: string) => docAttrs.has(k),
      },
    });

    vi.stubGlobal('window', {
      matchMedia: (query: string) => ({
        matches: query.includes('dark'),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
  });

  it('нет ключа — возвращается null (системная тема)', () => {
    expect(loadTheme()).toBeNull();
    expect(localStorage.getItem(KEY_THEME)).toBeNull();
  });

  it('сохранение темы и чтение при старте', () => {
    saveTheme('dark');
    expect(loadTheme()).toBe('dark');
    expect(localStorage.getItem(KEY_THEME)).toBe('dark');

    saveTheme('light');
    expect(loadTheme()).toBe('light');
    expect(localStorage.getItem(KEY_THEME)).toBe('light');

    saveTheme(null);
    expect(loadTheme()).toBeNull();
    expect(localStorage.getItem(KEY_THEME)).toBeNull();
  });

  it('applyTheme выставляет и удаляет атрибут data-theme на <html>', () => {
    applyTheme('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

    applyTheme('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    applyTheme(null);
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('getActiveTheme использует значение из localStorage при наличии, иначе системное', () => {
    // Без ключа — системная (в стабе matchMedia dark = true)
    expect(getActiveTheme()).toBe('dark');

    saveTheme('light');
    expect(getActiveTheme()).toBe('light');

    saveTheme('dark');
    expect(getActiveTheme()).toBe('dark');
  });
});

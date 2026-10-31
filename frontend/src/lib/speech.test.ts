// Озвучка: какой голос выбирается, что бывает без русского голоса, и что новая реплика
// обрывает озвучку, которая ещё ждала список голосов.
import { beforeEach, describe, expect, it, vi } from 'vitest';

interface FakeVoice {
  lang: string;
  name: string;
  localService: boolean;
}

let spoken: { text: string; voice: FakeVoice }[];
let listeners: (() => void)[];

function installSynth(voices: FakeVoice[], { lateVoices = false } = {}) {
  let available = lateVoices ? [] : voices;
  spoken = [];
  listeners = [];
  const synth = {
    getVoices: () => available,
    speak: (u: { text: string; voice: FakeVoice }) => spoken.push(u),
    cancel: vi.fn(),
    addEventListener: (_: string, fn: () => void) => listeners.push(fn),
    removeEventListener: () => {},
  };
  vi.stubGlobal('speechSynthesis', synth);
  vi.stubGlobal('window', { speechSynthesis: synth });
  vi.stubGlobal(
    'SpeechSynthesisUtterance',
    class {
      voice: FakeVoice | null = null;
      lang = '';
      constructor(public text: string) {}
    },
  );
  return {
    synth,
    deliverVoices: () => {
      available = voices;
      listeners.forEach((fn) => fn());
    },
  };
}

const irina = { lang: 'ru-RU', name: 'Irina', localService: true };
const zira = { lang: 'en-US', name: 'Zira', localService: true };

beforeEach(() => vi.resetModules());

describe('озвучка', () => {
  it('говорит русским голосом и тем же текстом', async () => {
    installSynth([zira, irina]);
    const { speak } = await import('./speech');
    const unavailable = vi.fn();
    await speak('Готово: «Купить хлеб».', unavailable);
    expect(spoken).toHaveLength(1);
    expect(spoken[0].text).toBe('Готово: «Купить хлеб».');
    expect(spoken[0].voice.name).toBe('Irina');
    expect(unavailable).not.toHaveBeenCalled();
  });

  it('выбирает самый естественный русский голос', async () => {
    const { pickRussian } = await import('./speech');
    const google = { lang: 'ru-RU', name: 'Google русский', localService: false };
    const svetlana = {
      lang: 'ru-RU',
      name: 'Microsoft Svetlana Online (Natural) - Russian (Russia)',
      localService: false,
    };
    const milena = { lang: 'ru_RU', name: 'Milena (Enhanced)', localService: true };
    const remote = { lang: 'ru-RU', name: 'Some voice', localService: false };
    const pick = (voices: FakeVoice[]) =>
      pickRussian(voices as unknown as SpeechSynthesisVoice[])?.name;
    expect(pick([irina, google, svetlana, zira])).toBe(svetlana.name);
    expect(pick([irina, google])).toBe('Google русский');
    expect(pick([irina, milena])).toBe('Milena (Enhanced)');
    expect(pick([remote, irina])).toBe('Irina');
    expect(pick([zira])).toBeUndefined();
  });

  it('нет русского голоса — не говорит и сообщает', async () => {
    installSynth([zira]);
    const { speak } = await import('./speech');
    const unavailable = vi.fn();
    await speak('Ответ', unavailable);
    expect(spoken).toHaveLength(0);
    expect(unavailable).toHaveBeenCalledOnce();
  });

  it('голоса приходят позже — ждёт voiceschanged', async () => {
    const { deliverVoices } = installSynth([irina], { lateVoices: true });
    const { speak } = await import('./speech');
    const done = speak('Ответ', () => {});
    deliverVoices();
    await done;
    expect(spoken).toHaveLength(1);
  });

  it('новая реплика во время ожидания голосов — старый ответ не озвучивается', async () => {
    const { deliverVoices } = installSynth([irina], { lateVoices: true });
    const { speak, stopSpeaking } = await import('./speech');
    const done = speak('Старый ответ', () => {});
    stopSpeaking();
    deliverVoices();
    await done;
    expect(spoken).toHaveLength(0);
  });
});

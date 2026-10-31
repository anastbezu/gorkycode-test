// Озвучка: какой голос выбирается, что бывает без русского голоса, и что новая реплика
// обрывает озвучку, которая ещё ждала список голосов.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { synthesize } = vi.hoisted(() => ({ synthesize: vi.fn() }));
vi.mock('../api/client', () => ({ synthesizeSpeech: synthesize }));

class FakeAudio {
  src = '';
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn();
  load = vi.fn();
  removeAttribute = vi.fn();
}
let audio: FakeAudio;

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

beforeEach(() => {
  vi.resetModules();
  synthesize.mockReset().mockRejectedValue(new Error('offline'));
  audio = new FakeAudio();
  vi.stubGlobal('Audio', class { constructor() { return audio; } });
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

afterEach(async () => {
  const { stopSpeaking } = await import('./speech');
  stopSpeaking();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('озвучка', () => {
  it('играет WAV сервера и освобождает URL после окончания', async () => {
    installSynth([irina]);
    vi.stubGlobal('window', {}); // Серверная озвучка не зависит от speechSynthesis.
    synthesize.mockResolvedValue(new Blob(['wav'], { type: 'audio/wav' }));
    const { speak } = await import('./speech');
    await speak('Ответ', vi.fn());
    expect(synthesize).toHaveBeenCalledWith('Ответ', expect.any(AbortSignal));
    expect(audio.play).toHaveBeenCalledOnce();
    expect(spoken).toHaveLength(0);
    audio.onended?.();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });

  it('остановка играющего ответа освобождает URL и не включает fallback', async () => {
    installSynth([irina]);
    synthesize.mockResolvedValue(new Blob(['wav']));
    const { speak, stopSpeaking } = await import('./speech');
    await speak('Ответ', vi.fn());
    const oldError = audio.onerror;
    stopSpeaking();
    oldError?.();
    await Promise.resolve();
    expect(audio.pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
    expect(spoken).toHaveLength(0);
  });

  it('запрет play и error дают ровно один браузерный fallback', async () => {
    installSynth([irina]);
    synthesize.mockResolvedValue(new Blob(['wav']));
    audio.play.mockImplementation(() => {
      audio.onerror?.();
      return Promise.reject(new Error('NotAllowedError'));
    });
    const { speak } = await import('./speech');
    await speak('Ответ', vi.fn());
    expect(spoken).toHaveLength(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });

  it('ошибка декодирования после начала звука включает fallback', async () => {
    installSynth([irina]);
    synthesize.mockResolvedValue(new Blob(['broken wav']));
    const { speak } = await import('./speech');
    await speak('Ответ', vi.fn());
    audio.onerror?.();
    await Promise.resolve();
    expect(spoken).toHaveLength(1);
  });

  it('таймаут отменяет HTTP, поздний WAV не играет', async () => {
    vi.useFakeTimers();
    installSynth([irina]);
    let resolve!: (blob: Blob) => void;
    synthesize.mockImplementation(() => new Promise<Blob>((r) => { resolve = r; }));
    const { speak } = await import('./speech');
    const done = speak('Ответ', vi.fn());
    await vi.advanceTimersByTimeAsync(16_000);
    expect(synthesize.mock.calls[0][1].aborted).toBe(true);
    expect(spoken).toHaveLength(1);
    resolve(new Blob(['late']));
    await done;
    expect(audio.play).not.toHaveBeenCalled();
  });

  it('новая реплика отменяет старый HTTP и подавляет позднюю ошибку', async () => {
    installSynth([irina]);
    let reject!: (error: Error) => void;
    synthesize.mockImplementationOnce(() => new Promise((_r, r) => { reject = r; }));
    synthesize.mockResolvedValueOnce(new Blob(['new']));
    const { speak } = await import('./speech');
    const old = speak('Старый ответ', vi.fn());
    await speak('Новый ответ', vi.fn());
    expect(synthesize.mock.calls[0][1].aborted).toBe(true);
    reject(new Error('late'));
    await old;
    expect(spoken).toHaveLength(0);
    expect(audio.play).toHaveBeenCalledOnce();
  });

  it('выключение отменяет запрос; выключенный звук не обращается к серверу', async () => {
    installSynth([irina]);
    let resolve!: (blob: Blob) => void;
    synthesize.mockImplementation(() => new Promise<Blob>((r) => { resolve = r; }));
    const { speak, setSpeechEnabled } = await import('./speech');
    const done = speak('Ответ', vi.fn());
    setSpeechEnabled(false);
    expect(synthesize.mock.calls[0][1].aborted).toBe(true);
    resolve(new Blob(['late']));
    await done;
    await speak('Следующий', vi.fn());
    expect(synthesize).toHaveBeenCalledOnce();
    expect(audio.play).not.toHaveBeenCalled();
    expect(spoken).toHaveLength(0);
    expect(localStorage.setItem).toHaveBeenCalledWith('gorky.speechEnabled', 'false');
  });

  it('сохранённое выключение действует после перезагрузки', async () => {
    installSynth([irina]);
    vi.stubGlobal('localStorage', { getItem: () => 'false' });
    const { speak } = await import('./speech');
    await speak('Ответ', vi.fn());
    expect(synthesize).not.toHaveBeenCalled();
  });

  it('длинный текст читает браузер целиком без HTTP', async () => {
    installSynth([irina]);
    const { speak } = await import('./speech');
    const text = 'я'.repeat(1001);
    await speak(text, vi.fn());
    expect(synthesize).not.toHaveBeenCalled();
    expect(spoken[0].text).toBe(text);
  });

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

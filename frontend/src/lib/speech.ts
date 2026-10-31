// Gemini через сервер; при сбое — русский голос браузера. reply передаётся дословно.
import { synthesizeSpeech } from '../api/client';
import { loadVoiceOutput } from './storage';

const VOICES_WAIT_MS = 1500;
const TTS_TIMEOUT_MS = 7_000;
let enabled = loadVoiceOutput();
let pending: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let player: HTMLAudioElement | null = null;
let objectUrl: string | null = null;

/** Применить единственную настройку voiceOutput; сохранением управляет SettingsModal/App. */
export function setVoiceOutputEnabled(value: boolean): void {
  enabled = value;
  if (!value) stopSpeaking();
}

function audioPlayer(): HTMLAudioElement {
  if (!player) player = new Audio();
  return player;
}

/** Вызвать из пользовательского жеста до ожидания LLM; тот же элемент играет ответ. */
export function prepareSpeech(): void {
  if (!enabled) return;
  try {
    const audio = audioPlayer();
    // Короткий PCM WAV с тишиной для разрешения воспроизведения в мобильном Safari.
    audio.src = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==';
    void audio.play().catch(() => {});
  } catch { /* Браузерный fallback остаётся доступен. */ }
}

function releaseAudio(): void {
  if (player) {
    player.onended = null;
    player.onerror = null;
    player.pause();
    player.removeAttribute('src');
    player.load();
  }
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
}

// Растёт при каждой остановке: озвучка, которая ждала список голосов, не начнётся после новой реплики
let generation = 0;

/** Список голосов в части браузеров приходит не сразу — ждём событие voiceschanged. */
function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  const now = speechSynthesis.getVoices();
  if (now.length > 0) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = () => {
      speechSynthesis.removeEventListener('voiceschanged', done);
      clearTimeout(timer);
      resolve(speechSynthesis.getVoices());
    };
    const timer = setTimeout(done, VOICES_WAIT_MS);
    speechSynthesis.addEventListener('voiceschanged', done);
  });
}

// Чем естественнее голос, тем выше: нейросетевые голоса Edge («… Online (Natural)»),
// сетевой «Google русский» в Chrome, улучшенные голоса Apple. Системные голоса вроде
// Microsoft Irina звучат роботом — только если лучше нет.
const NATURAL_VOICES = [/natural/i, /google/i, /premium|enhanced|siri/i];

function voiceRank(voice: SpeechSynthesisVoice): number {
  const index = NATURAL_VOICES.findIndex((pattern) => pattern.test(voice.name));
  if (index >= 0) return index;
  // Среди остальных локальный работает без сети и начинает говорить быстрее
  return voice.localService ? NATURAL_VOICES.length : NATURAL_VOICES.length + 1;
}

export function pickRussian(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const ru = voices.filter((v) => v.lang.toLowerCase().replace('_', '-').startsWith('ru'));
  if (ru.length === 0) return null;
  return ru.reduce((best, v) => (voiceRank(v) < voiceRank(best) ? v : best));
}

/** Остановить текущую озвучку: новая запись или реплика — ассистент не говорит поверх пользователя. */
export function stopSpeaking(): void {
  generation++;
  pending?.abort();
  pending = null;
  clearTimeout(timer);
  releaseAudio();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}

/**
 * Озвучить текст. Если озвучка недоступна (нет speechSynthesis или русского голоса) —
 * вызвать `onUnavailable` и ничего не говорить.
 */
async function browserSpeak(text: string, onUnavailable: () => void, mine: number): Promise<void> {
  if (mine !== generation || !enabled) return;
  if (!('speechSynthesis' in window)) {
    onUnavailable();
    return;
  }
  const voice = pickRussian(await loadVoices());
  if (mine !== generation) return;
  if (!voice) {
    onUnavailable();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang || 'ru-RU';
  try { speechSynthesis.speak(utterance); } catch { onUnavailable(); }
}

/** Новая реплика/запись/выключение звука отменяют запрос и все поздние callbacks. */
export async function speak(text: string, onUnavailable: () => void): Promise<void> {
  stopSpeaking();
  if (!enabled || !text.trim()) return;
  const mine = generation;
  const controller = new AbortController();
  pending = controller;
  let fellBack = false;
  const fallback = async () => {
    if (mine !== generation || fellBack || !enabled) return;
    fellBack = true;
    clearTimeout(timer);
    controller.abort();
    pending = null;
    releaseAudio();
    await browserSpeak(text, onUnavailable, mine);
  };
  // Длинный reply не обрезаем: браузер читает его целиком, сервер не вызываем.
  if (Array.from(text).length > 1000) return fallback();
  timer = setTimeout(() => { void fallback(); }, TTS_TIMEOUT_MS);
  try {
    const blob = await synthesizeSpeech(text, controller.signal);
    if (mine !== generation || fellBack || !enabled) return;
    const audio = audioPlayer();
    objectUrl = URL.createObjectURL(blob);
    audio.src = objectUrl;
    audio.onended = () => { if (mine === generation) releaseAudio(); };
    audio.onerror = () => { void fallback(); };
    await audio.play();
    if (mine === generation && !fellBack) {
      clearTimeout(timer);
      pending = null;
    }
  } catch {
    await fallback();
  }
}

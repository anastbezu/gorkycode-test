// Озвучка ответа голосом браузера (speechSynthesis), язык ru-RU. Серверного синтеза нет.
// reply озвучивается как есть — тот же текст, что в чате (api.md, «Правила»).
// Русского голоса может не быть (не проверено на iOS, Android) — тогда не озвучиваем.

const VOICES_WAIT_MS = 1500;

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
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}

/**
 * Озвучить текст. Если озвучка недоступна (нет speechSynthesis или русского голоса) —
 * вызвать `onUnavailable` и ничего не говорить.
 */
export async function speak(text: string, onUnavailable: () => void): Promise<void> {
  if (!('speechSynthesis' in window)) {
    onUnavailable();
    return;
  }
  stopSpeaking();
  const mine = generation;
  const voice = pickRussian(await loadVoices());
  if (mine !== generation) return;
  if (!voice) {
    onUnavailable();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang || 'ru-RU';
  speechSynthesis.speak(utterance);
}

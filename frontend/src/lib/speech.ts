// Озвучка ответа голосом браузера (speechSynthesis), язык ru-RU. Серверного синтеза нет.
// reply озвучивается как есть — тот же текст, что в чате (api.md, «Правила»).
// Русского голоса может не быть (не проверено на iOS, Android, Windows) — тогда не озвучиваем.

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

function pickRussian(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const ru = voices.filter((v) => v.lang.toLowerCase().replace('_', '-').startsWith('ru'));
  // Локальный голос работает без сети и начинает говорить быстрее
  return ru.find((v) => v.localService) ?? ru[0] ?? null;
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

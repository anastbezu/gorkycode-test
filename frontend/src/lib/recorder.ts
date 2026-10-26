// Запись голоса в браузере (MediaRecorder). Формат — какой браузер умеет: Chrome и Android
// пишут audio/webm, Safari и iOS — audio/mp4. Запись отправляется как есть, без перекодировки.
// Длиннее 30 секунд сервер не принимает (413), поэтому запись останавливается сама чуть раньше.

export const MAX_RECORDING_MS = 29_500;

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg'];

const EXTENSIONS: { [mime: string]: string } = {
  'audio/webm': 'webm',
  'audio/mp4': 'm4a',
  'audio/ogg': 'ogg',
  'audio/wav': 'wav',
};

/** Можно ли записывать голос: нужен MediaRecorder и микрофон, который браузер даёт только по HTTPS или на localhost. */
export function canRecord(): boolean {
  return typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

/** Понятное сообщение по ошибке getUserMedia — что сделать пользователю. */
export function microphoneErrorText(err: unknown): string {
  const name = (err as { name?: string } | null)?.name;
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Нет доступа к микрофону. Разрешите микрофон для этого сайта в настройках браузера (значок слева от адреса) и нажмите кнопку ещё раз.';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'Микрофон не найден. Подключите микрофон или напишите текстом.';
    case 'NotReadableError':
      return 'Микрофон занят другим приложением. Закройте его и попробуйте ещё раз.';
    default:
      return `Не удалось включить микрофон${name ? ` (${name})` : ''}. Попробуйте ещё раз или напишите текстом.`;
  }
}

export interface Recording {
  /** Остановить и получить файл записи. */
  stop: () => Promise<File>;
  /** Уровень громкости 0–1 — для индикатора «Идёт запись звука». */
  level: () => number;
}

/**
 * Начать запись. Бросает ошибку getUserMedia (нет доступа, нет микрофона) — её показывает вызывающий.
 * `onAutoStop` вызывается, когда запись остановилась сама на 30-й секунде.
 */
export async function startRecording(onAutoStop: () => void): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);

  // Уровень громкости для индикатора
  const audio = new AudioContext();
  const analyser = audio.createAnalyser();
  analyser.fftSize = 512;
  audio.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);

  const stopped = new Promise<File>((resolve) => {
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      void audio.close();
      // Тип файла — без параметров кодека: сервер определяет формат по Content-Type
      const type = (recorder.mimeType || mimeType || 'audio/webm').split(';')[0];
      const blob = new Blob(chunks, { type });
      resolve(new File([blob], `speech.${EXTENSIONS[type] ?? 'webm'}`, { type }));
    };
  });

  const timer = setTimeout(() => {
    if (recorder.state === 'recording') {
      recorder.stop();
      onAutoStop();
    }
  }, MAX_RECORDING_MS);

  recorder.start();

  return {
    stop: () => {
      clearTimeout(timer);
      if (recorder.state === 'recording') recorder.stop();
      return stopped;
    },
    level: () => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += ((s - 128) / 128) ** 2;
      return Math.min(1, Math.sqrt(sum / samples.length) * 4);
    },
  };
}

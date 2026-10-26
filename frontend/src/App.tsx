// Страница ассистента: чат слева, «Мои дела» справа (на телефоне — шторкой), настройки LLM.
// Состояние разговора и ленты — здесь; сеть — api/client.ts; показ дат — lib/dates.ts.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, fetchItems, onProfileReset, sendChat, transcribe } from './api/client';
import type { LLMConfig } from './api/types';
import { ResultView } from './components/ResultView';
import { SettingsModal } from './components/SettingsModal';
import { activeTodayCount, panelDayKeys, PANEL_DAYS, TasksPanel, type PanelState } from './components/TasksPanel';
import { RecordingIndicator } from './components/RecordingIndicator';
import { MicIcon, SendIcon, SettingsIcon } from './components/icons';
import { addDaysToKey, browserTimeZone, localMidnightIso } from './lib/dates';
import { canRecord, microphoneErrorText, startRecording, type Recording } from './lib/recorder';
import { speak, stopSpeaking } from './lib/speech';
import {
  loadChat,
  loadLLMConfig,
  saveChat,
  saveLLMConfig,
  type ChatMessage,
  type StoredChat,
} from './lib/storage';

const HINTS = ['Что у меня сегодня?', 'Напомни завтра в 10 позвонить Ивану'];

const UNKNOWN_RESULT_TEXT = 'Нет ответа от сервера. Не знаю, выполнено ли — проверьте «Мои дела».';
const STT_NO_ANSWER_TEXT = 'Не удалось распознать запись: нет ответа от сервера. Попробуйте ещё раз.';
const NO_VOICE_TEXT = 'Озвучка на этом устройстве недоступна: нет русского голоса. Ответы — только текстом.';
const NEW_PROFILE_TEXT =
  'Сохранённый профиль не принят сервером — начат новый профиль со стартовым набором записей.';

/** Плашка над полем ввода: ошибка с «Повторить» или сообщение без действия. */
type Banner = { text: string; retryText?: string } | null;

function newId(): string {
  return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : String(Date.now() + Math.random());
}

/** Панель «Мои дела»: один запрос на 7 дней; прежние записи видны, пока идёт перезапрос. */
function usePanel(tz: string) {
  const [state, setState] = useState<PanelState>({ status: 'loading', records: [] });
  // Номер последнего запроса: ответ более раннего, пришедший позже, не затирает свежие данные
  const latest = useRef(0);

  const load = useCallback(async () => {
    const request = ++latest.current;
    const [first] = panelDayKeys(tz);
    setState((prev) => ({ status: 'loading', records: prev.records }));
    try {
      const records = await fetchItems({
        from: localMidnightIso(first),
        to: localMidnightIso(addDaysToKey(first, PANEL_DAYS)),
        tz,
      });
      if (request === latest.current) setState({ status: 'ready', records });
    } catch (err) {
      if (request !== latest.current) return;
      const message = err instanceof ApiError && err.kind === 'rejected' ? err.detail : 'Нет ответа от сервера.';
      setState((prev) => ({ status: 'error', records: prev.records, message }));
    }
  }, [tz]);

  return { state, load };
}

export function App() {
  const tz = browserTimeZone();
  const [chat, setChat] = useState<StoredChat>(loadChat);
  const [pending, setPending] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [draft, setDraft] = useState('');
  const [llmConfig, setLlmConfig] = useState<LLMConfig>(loadLLMConfig);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedDay, setSelectedDay] = useState(0);
  const panel = usePanel(tz);
  const feedEnd = useRef<HTMLDivElement>(null);
  // Отправка идёт — вторая не начинается, даже если состояние ещё не перерисовалось
  const sending = useRef(false);
  // Текущий разговор для отправки: голосовая реплика уходит после await распознавания
  const conversationId = useRef(chat.conversationId);
  conversationId.current = chat.conversationId;
  const voiceAvailable = canRecord();
  const [recording, setRecording] = useState<Recording | null>(null);
  // «Озвучка недоступна» — одно сообщение за всё время страницы
  const noVoiceShown = useRef(false);

  useEffect(() => saveChat(chat), [chat]);
  useEffect(() => {
    void panel.load();
  }, [panel.load]);
  useEffect(
    () =>
      onProfileReset(() => {
        setBanner({ text: NEW_PROFILE_TEXT });
      }),
    [],
  );
  useEffect(() => {
    feedEnd.current?.scrollIntoView({ block: 'end' });
  }, [chat.messages.length, pending, banner]);

  const send = useCallback(
    async (text: string, isRetry = false) => {
      const trimmed = text.trim();
      if (!trimmed || sending.current) return;
      sending.current = true;
      stopSpeaking();
      setBanner(null);
      setPending(true);
      if (!isRetry) {
        setDraft('');
        setChat((c) => ({ ...c, messages: [...c.messages, { id: newId(), role: 'user', text: trimmed }] }));
      }
      try {
        const res = await sendChat({ text: trimmed, conversationId: conversationId.current, timezone: tz, llmConfig });
        const reply: ChatMessage = {
          id: newId(),
          role: 'assistant',
          reply: res.reply,
          result: res.result,
          awaiting: res.awaiting,
        };
        setChat((c) => ({ conversationId: res.conversation_id, messages: [...c.messages, reply] }));
        void panel.load();
        // Озвучивается каждый ответ — и на голос, и на набранный текст
        void speak(res.reply, () => {
          if (noVoiceShown.current) return;
          noVoiceShown.current = true;
          setBanner({ text: NO_VOICE_TEXT });
        });
      } catch (err) {
        if (err instanceof ApiError && err.kind === 'rejected') {
          setBanner({ text: `Сервер не принял запрос: ${err.detail}` });
        } else {
          // Сервер мог успеть выполнить — нельзя писать «ничего не сохранено»
          setBanner({ text: UNKNOWN_RESULT_TEXT, retryText: trimmed });
        }
      } finally {
        sending.current = false;
        setPending(false);
      }
    },
    [tz, llmConfig, panel],
  );

  /** Голос: первое нажатие — запись, второе (или 30-я секунда) — распознать и отправить как реплику. */
  const finishRecording = useCallback(
    async (rec: Recording) => {
      setRecording(null);
      const audio = await rec.stop();
      if (sending.current) return;
      sending.current = true;
      setPending(true); // ожидание распознавания — тем же «Ассистент думает…»: «Распознаю» в макете нет
      let text: string | null = null;
      try {
        text = await transcribe(audio);
      } catch (err) {
        // Ошибка распознавания — показать detail, в чат ничего не уходит
        setBanner({ text: err instanceof ApiError && err.kind === 'rejected' ? err.detail : STT_NO_ANSWER_TEXT });
      } finally {
        sending.current = false;
        setPending(false);
      }
      if (text) await send(text);
    },
    [send],
  );

  const toggleRecording = async () => {
    if (recording) {
      await finishRecording(recording);
      return;
    }
    if (sending.current) return;
    stopSpeaking();
    setBanner(null);
    try {
      let rec: Recording | null = null;
      rec = await startRecording(() => rec && void finishRecording(rec));
      setRecording(rec);
    } catch (err) {
      setBanner({ text: microphoneErrorText(err) });
    }
  };

  const retry = async (text: string) => {
    setBanner(null);
    await panel.load();
    await send(text, true);
  };

  const saveSettings = (cfg: LLMConfig) => {
    saveLLMConfig(cfg);
    setLlmConfig(cfg);
    setSettingsOpen(false);
  };

  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setSheetOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sheetOpen]);

  const todayCount = activeTodayCount(panel.state.records, tz);

  return (
    <div className="app">
      <header className="header">
        <h1 className="header__title">
          <span className="header__title-full">Голосовой ассистент</span>
          <span className="header__title-short">Ассистент</span>
        </h1>
        <button type="button" className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Настройки LLM">
          <SettingsIcon />
        </button>
      </header>

      <main className="chat">
        <div className="feed" aria-live="polite">
          {chat.messages.length === 0 && (
            <div className="feed__empty">
              <div className="bubble bubble--assistant">Я помогаю вести задачи, встречи и напоминания.</div>
              <div className="chips">
                {HINTS.map((hint) => (
                  <button key={hint} type="button" className="chip" onClick={() => void send(hint)} disabled={pending}>
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          )}

          {chat.messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="bubble bubble--user">
                {m.text}
              </div>
            ) : (
              <div key={m.id} className="assistant">
                <div className="bubble bubble--assistant">{m.reply}</div>
                <ResultView result={m.result} awaiting={m.awaiting} tz={tz} />
              </div>
            ),
          )}

          {pending && (
            <div className="thinking" role="status">
              <span className="thinking__dots" aria-hidden>
                <i />
                <i />
                <i />
              </span>
              Ассистент думает…
            </div>
          )}

          {banner && (
            <div className="banner" role="alert">
              <span>{banner.text}</span>
              {banner.retryText && (
                <button type="button" className="btn btn--glass" onClick={() => void retry(banner.retryText!)}>
                  Повторить
                </button>
              )}
            </div>
          )}
          <div ref={feedEnd} />
        </div>

        <button type="button" className="sheet-toggle" onClick={() => setSheetOpen(true)}>
          Мои дела · {todayCount}
        </button>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void send(draft);
          }}
        >
          {voiceAvailable && (
            <button
              type="button"
              className={`icon-btn mic${recording ? ' mic--on' : ''}`}
              onClick={() => void toggleRecording()}
              disabled={pending}
              aria-label={recording ? 'Остановить запись и отправить' : 'Начать говорить'}
              aria-pressed={!!recording}
            >
              <MicIcon />
            </button>
          )}
          {recording ? (
            <RecordingIndicator level={recording.level} />
          ) : (
            <input
              className="composer__input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={voiceAvailable ? 'Напишите или скажите, что нужно сделать' : 'Напишите, что нужно сделать'}
              aria-label="Сообщение"
              autoComplete="off"
            />
          )}
          <button
            type="submit"
            className="btn btn--primary composer__send"
            disabled={pending || !!recording || !draft.trim()}
          >
            <span className="composer__send-label">Отправить</span>
            <SendIcon />
          </button>
        </form>
      </main>

      <div className={`side${sheetOpen ? ' side--open' : ''}`}>
        <div className="side__backdrop" onClick={() => setSheetOpen(false)} />
        <TasksPanel
          state={panel.state}
          tz={tz}
          selectedDay={selectedDay}
          onSelectDay={setSelectedDay}
          onRetry={() => void panel.load()}
          onClose={() => setSheetOpen(false)}
        />
      </div>

      {settingsOpen && (
        <SettingsModal initial={llmConfig} onSave={saveSettings} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}

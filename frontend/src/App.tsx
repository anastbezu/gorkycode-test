// Страница ассистента: чат слева, «Мои дела» справа (на телефоне — шторкой), настройки LLM.
// Состояние разговора и ленты — здесь; сеть — api/client.ts; показ дат — lib/dates.ts.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  currentAccount,
  fetchItems,
  fetchMe,
  logout,
  onProfileReset,
  onSessionExpired,
  sendChat,
  setItemStatus,
  transcribe,
} from './api/client';
import type { Account, ActionResult, LLMConfig, Record } from './api/types';
import { AuthModal } from './components/AuthModal';
import { Background } from './components/Background';
import { CalendarView } from './components/CalendarView';
import { RecordDialog, type RecordDialogTarget } from './components/RecordDialog';
import { ResultView } from './components/ResultView';
import { SettingsModal } from './components/SettingsModal';
import { Toast, type ToastInfo } from './components/Toast';
import { activeTodayCount, panelDayKeys, PANEL_DAYS, TasksPanel, type PanelState } from './components/TasksPanel';
import { RecordingIndicator } from './components/RecordingIndicator';
import {
  AlertCircleIcon,
  BackIcon,
  CalendarIcon,
  MicIcon,
  MoonIcon,
  SendIcon,
  SettingsIcon,
  SunIcon,
  WifiOffIcon,
} from './components/icons';
import { addDaysToKey, browserTimeZone, dayKey, localMidnightIso } from './lib/dates';
import { canRecord, microphoneErrorText, startRecording, type Recording } from './lib/recorder';
import { speak, stopSpeaking } from './lib/speech';
import {
  applyTheme,
  loadChat,
  loadLLMConfig,
  loadTheme,
  saveChat,
  saveLLMConfig,
  saveTheme,
  type ChatMessage,
  type StoredChat,
  type ThemeChoice,
} from './lib/storage';

const HINTS = [
  'Что у меня сегодня?',
  'Напомни завтра в 10 позвонить Ивану',
  'Назначь встречу в пятницу в 15:00',
  'Что у меня на неделе?',
];
const STT_NO_ANSWER_TEXT = 'Не удалось распознать запись: нет ответа от сервера. Попробуйте ещё раз.';
const NO_VOICE_TEXT = 'Озвучка на этом устройстве недоступна: нет русского голоса. Ответы — только текстом.';
const NEW_PROFILE_TEXT =
  'Сохранённый профиль не принят сервером — начат новый профиль со стартовым набором записей.';

/** Плашка над полем ввода: ошибка с «Повторить» или сообщение без действия. */
type Banner = { text: string; retryText?: string } | null;

/** Экран — в адресе (`#calendar`): «Назад» браузера и телефона переключает экраны, ссылку можно открыть сразу. */
function useScreen(): ['chat' | 'calendar', (screen: 'chat' | 'calendar') => void] {
  const read = () => (window.location.hash === '#calendar' ? 'calendar' : 'chat');
  const [screen, setScreen] = useState<'chat' | 'calendar'>(read);
  useEffect(() => {
    const onPop = () => setScreen(read());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const go = (next: 'chat' | 'calendar') => {
    window.history.pushState(null, '', next === 'calendar' ? '#calendar' : window.location.pathname);
    setScreen(next);
  };
  return [screen, go];
}

function newId(): string {
  return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : String(Date.now() + Math.random());
}

/** Панель «Мои дела»: один запрос на 5 дней; прежние записи видны, пока идёт перезапрос. */
function usePanel(tz: string) {
  const [firstDayKey, setFirstDayKey] = useState(() => dayKey(new Date(), tz));
  const [selectedDay, setSelectedDay] = useState<number | 'undated'>(0);
  const [state, setState] = useState<PanelState>({ status: 'loading', records: [] });
  const [todayCount, setTodayCount] = useState(0);
  // Номер последнего запроса: ответ более раннего, пришедший позже, не затирает свежие данные
  const latest = useRef(0);
  const currentFirstDay = useRef(firstDayKey);
  currentFirstDay.current = firstDayKey;

  const load = useCallback(async (targetFirstDay?: string) => {
    const request = ++latest.current;
    const first = targetFirstDay ?? currentFirstDay.current;
    setState((prev) => ({ status: 'loading', records: prev.records }));
    try {
      const records = await fetchItems({
        from: localMidnightIso(first),
        to: localMidnightIso(addDaysToKey(first, PANEL_DAYS)),
        tz,
        includeUndated: true,
      });
      if (request === latest.current) {
        setState({ status: 'ready', records });
        const now = new Date();
        const today = dayKey(now, tz);
        const pageKeys = panelDayKeys(first, PANEL_DAYS);
        if (pageKeys.includes(today)) {
          setTodayCount(activeTodayCount(records, tz, now));
        }
      }
    } catch (err) {
      if (request !== latest.current) return;
      const message = err instanceof ApiError && err.kind === 'rejected' ? err.detail : 'Нет ответа от сервера.';
      setState((prev) => ({ status: 'error', records: prev.records, message }));
    }
  }, [tz]);

  const prevPage = useCallback(() => {
    const nextFirst = addDaysToKey(firstDayKey, -PANEL_DAYS);
    setFirstDayKey(nextFirst);
    setSelectedDay(0);
    void load(nextFirst);
  }, [firstDayKey, load]);

  const nextPage = useCallback(() => {
    const nextFirst = addDaysToKey(firstDayKey, PANEL_DAYS);
    setFirstDayKey(nextFirst);
    setSelectedDay(0);
    void load(nextFirst);
  }, [firstDayKey, load]);

  const resetToToday = useCallback(() => {
    const today = dayKey(new Date(), tz);
    setFirstDayKey(today);
    setSelectedDay(0);
    void load(today);
  }, [tz, load]);

  return {
    state,
    firstDayKey,
    selectedDay,
    setSelectedDay,
    todayCount,
    load,
    prevPage,
    nextPage,
    resetToToday,
  };
}

export function App() {
  const tz = browserTimeZone();
  const [account, setAccount] = useState<Account | null>(currentAccount);
  const [authOpen, setAuthOpen] = useState(false);
  const [dialogTarget, setDialogTarget] = useState<RecordDialogTarget | null>(null);
  const [calendarReloadKey, setCalendarReloadKey] = useState(0);
  const [toast, setToast] = useState<ToastInfo | null>(null);
  const [chat, setChat] = useState<StoredChat>(loadChat);
  const [pending, setPending] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [draft, setDraft] = useState('');
  const [llmConfig, setLlmConfig] = useState<LLMConfig>(loadLLMConfig);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice | null>(loadTheme);
  const [systemDark, setSystemDark] = useState<boolean>(() => {
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    return false;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const isDark = theme ? theme === 'dark' : systemDark;

  const toggleTheme = useCallback(() => {
    const next: ThemeChoice = isDark ? 'light' : 'dark';
    saveTheme(next);
    applyTheme(next);
    setTheme(next);
  }, [isDark]);

  const panel = usePanel(tz);
  const [screen, goTo] = useScreen();
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

  const openRecord = useCallback((record: Record) => {
    setDialogTarget({ mode: 'edit', record });
  }, []);

  const openCreate = useCallback((initialDay?: string) => {
    setDialogTarget({ mode: 'create', initialDay });
  }, []);

  const updateRecordInFeed = useCallback((updated: Record) => {
    setChat((prev) => {
      let changed = false;
      const nextMessages = prev.messages.map((m) => {
        if (m.role !== 'assistant' || !m.result?.records) return m;
        const records = m.result.records.map((r) => {
          if (r.id === updated.id) {
            changed = true;
            return { ...r, ...updated };
          }
          return r;
        });
        return changed ? { ...m, result: { ...m.result, records } } : m;
      });
      return changed ? { ...prev, messages: nextMessages } : prev;
    });
  }, []);

  const handleActionSuccess = useCallback(
    (res: ActionResult) => {
      void panel.load();
      setCalendarReloadKey((k) => k + 1);
      if (res.records && res.records.length > 0) {
        updateRecordInFeed(res.records[0]);
      }
    },
    [panel, updateRecordInFeed],
  );

  const handleDeleteRecord = useCallback(
    async (record: Record) => {
      try {
        await setItemStatus(record.id, 'cancelled', tz);
        void panel.load();
        setCalendarReloadKey((k) => k + 1);
        updateRecordInFeed({ ...record, status: 'cancelled' });
        setToast({ recordId: record.id, title: record.title });
      } catch (err) {
        if (err instanceof ApiError && err.kind === 'rejected') {
          setBanner({ text: err.detail });
        } else {
          setBanner({ text: 'Нет ответа от сервера, проверьте список.' });
        }
      }
    },
    [tz, panel, updateRecordInFeed],
  );

  const handleSetStatus = useCallback(
    async (record: Record, status: 'done' | 'active' | 'cancelled') => {
      try {
        const res = await setItemStatus(record.id, status, tz);
        void panel.load();
        setCalendarReloadKey((k) => k + 1);
        if (res.records && res.records.length > 0) {
          updateRecordInFeed(res.records[0]);
        } else {
          updateRecordInFeed({ ...record, status });
        }
      } catch (err) {
        if (err instanceof ApiError && err.kind === 'rejected') {
          setBanner({ text: err.detail });
        } else {
          setBanner({ text: 'Нет ответа от сервера, проверьте список.' });
        }
      }
    },
    [tz, panel, updateRecordInFeed],
  );

  const handleRestoreRecord = useCallback(
    async (recordId: string) => {
      setToast(null);
      try {
        const res = await setItemStatus(recordId, 'active', tz);
        void panel.load();
        setCalendarReloadKey((k) => k + 1);
        if (res.records && res.records.length > 0) {
          updateRecordInFeed(res.records[0]);
        }
      } catch (err) {
        if (err instanceof ApiError && err.kind === 'rejected') {
          setBanner({ text: err.detail });
        } else {
          setBanner({ text: 'Нет ответа от сервера, проверьте список.' });
        }
      }
    },
    [tz, panel, updateRecordInFeed],
  );

  const switchUser = useCallback(
    (next: Account | null) => {
      setAccount(next);
      setChat({ conversationId: null, messages: [] });
      stopSpeaking();
      if (recording) {
        void recording.stop();
        setRecording(null);
      }
      sending.current = false;
      setPending(false);
      void panel.resetToToday();
    },
    [recording, panel],
  );

  const handleLogout = async () => {
    await logout();
    switchUser(null);
  };

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
  useEffect(
    () =>
      onSessionExpired(() => {
        switchUser(null);
        setBanner({ text: 'Сессия входа истекла — вы снова гость. Войдите ещё раз.' });
      }),
    [switchUser],
  );
  useEffect(() => {
    if (!account) return;
    void fetchMe()
      .then((acc) => setAccount(acc))
      .catch(() => {});
  }, []);
  useEffect(() => {
    feedEnd.current?.scrollIntoView({ block: 'end' });
  }, [chat.messages.length, pending, banner]);

  const send = useCallback(
    async (text: string, isRetry = false, replaceErrorId?: string) => {
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
        setChat((c) => {
          const filtered = replaceErrorId ? c.messages.filter((m) => m.id !== replaceErrorId) : c.messages;
          return { conversationId: res.conversation_id, messages: [...filtered, reply] };
        });
        void panel.load();
        // Озвучивается каждый ответ — и на голос, и на набранный текст
        void speak(res.reply, () => {
          if (noVoiceShown.current) return;
          noVoiceShown.current = true;
          setBanner({ text: NO_VOICE_TEXT });
        });
      } catch (err) {
        if (err instanceof ApiError && err.kind === 'rejected') {
          const errorMsg: ChatMessage = {
            id: newId(),
            role: 'error',
            kind: 'rejected',
            userText: trimmed,
            detail: err.detail,
          };
          setChat((c) => {
            const filtered = replaceErrorId ? c.messages.filter((m) => m.id !== replaceErrorId) : c.messages;
            return { ...c, messages: [...filtered, errorMsg] };
          });
        } else {
          const errorMsg: ChatMessage = {
            id: newId(),
            role: 'error',
            kind: 'unknown',
            userText: trimmed,
          };
          setChat((c) => {
            const filtered = replaceErrorId ? c.messages.filter((m) => m.id !== replaceErrorId) : c.messages;
            return { ...c, messages: [...filtered, errorMsg] };
          });
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

  const todayCount = panel.todayCount;

  return (
    <div className="app">
      <Background />
      <header className="header">
        {screen === 'calendar' ? (
          <div className="header__left">
            <button type="button" className="icon-btn" onClick={() => goTo('chat')} aria-label="Назад в чат">
              <BackIcon />
            </button>
            <h1 className="header__title">Календарь</h1>
          </div>
        ) : (
          <h1 className="header__title">
            <span className="header__title-full">Голосовой ассистент</span>
            <span className="header__title-short">Ассистент</span>
          </h1>
        )}
        <div className="header__actions">
          <button
            type="button"
            className="icon-btn"
            onClick={toggleTheme}
            aria-label={isDark ? 'Включить светлую тему' : 'Включить тёмную тему'}
            title={isDark ? 'Включить светлую тему' : 'Включить тёмную тему'}
          >
            {isDark ? <SunIcon /> : <MoonIcon />}
          </button>
          {screen === 'chat' && (
            <button type="button" className="icon-btn" onClick={() => goTo('calendar')} aria-label="Календарь">
              <CalendarIcon />
            </button>
          )}
          <button type="button" className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Настройки LLM">
            <SettingsIcon />
          </button>
          {account ? (
            <div className="header__user">
              <span className="header__username" title={account.login}>
                {account.login}
              </span>
              <button
                type="button"
                className="btn btn--glass header__logout-btn"
                onClick={() => void handleLogout()}
              >
                Выйти
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn--glass header__login-btn"
              onClick={() => setAuthOpen(true)}
            >
              Войти
            </button>
          )}
        </div>
      </header>

      {screen === 'calendar' ? (
        <CalendarView
          key={account?.id ?? 'guest'}
          tz={tz}
          reloadKey={calendarReloadKey}
          onOpen={openRecord}
          onCreate={openCreate}
        />
      ) : (
      <>
      <main className="chat">
        <div className="feed" aria-live="polite">
          {chat.messages.length === 0 && (
            <div className="feed__empty">
              <div className="empty-chat__icon" aria-hidden="true">
                <MicIcon width={28} height={28} />
              </div>
              <h2 className="empty-chat__title">Чем помочь?</h2>
              <p className="empty-chat__subtitle">
                Скажите или напишите — я запишу задачу, встречу или напоминание.
              </p>
              <div className="empty-chat__chips">
                {HINTS.map((hint) => (
                  <button
                    key={hint}
                    type="button"
                    className="chip empty-chat__chip"
                    onClick={() => void send(hint)}
                    disabled={pending}
                  >
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          )}

          {chat.messages.map((m) => {
            if (m.role === 'user') {
              return (
                <div key={m.id} className="bubble bubble--user">
                  {m.text}
                </div>
              );
            }
            if (m.role === 'error') {
              return (
                <div key={m.id} className="assistant">
                  <div className="chat-error-card">
                    <div className="chat-error-card__body">
                      <div className="chat-error-card__icon">
                        {m.kind === 'unknown' ? (
                          <WifiOffIcon width={20} height={20} />
                        ) : (
                          <AlertCircleIcon width={20} height={20} />
                        )}
                      </div>
                      <div className="chat-error-card__content">
                        <div className="chat-error-card__title">
                          {m.kind === 'unknown'
                            ? 'Нет ответа от сервера. Не знаю, выполнено ли — проверьте «Мои дела».'
                            : 'Сервер не принял запрос. Ничего не изменилось.'}
                        </div>
                        {m.kind === 'rejected' && m.detail && (
                          <div className="chat-error-card__detail">{m.detail}</div>
                        )}
                      </div>
                    </div>
                    <div className="chat-error-card__actions">
                      {m.kind === 'unknown' ? (
                        <>
                          <button
                            type="button"
                            className="btn btn--primary-sm"
                            onClick={() => {
                              setSheetOpen(true);
                              void panel.load();
                            }}
                          >
                            Открыть «Мои дела»
                          </button>
                          <button
                            type="button"
                            className="btn btn--secondary-sm"
                            onClick={() => void send(m.userText, true, m.id)}
                          >
                            Отправить ещё раз
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--primary-sm"
                          onClick={() => void send(m.userText, true, m.id)}
                        >
                          Повторить
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            }
            return (
              <div key={m.id} className="assistant">
                <div className="bubble bubble--assistant">{m.reply}</div>
                <ResultView
                  result={m.result}
                  awaiting={m.awaiting}
                  tz={tz}
                  onOpen={openRecord}
                  onSetStatus={handleSetStatus}
                  onDelete={handleDeleteRecord}
                  onRestore={handleRestoreRecord}
                />
              </div>
            );
          })}

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
          firstDayKey={panel.firstDayKey}
          selectedDay={panel.selectedDay}
          onSelectDay={panel.setSelectedDay}
          onPrevPage={panel.prevPage}
          onNextPage={panel.nextPage}
          onRetry={() => void panel.load()}
          onClose={() => setSheetOpen(false)}
          onOpen={openRecord}
          onCreate={openCreate}
        />
      </div>
      </>
      )}

      <Toast toast={toast} onRestore={handleRestoreRecord} onDismiss={() => setToast(null)} />

      {dialogTarget && (
        <RecordDialog
          target={dialogTarget}
          tz={tz}
          onSuccess={handleActionSuccess}
          onDelete={(r) => void handleDeleteRecord(r)}
          onClose={() => setDialogTarget(null)}
        />
      )}

      {settingsOpen && (
        <SettingsModal initial={llmConfig} onSave={saveSettings} onClose={() => setSettingsOpen(false)} />
      )}

      {authOpen && (
        <AuthModal
          onSuccess={(acc) => switchUser(acc)}
          onClose={() => setAuthOpen(false)}
        />
      )}
    </div>
  );
}

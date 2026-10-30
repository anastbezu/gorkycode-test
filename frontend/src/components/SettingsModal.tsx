import { useEffect, useRef, useState } from 'react';
import type { LLMConfig } from '../api/types';
import {
  BellIcon,
  CalendarIcon,
  ChevronDownIcon,
  CloseIcon,
  CpuIcon,
  EyeIcon,
  EyeOffIcon,
  SearchIcon,
  ServerIcon,
  SlidersIcon,
  UserIcon,
} from './icons';
import { GoogleCalendarSection } from './GoogleCalendarSection';
import {
  findTimezone,
  formatTzLabel,
  POPULAR_TIMEZONE_IANAS,
  searchTimezones,
} from '../lib/timezones';
import {
  getNotificationStatus,
  requestNotificationPermission,
  type NotificationStatus,
} from '../lib/notifications';
import type { ReminderSettings, ThemeSetting } from '../lib/storage';

export type SettingsTab = 'general' | 'reminders' | 'model' | 'google';

interface Props {
  initialConfig: LLMConfig;
  initialTheme: ThemeSetting;
  initialTimezone: string | null;
  initialVoiceOutput: boolean;
  initialReminders: ReminderSettings;
  browserTz: string;
  isLoggedIn?: boolean;
  onSave: (data: {
    config: LLMConfig;
    theme: ThemeSetting;
    timezone: string | null;
    voiceOutput: boolean;
    reminders: ReminderSettings;
  }) => void;
  onClose: () => void;
}

export function isCustomConfig(cfg: LLMConfig): boolean {
  return Boolean(cfg.base_url || cfg.model || cfg.api_key);
}

export function sanitizeConfig(fields: { base_url: string; model: string; api_key: string }): LLMConfig {
  const clean = (v: string) => (v.trim() ? v.trim() : null);
  return {
    base_url: clean(fields.base_url),
    model: clean(fields.model),
    api_key: clean(fields.api_key),
  };
}

export function SettingsModal({
  initialConfig,
  initialTheme,
  initialTimezone,
  initialVoiceOutput,
  initialReminders,
  browserTz,
  isLoggedIn = false,
  onSave,
  onClose,
}: Props) {
  const [tab, setTab] = useState<SettingsTab>('general');

  // General tab state
  const [theme, setTheme] = useState<ThemeSetting>(initialTheme);
  const [selectedTz, setSelectedTz] = useState<string | null>(initialTimezone);
  const [voiceOutput, setVoiceOutput] = useState(initialVoiceOutput);

  // Timezone dropdown state
  const [tzOpen, setTzOpen] = useState(false);
  const [tzSearch, setTzSearch] = useState('');
  const tzDropdownRef = useRef<HTMLDivElement>(null);

  // Reminders tab state
  const [reminders, setReminders] = useState<ReminderSettings>(initialReminders);
  const [notifStatus, setNotifStatus] = useState<NotificationStatus>(getNotificationStatus);

  // Model tab state
  const [baseUrl, setBaseUrl] = useState(initialConfig.base_url ?? '');
  const [model, setModel] = useState(initialConfig.model ?? '');
  const [apiKey, setApiKey] = useState(initialConfig.api_key ?? '');
  const [showKey, setShowKey] = useState(false);

  const isCustom = isCustomConfig({
    base_url: baseUrl,
    model,
    api_key: apiKey,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Close timezone dropdown when clicking outside
  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (tzDropdownRef.current && !tzDropdownRef.current.contains(e.target as Node)) {
        setTzOpen(false);
      }
    };
    if (tzOpen) {
      document.addEventListener('mousedown', onClickOutside);
    }
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [tzOpen]);

  const handleRequestPermission = async () => {
    const next = await requestNotificationPermission();
    setNotifStatus(next);
    if (next === 'granted') {
      setReminders((prev) => ({ ...prev, enabled: true }));
    }
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      config: sanitizeConfig({ base_url: baseUrl, model, api_key: apiKey }),
      theme,
      timezone: selectedTz,
      voiceOutput,
      reminders,
    });
  };

  const currentTzLabel = selectedTz ? formatTzLabel(selectedTz) : `Как в браузере · ${formatTzLabel(browserTz)}`;
  const searchResults = tzSearch ? searchTimezones(tzSearch) : [];

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="modal__dialog modal__dialog--settings"
        onSubmit={handleSave}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        <div className="modal__head">
          <h2 id="settings-title" className="modal__title">
            Настройки
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <CloseIcon />
          </button>
        </div>

        {/* Табы для мобильных устройств */}
        <div className="settings-mobile-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'general'}
            className={`settings-mobile-tab ${tab === 'general' ? 'settings-mobile-tab--active' : ''}`}
            onClick={() => setTab('general')}
          >
            Общие
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'reminders'}
            className={`settings-mobile-tab ${tab === 'reminders' ? 'settings-mobile-tab--active' : ''}`}
            onClick={() => setTab('reminders')}
          >
            Напоминания
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'model'}
            className={`settings-mobile-tab ${tab === 'model' ? 'settings-mobile-tab--active' : ''}`}
            onClick={() => setTab('model')}
          >
            Модель
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'google'}
            className={`settings-mobile-tab ${tab === 'google' ? 'settings-mobile-tab--active' : ''}`}
            onClick={() => setTab('google')}
          >
            Google
          </button>
        </div>

        <div className="settings-layout">
          {/* Боковая навигация десктопа */}
          <aside className="settings-nav">
            <button
              type="button"
              className={`settings-nav__item ${tab === 'general' ? 'settings-nav__item--active' : ''}`}
              onClick={() => setTab('general')}
            >
              <SlidersIcon />
              <span>Общие</span>
            </button>
            <button
              type="button"
              className={`settings-nav__item ${tab === 'reminders' ? 'settings-nav__item--active' : ''}`}
              onClick={() => setTab('reminders')}
            >
              <BellIcon />
              <span>Напоминания</span>
            </button>
            <button
              type="button"
              className={`settings-nav__item ${tab === 'model' ? 'settings-nav__item--active' : ''}`}
              onClick={() => setTab('model')}
            >
              <CpuIcon />
              <span>Модель</span>
            </button>
            <button
              type="button"
              className={`settings-nav__item ${tab === 'google' ? 'settings-nav__item--active' : ''}`}
              onClick={() => setTab('google')}
            >
              <CalendarIcon />
              <span>Google</span>
            </button>
          </aside>

          {/* Содержимое вкладки */}
          <div className="settings-content">
            {tab === 'general' && (
              <div className="settings-tab-panel">
                <div className="settings-group">
                  <span className="settings-group__title">Тема</span>
                  <div className="segmented-control" role="group" aria-label="Выбор темы оформления">
                    <button
                      type="button"
                      className={`segmented-btn ${theme === 'system' ? 'segmented-btn--active' : ''}`}
                      onClick={() => setTheme('system')}
                    >
                      Как в системе
                    </button>
                    <button
                      type="button"
                      className={`segmented-btn ${theme === 'light' ? 'segmented-btn--active' : ''}`}
                      onClick={() => setTheme('light')}
                    >
                      Светлая
                    </button>
                    <button
                      type="button"
                      className={`segmented-btn ${theme === 'dark' ? 'segmented-btn--active' : ''}`}
                      onClick={() => setTheme('dark')}
                    >
                      Тёмная
                    </button>
                  </div>
                  <span className="settings-group__hint">
                    Луна в шапке переключает на светлую или тёмную. Вернуть «как в системе» — здесь.
                  </span>
                </div>

                <div className="settings-group">
                  <span className="settings-group__title">Часовой пояс</span>
                  <div className="tz-select" ref={tzDropdownRef}>
                    <button
                      type="button"
                      className="tz-select__trigger"
                      onClick={() => setTzOpen((prev) => !prev)}
                      aria-haspopup="listbox"
                      aria-expanded={tzOpen}
                    >
                      <span className="tz-select__text">{currentTzLabel}</span>
                      <ChevronDownIcon />
                    </button>

                    {tzOpen && (
                      <div className="tz-dropdown" role="listbox">
                        <div className="tz-dropdown__search">
                          <SearchIcon />
                          <input
                            type="text"
                            className="tz-dropdown__input"
                            value={tzSearch}
                            onChange={(e) => setTzSearch(e.target.value)}
                            placeholder="Поиск города..."
                            autoFocus
                          />
                        </div>

                        {tzSearch.trim() ? (
                          <div className="tz-dropdown__section">
                            <span className="tz-dropdown__header">НАЙДЕНО</span>
                            {searchResults.length > 0 ? (
                              searchResults.map((t) => (
                                <button
                                  key={t.iana}
                                  type="button"
                                  className={`tz-dropdown__item ${selectedTz === t.iana ? 'tz-dropdown__item--selected' : ''}`}
                                  onClick={() => {
                                    setSelectedTz(t.iana);
                                    setTzOpen(false);
                                    setTzSearch('');
                                  }}
                                >
                                  <span className="tz-dropdown__city">{t.city}</span>
                                  <span className="tz-dropdown__offset">{t.utcOffset}</span>
                                </button>
                              ))
                            ) : (
                              <div className="tz-dropdown__empty">Ничего не найдено</div>
                            )}
                          </div>
                        ) : (
                          <>
                            <button
                              type="button"
                              className={`tz-dropdown__item ${selectedTz === null ? 'tz-dropdown__item--selected' : ''}`}
                              onClick={() => {
                                setSelectedTz(null);
                                setTzOpen(false);
                              }}
                            >
                              <span className="tz-dropdown__city">Как в браузере</span>
                              <span className="tz-dropdown__offset">{formatTzLabel(browserTz)}</span>
                            </button>

                            <div className="tz-dropdown__section">
                              <span className="tz-dropdown__header">ЧАСТО</span>
                              {POPULAR_TIMEZONE_IANAS.map((iana) => {
                                const t = findTimezone(iana);
                                if (!t) return null;
                                return (
                                  <button
                                    key={t.iana}
                                    type="button"
                                    className={`tz-dropdown__item ${selectedTz === t.iana ? 'tz-dropdown__item--selected' : ''}`}
                                    onClick={() => {
                                      setSelectedTz(t.iana);
                                      setTzOpen(false);
                                    }}
                                  >
                                    <span className="tz-dropdown__city">{t.city}</span>
                                    <span className="tz-dropdown__offset">{t.utcOffset}</span>
                                  </button>
                                );
                              })}
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <span className="settings-group__hint">
                    Время в чате, «Моих делах» и календаре. По умолчанию — как в браузере.
                  </span>
                </div>

                <div className="settings-group">
                  <span className="settings-group__title">Звук</span>
                  <div className="toggle-row">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={voiceOutput}
                      className={`toggle-switch ${voiceOutput ? 'toggle-switch--on' : ''}`}
                      onClick={() => setVoiceOutput(!voiceOutput)}
                    >
                      <span className="toggle-switch__thumb" />
                    </button>
                    <div className="toggle-row__content">
                      <span className="toggle-row__label">Озвучивать ответы</span>
                      <span className="toggle-row__hint">
                        Ответы читаются вслух голосом браузера. Остановить один ответ можно кнопкой рядом с ним.
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {tab === 'reminders' && (
              <div className="settings-tab-panel">
                <span className="settings-panel-title">Напоминания в браузере</span>

                <div className="toggle-row">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={reminders.enabled}
                    className={`toggle-switch ${reminders.enabled ? 'toggle-switch--on' : ''}`}
                    onClick={() => {
                      if (!reminders.enabled && notifStatus === 'default') {
                        void handleRequestPermission();
                      } else {
                        setReminders((prev) => ({ ...prev, enabled: !prev.enabled }));
                      }
                    }}
                  >
                    <span className="toggle-switch__thumb" />
                  </button>
                  <span className="toggle-row__label">Напоминать о встречах и напоминаниях</span>
                </div>

                {reminders.enabled && notifStatus === 'default' && (
                  <div className="settings-notif-box">
                    <p className="settings-notif-box__text">Браузер ещё не разрешил уведомления.</p>
                    <button
                      type="button"
                      className="btn btn--primary"
                      onClick={() => void handleRequestPermission()}
                    >
                      Разрешить уведомления
                    </button>
                  </div>
                )}

                {reminders.enabled && notifStatus === 'denied' && (
                  <div className="settings-notif-alert">
                    Уведомления запрещены в браузере. Включите их в настройках сайта: значок слева от адреса → «Уведомления» → «Разрешить».
                  </div>
                )}

                {reminders.enabled && notifStatus === 'granted' && (
                  <div className="settings-group" style={{ marginTop: '16px' }}>
                    <span className="settings-group__title">Когда напомнить</span>
                    <div className="segmented-control" role="group" aria-label="Когда напомнить">
                      <button
                        type="button"
                        className={`segmented-btn ${reminders.leadMinutes === 0 ? 'segmented-btn--active' : ''}`}
                        onClick={() => setReminders((prev) => ({ ...prev, leadMinutes: 0 }))}
                      >
                        В момент
                      </button>
                      <button
                        type="button"
                        className={`segmented-btn ${reminders.leadMinutes === 5 ? 'segmented-btn--active' : ''}`}
                        onClick={() => setReminders((prev) => ({ ...prev, leadMinutes: 5 }))}
                      >
                        За 5 мин
                      </button>
                      <button
                        type="button"
                        className={`segmented-btn ${reminders.leadMinutes === 15 ? 'segmented-btn--active' : ''}`}
                        onClick={() => setReminders((prev) => ({ ...prev, leadMinutes: 15 }))}
                      >
                        За 15 мин
                      </button>
                      <button
                        type="button"
                        className={`segmented-btn ${reminders.leadMinutes === 30 ? 'segmented-btn--active' : ''}`}
                        onClick={() => setReminders((prev) => ({ ...prev, leadMinutes: 30 }))}
                      >
                        За 30 мин
                      </button>
                    </div>
                  </div>
                )}

                <span className="settings-group__hint" style={{ marginTop: '12px', display: 'block' }}>
                  Работает, пока вкладка открыта. Задачи без времени и записи на весь день не напоминаются.
                </span>
              </div>
            )}

            {tab === 'model' && (
              <div className="settings-tab-panel">
                <div className={`settings-status settings-status--${isCustom ? 'custom' : 'server'}`}>
                  {isCustom ? <UserIcon /> : <ServerIcon />}
                  <span>{isCustom ? 'Используются ваши настройки' : 'Используются настройки сервера'}</span>
                </div>

                <label className="field">
                  <span className="field__label">API Base URL</span>
                  <input
                    className="field__input"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://api.example.com/v1"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <span className="field__hint">OpenAI, Gemini или OpenRouter</span>
                </label>

                <label className="field">
                  <span className="field__label">Model Name</span>
                  <input
                    className="field__input"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="my-model-large"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </label>

                <label className="field">
                  <span className="field__label">API Key</span>
                  <div className="field__input-wrap">
                    <input
                      type={showKey ? 'text' : 'password'}
                      className="field__input field__input--key"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="••••••••••••••••"
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      className="icon-btn field__eye"
                      onClick={() => setShowKey(!showKey)}
                      aria-label={showKey ? 'Скрыть ключ' : 'Показать ключ'}
                    >
                      {showKey ? <EyeOffIcon /> : <EyeIcon />}
                    </button>
                  </div>
                  <span className="field__hint">
                    Хранится только в этом браузере. Если ключ или модель неверные, ассистент скажет об этом в чате.
                  </span>
                </label>
              </div>
            )}

            {tab === 'google' && (
              <div className="settings-tab-panel">
                {isLoggedIn ? (
                  <GoogleCalendarSection tz={selectedTz ?? browserTz} />
                ) : (
                  <div className="settings-empty-auth">
                    <p className="settings-empty-auth__text">
                      Google Календарь подключается только у учётки — войдите в аккаунт.
                    </p>
                  </div>
                )}
                <div className="settings-privacy">
                  <a
                    href="/privacy.html"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="settings-privacy-link"
                  >
                    Политика конфиденциальности
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="modal__foot">
          <button type="button" className="btn btn--glass" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" className="btn btn--primary">
            Сохранить
          </button>
        </div>
      </form>
    </div>
  );
}

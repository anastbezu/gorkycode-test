// Настройки LLM (фреймы «Настройки LLM · сервер» и «· свои»): три поля LLMConfig.
// Метка показывает сохранённое состояние (сервер / свои). Сброс очищает поля до сохранения.
import { useEffect, useState } from 'react';
import type { LLMConfig } from '../api/types';
import { CloseIcon, EyeIcon, EyeOffIcon, ServerIcon, UserIcon } from './icons';

interface Props {
  initial: LLMConfig;
  onSave: (cfg: LLMConfig) => void;
  onClose: () => void;
}

/** Проверка, настроена ли пользовательская модель (хотя бы одно поле заполнено). */
export function isCustomConfig(cfg: LLMConfig): boolean {
  return Boolean(cfg.base_url || cfg.model || cfg.api_key);
}

/** Очистка полей перед сохранением: пустые строки или пробелы превращаются в null. */
export function sanitizeConfig(fields: { base_url: string; model: string; api_key: string }): LLMConfig {
  const clean = (v: string) => (v.trim() ? v.trim() : null);
  return {
    base_url: clean(fields.base_url),
    model: clean(fields.model),
    api_key: clean(fields.api_key),
  };
}

export function SettingsModal({ initial, onSave, onClose }: Props) {
  const [baseUrl, setBaseUrl] = useState(initial.base_url ?? '');
  const [model, setModel] = useState(initial.model ?? '');
  const [apiKey, setApiKey] = useState(initial.api_key ?? '');
  const [showKey, setShowKey] = useState(false);

  // Метка показывает именно сохранённое состояние, а не введённое в форме
  const isCustom = isCustomConfig(initial);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(sanitizeConfig({ base_url: baseUrl, model, api_key: apiKey }));
  };

  const handleReset = () => {
    setBaseUrl('');
    setModel('');
    setApiKey('');
  };

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal__dialog" onSubmit={save} role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="modal__head">
          <h2 id="settings-title" className="modal__title">
            Настройки LLM
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <CloseIcon />
          </button>
        </div>

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
            placeholder="Как на сервере"
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
            placeholder="Как на сервере"
            autoComplete="off"
            spellCheck={false}
          />
        </label>

        <label className="field">
          <span className="field__label">API Key</span>
          <div className="field__input-wrap">
            <input
              className="field__input"
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Как на сервере"
              autoComplete="off"
              spellCheck={false}
            />
            <button
              type="button"
              className="field__eye-btn"
              onClick={() => setShowKey(!showKey)}
              aria-label={showKey ? 'Скрыть ключ' : 'Показать ключ'}
              title={showKey ? 'Скрыть ключ' : 'Показать ключ'}
            >
              {showKey ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
          <span className="field__hint">
            {isCustom
              ? 'Хранится только в этом браузере. Если ключ или модель неверные, ассистент скажет об этом в чате.'
              : 'Заполните поля, чтобы подключить свою модель.'}
          </span>
        </label>

        <div className="modal__actions modal__actions--settings">
          <button
            type="button"
            className="settings-reset"
            disabled={!isCustom}
            onClick={handleReset}
          >
            Сбросить к настройкам сервера
          </button>
          <div className="modal__actions-right">
            <button type="button" className="btn btn--glass" onClick={onClose}>
              Отмена
            </button>
            <button type="submit" className="btn btn--primary">
              Сохранить
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

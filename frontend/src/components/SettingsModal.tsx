// Настройки LLM (фрейм «Настройки LLM»): три поля LLMConfig. «Сохранить» — запомнить в браузере,
// «Отмена», крестик и Esc — закрыть без изменений. Ключ — поле типа password, никуда не выводится.
import { useEffect, useState } from 'react';
import type { LLMConfig } from '../api/types';
import { CloseIcon } from './icons';

interface Props {
  initial: LLMConfig;
  onSave: (cfg: LLMConfig) => void;
  onClose: () => void;
}

export function SettingsModal({ initial, onSave, onClose }: Props) {
  const [baseUrl, setBaseUrl] = useState(initial.base_url ?? '');
  const [model, setModel] = useState(initial.model ?? '');
  const [apiKey, setApiKey] = useState(initial.api_key ?? '');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = (v: string) => (v.trim() ? v.trim() : null);
    onSave({ base_url: clean(baseUrl), model: clean(model), api_key: clean(apiKey) });
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

        <label className="field">
          <span className="field__label">API Base URL</span>
          <input
            className="field__input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
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
            placeholder="gpt-4o-mini"
            autoComplete="off"
            spellCheck={false}
          />
        </label>

        <label className="field">
          <span className="field__label">API Key</span>
          <input
            className="field__input"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          <span className="field__hint">Хранится только в этом браузере</span>
        </label>

        <div className="modal__actions">
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

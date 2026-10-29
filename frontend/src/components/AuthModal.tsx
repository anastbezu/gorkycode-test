import { useEffect, useState } from 'react';
import { ApiError, login, register } from '../api/client';
import type { Account } from '../api/types';
import { CloseIcon } from './icons';

interface Props {
  onSuccess: (account: Account) => void;
  onClose: () => void;
}

export function AuthModal({ onSuccess, onClose }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [loginValue, setLoginValue] = useState('');
  const [passwordValue, setPasswordValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError(null);
    setLoading(true);
    try {
      const creds = { login: loginValue.trim(), password: passwordValue };
      const res = mode === 'login' ? await login(creds) : await register(creds);
      onSuccess(res.account);
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Не удалось выполнить запрос');
      }
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (next: 'login' | 'register') => {
    setMode(next);
    setError(null);
  };

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="modal__dialog"
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
      >
        <div className="modal__head">
          <h2 id="auth-title" className="modal__title">
            {mode === 'login' ? 'Вход в аккаунт' : 'Регистрация'}
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Закрыть" disabled={loading}>
            <CloseIcon />
          </button>
        </div>

        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={`auth-tab${mode === 'login' ? ' auth-tab--active' : ''}`}
            onClick={() => switchMode('login')}
            disabled={loading}
          >
            Вход
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={`auth-tab${mode === 'register' ? ' auth-tab--active' : ''}`}
            onClick={() => switchMode('register')}
            disabled={loading}
          >
            Регистрация
          </button>
        </div>

        <label className="field">
          <span className="field__label">Логин</span>
          <input
            className="field__input"
            value={loginValue}
            onChange={(e) => setLoginValue(e.target.value)}
            placeholder={mode === 'login' ? 'Логин' : 'ivan_dev'}
            autoComplete="username"
            autoFocus
            required
            disabled={loading}
            spellCheck={false}
          />
          {mode === 'register' && (
            <span className="field__hint">От 3 до 32 символов (латиница, цифры, _, ., -)</span>
          )}
        </label>

        <label className="field">
          <span className="field__label">Пароль</span>
          <input
            className="field__input"
            type="password"
            value={passwordValue}
            onChange={(e) => setPasswordValue(e.target.value)}
            placeholder="••••••••"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
            disabled={loading}
            spellCheck={false}
          />
          {mode === 'register' ? (
            <span className="field__hint">Не менее 8 символов</span>
          ) : (
            <span className="field__hint">Демо-учётка доступна в описании проекта</span>
          )}
        </label>

        {error && (
          <div className="field__error" role="alert">
            {error}
          </div>
        )}

        <div className="modal__actions">
          <button type="button" className="btn btn--glass" onClick={onClose} disabled={loading}>
            Отмена
          </button>
          <button type="submit" className="btn btn--primary" disabled={loading}>
            {loading ? 'Отправка…' : mode === 'login' ? 'Войти' : 'Зарегистрироваться'}
          </button>
        </div>
      </form>
    </div>
  );
}

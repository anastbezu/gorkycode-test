import { useEffect, useState } from 'react';
import {
  connectGoogleCalendar,
  disconnectGoogleCalendar,
  fetchGoogleCalendarStatus,
} from '../api/client';
import type { GoogleCalendarStatus } from '../api/types';
import { CalendarIcon, CheckIcon } from './icons';

interface Props {
  tz: string;
}

export function GoogleCalendarSection({ tz }: Props) {
  const [status, setStatus] = useState<GoogleCalendarStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const res = await fetchGoogleCalendarStatus();
      setStatus(res);
    } catch {
      // При сетевой ошибке оставляем текущее или null
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  const handleConnect = async () => {
    try {
      setConnecting(true);
      setActionError(null);
      const authUrl = await connectGoogleCalendar(tz);
      window.location.assign(authUrl);
    } catch (err: unknown) {
      setConnecting(false);
      const detail = err && typeof err === 'object' && 'detail' in err ? String(err.detail) : null;
      setActionError(detail || 'Не удалось открыть страницу Google. Попробуйте ещё раз.');
    }
  };

  const handleDisconnect = async () => {
    try {
      setDisconnecting(true);
      setActionError(null);
      await disconnectGoogleCalendar();
      await loadStatus();
    } catch (err: unknown) {
      const detail = err && typeof err === 'object' && 'detail' in err ? String(err.detail) : null;
      setActionError(detail || 'Не удалось отключить Google Календарь.');
    } finally {
      setDisconnecting(false);
    }
  };

  if (loading) {
    return (
      <div className="gcal-section">
        <h3 className="gcal-section__title">Google Календарь</h3>
        <div className="gcal-loading">Загрузка статуса…</div>
      </div>
    );
  }

  // Если сервер вернул 503 или недоступен
  if (status?.unavailable) {
    return (
      <div className="gcal-section">
        <h3 className="gcal-section__title">Google Календарь</h3>
        <div className="gcal-card">
          <div className="gcal-card__icon" aria-hidden>
            <CalendarIcon />
          </div>
          <div className="gcal-card__body">
            <div className="gcal-card__desc">
              Подключение пока недоступно на этом сервере.
            </div>
          </div>
        </div>
      </div>
    );
  }

  const isConnected = status?.state === 'connected';
  const isError = status?.state === 'error';
  const isNotConnected = !status || status.state === 'not_connected';

  return (
    <div className="gcal-section">
      <h3 className="gcal-section__title">Google Календарь</h3>

      {isNotConnected && (
        <div className="gcal-card">
          <div className="gcal-card__icon" aria-hidden>
            <CalendarIcon />
          </div>
          <div className="gcal-card__body">
            <div className="gcal-card__header">
              <span className="gcal-card__state-title">Не подключён</span>
            </div>
            <div className="gcal-card__desc">
              Записи будут появляться в отдельном календаре «Голосовой ассистент». Ассистент не видит ваши другие календари.
            </div>
            {actionError && <div className="gcal-card__error-msg">{actionError}</div>}
            <div className="gcal-card__actions">
              <button
                type="button"
                className="btn btn--primary gcal-btn"
                disabled={connecting}
                onClick={handleConnect}
              >
                {connecting ? 'Открываю Google…' : 'Подключить'}
              </button>
            </div>
          </div>
        </div>
      )}

      {isConnected && (
        <div className="gcal-card">
          <div className="gcal-card__icon" aria-hidden>
            <CalendarIcon />
          </div>
          <div className="gcal-card__body">
            <div className="gcal-card__header">
              {status.email ? (
                <span className="gcal-card__email" title={status.email}>
                  {status.email}
                </span>
              ) : (
                <span className="gcal-card__state-title">Подключён</span>
              )}
              <span className="tag tag--connected">
                <CheckIcon width={12} height={12} />
                <span>Подключён</span>
              </span>
            </div>
            {status.pending > 0 && (
              <div className="gcal-card__pending">
                Ждут отправки в Google: {status.pending}
              </div>
            )}
            {actionError && <div className="gcal-card__error-msg">{actionError}</div>}
            <div className="gcal-card__actions">
              <button
                type="button"
                className="btn btn--glass gcal-btn"
                disabled={connecting || disconnecting}
                onClick={handleConnect}
              >
                {connecting ? 'Открываю Google…' : 'Переподключить'}
              </button>
              <button
                type="button"
                className="btn btn--glass gcal-btn gcal-btn--disconnect"
                disabled={connecting || disconnecting}
                onClick={handleDisconnect}
              >
                {disconnecting ? 'Отключаю…' : 'Отключить'}
              </button>
            </div>
          </div>
        </div>
      )}

      {isError && (
        <div className="gcal-card">
          <div className="gcal-card__icon gcal-card__icon--error" aria-hidden>
            <CalendarIcon />
          </div>
          <div className="gcal-card__body">
            <div className="gcal-card__header">
              {status.email && (
                <span className="gcal-card__email" title={status.email}>
                  {status.email}
                </span>
              )}
              <span className="tag tag--error">Ошибка</span>
            </div>
            <div className="gcal-card__desc gcal-card__desc--error">
              {status.error || 'Доступ к Google Календарю отозван — переподключите.'}
            </div>
            {status.pending > 0 && (
              <div className="gcal-card__pending">
                Ждут отправки в Google: {status.pending}
              </div>
            )}
            {actionError && <div className="gcal-card__error-msg">{actionError}</div>}
            <div className="gcal-card__actions">
              <button
                type="button"
                className="btn btn--glass gcal-btn"
                disabled={connecting || disconnecting}
                onClick={handleConnect}
              >
                {connecting ? 'Открываю Google…' : 'Переподключить'}
              </button>
              <button
                type="button"
                className="btn btn--glass gcal-btn gcal-btn--disconnect"
                disabled={connecting || disconnecting}
                onClick={handleDisconnect}
              >
                {disconnecting ? 'Отключаю…' : 'Отключить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

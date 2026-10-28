import { useEffect } from 'react';

export interface ToastInfo {
  recordId: string;
  title: string;
}

interface Props {
  toast: ToastInfo | null;
  onRestore: (recordId: string) => void;
  onDismiss: () => void;
}

export function Toast({ toast, onRestore, onDismiss }: Props) {
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => {
      onDismiss();
    }, 8000);
    return () => clearTimeout(timer);
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div className="toast" role="status" aria-live="polite">
      <span className="toast__text">Удалено: «{toast.title}»</span>
      <button
        type="button"
        className="btn btn--glass toast__action"
        onClick={() => onRestore(toast.recordId)}
      >
        Вернуть
      </button>
    </div>
  );
}

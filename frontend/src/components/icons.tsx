// Иконки компонента «Кнопка-иконка» из макета: линейные, 24×24, обводка 2 px.
const common = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
};

export function SettingsIcon() {
  return (
    <svg {...common}>
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
      <circle cx="9" cy="7" r="2" fill="var(--surface)" />
      <circle cx="15" cy="12" r="2" fill="var(--surface)" />
      <circle cx="9" cy="17" r="2" fill="var(--surface)" />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg {...common}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg {...common}>
      <path d="M21 3 10 14" />
      <path d="M21 3 14.5 21l-4.5-7-7-4.5z" />
    </svg>
  );
}

export function MicIcon() {
  return (
    <svg {...common}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
      <line x1="12" y1="18" x2="12" y2="22" />
    </svg>
  );
}

export function CalendarIcon() {
  return (
    <svg {...common}>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <line x1="8" y1="3" x2="8" y2="7" />
      <line x1="16" y1="3" x2="16" y2="7" />
      <line x1="3" y1="11" x2="21" y2="11" />
      <line x1="8" y1="15" x2="11" y2="15" />
    </svg>
  );
}

export function BackIcon() {
  return (
    <svg {...common}>
      <line x1="19" y1="12" x2="5" y2="12" />
      <path d="M11 6 5 12l6 6" />
    </svg>
  );
}

export function PrevIcon() {
  return (
    <svg {...common}>
      <path d="M15 6 9 12l6 6" />
    </svg>
  );
}

export function NextIcon() {
  return (
    <svg {...common}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

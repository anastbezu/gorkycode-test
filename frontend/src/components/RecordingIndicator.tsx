// «Идёт запись звука» с индикатором уровня — фрейм «Состояния», блок «Микрофон».
// Высоты столбиков меняются напрямую через DOM в своём цикле кадров, без перерисовки всей страницы.
import { useEffect, useRef } from 'react';

const BARS = 5;
// Разная чувствительность столбиков, чтобы индикатор «дышал», а не прыгал одним блоком
const WEIGHTS = [0.55, 0.85, 1, 0.75, 0.6];

export function RecordingIndicator({ level }: { level: () => number }) {
  const bars = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const value = level();
      bars.current.forEach((bar, i) => {
        if (bar) bar.style.height = `${20 + Math.min(1, value * WEIGHTS[i]) * 80}%`;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [level]);

  return (
    <div className="recording" role="status">
      <span className="recording__label">Идёт запись звука</span>
      <span className="recording__bars" aria-hidden>
        {Array.from({ length: BARS }, (_, i) => (
          <span key={i} ref={(el) => void (bars.current[i] = el)} />
        ))}
      </span>
    </div>
  );
}

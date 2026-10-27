// Пятна на фоне (фиолетовое, лаймовое, оранжевое — как в макете), которые двигаются:
// - всегда медленно плывут по кругу — CSS-анимация;
// - на компьютере (есть мышь) ещё и тянутся за курсором с задержкой, каждое на своё расстояние.
// Двигается только transform отдельных слоёв — это делает видеокарта, без перерисовки страницы.
// «Уменьшить движение» в системе — пятна стоят (styles.css).
import { useEffect, useRef } from 'react';

// Насколько пиксель смещения курсора от центра сдвигает пятно: разная глубина у каждого
const DEPTH = [0.12, -0.08, 0.06];
// Доля оставшегося пути за кадр: меньше — плавнее и с большей задержкой
const EASING = 0.06;

export function Background() {
  const layers = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!finePointer || reducedMotion) return;

    const target = { x: 0, y: 0 };
    const current = { x: 0, y: 0 };
    let frame = 0;

    // Цикл кадров работает, только пока пятна догоняют курсор, потом останавливается
    const step = () => {
      current.x += (target.x - current.x) * EASING;
      current.y += (target.y - current.y) * EASING;
      layers.current.forEach((layer, i) => {
        if (layer) layer.style.transform = `translate3d(${current.x * DEPTH[i]}px, ${current.y * DEPTH[i]}px, 0)`;
      });
      const settled = Math.abs(target.x - current.x) < 0.5 && Math.abs(target.y - current.y) < 0.5;
      frame = settled ? 0 : requestAnimationFrame(step);
    };

    const onMove = (e: PointerEvent) => {
      target.x = e.clientX - window.innerWidth / 2;
      target.y = e.clientY - window.innerHeight / 2;
      if (!frame) frame = requestAnimationFrame(step);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="bg" aria-hidden>
      {[1, 2, 3].map((n, i) => (
        // Внешний слой — смещение за мышью, внутренний — плавание по кругу: два transform не мешают друг другу
        <div key={n} className="bg__layer" ref={(el) => void (layers.current[i] = el)}>
          <div className={`bg__blob bg__blob--${n}`} />
        </div>
      ))}
    </div>
  );
}

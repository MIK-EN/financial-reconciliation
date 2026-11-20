import { useMemo, useRef, useState } from "react";

import {
  ArrowRight,
  Check,
  WarningCircle,
} from "./Icons";

type CtaOrigin = "nav" | "hero" | "final";

interface LandingProps {
  busy: boolean;
  error: string | null;
  onStart: () => void;
  onLogin: () => void;
}

const DEMO_TEXT =
  "The function returns a list of matching items. If you omit the optional limit parameter, it returns all available results.";
const DEMO_INITIAL = ["omit", "optional"];
const DIFFICULT_SHARE = 0.2;

function Demo() {
  const parts = useMemo(() => DEMO_TEXT.match(/[A-Za-z]+|[^A-Za-z]+/g) ?? [], []);
  const total = useMemo(
    () => new Set(parts.filter((part) => /^[A-Za-z]+$/.test(part)).map((w) => w.toLowerCase()))
      .size,
    [parts],
  );
  const [marked, setMarked] = useState<Set<string>>(() => new Set(DEMO_INITIAL));

  function toggle(key: string) {
    const next = new Set(marked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setMarked(next);
  }

  const share = marked.size / total;
  const difficult = share > DIFFICULT_SHARE;

  return (
    <figure className="demo-frame" aria-labelledby="demo-caption">
      <div className="demo">
        <div className="demo-head">
          <p className="caption-3 muted">Пример</p>
          <p id="demo-caption" className="caption-1 muted">
            Нажмите на слово, которое не знаете
          </p>
        </div>
        <p className="demo-text" lang="en">
          {parts.map((part, index) => {
            if (!/^[A-Za-z]+$/.test(part)) return <span key={index}>{part}</span>;
            const key = part.toLowerCase();
            return (
              <button
                key={index}
                type="button"
                className="word"
                aria-pressed={marked.has(key)}
                onClick={() => toggle(key)}
              >
                {part}
              </button>
            );
          })}
        </p>
        <div className="meter" aria-live="polite">
          <div className="meter-row">
            <p className="title-4">
              Незнакомых слов: {marked.size} из {total}
            </p>
            <p className="title-4 muted">{Math.round(share * 100)}%</p>
          </div>
          <div className="meter-track" aria-hidden="true">
            <div
              className="meter-fill"
              style={{
                transform: `scaleX(${Math.min(share, 1)})`,
                background: difficult ? "#b4541a" : "#111111",
              }}
            />
            <div className="meter-limit" />
          </div>
          <p className="body-6 muted">
            {difficult
              ? "Больше 20%: текст трудный, следующий будет проще."
              : "Не больше 20%: текст доступен, следующий будет сложнее."}
          </p>
        </div>
      </div>
    </figure>
  );
}

export function Landing({ busy, error, onStart, onLogin }: LandingProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [origin, setOrigin] = useState<CtaOrigin>("hero");

  function start(from: CtaOrigin) {
    setOrigin(from);
    onStart();
  }

  const startLabel = busy ? "Начинаем…" : "Подобрать сложность";
  const errorAlert = (where: CtaOrigin) =>
    error !== null && origin === where ? (
      <p className="message message-error body-6" role="alert">
        <WarningCircle />
        {error}
      </p>
    ) : null;

  return (
    <div ref={rootRef}>
      <a className="skip-link btn btn-primary btn-sm button-sm" href="#main">
        Перейти к содержанию
      </a>

      <header className="nav-wrap">
        <nav className="nav" aria-label="Основная навигация">
          <a className="brand title-4" href="#top">
            <span className="brand-mark" aria-hidden="true">
              En
            </span>
            English for Developers
          </a>
          <button
            className="btn btn-ghost btn-sm button-sm"
            type="button"
            disabled={busy}
            onClick={onLogin}
          >
            Войти
          </button>
          <button
            className="nav-cta btn btn-primary btn-sm button-sm"
            type="button"
            disabled={busy}
            onClick={() => start("nav")}
          >
            {startLabel}
          </button>
        </nav>
      </header>
      {errorAlert("nav") === null ? null : (
        <div className="container" style={{ paddingTop: 16 }}>
          {errorAlert("nav")}
        </div>
      )}

      <main id="main" tabIndex={-1}>
        <section id="top" className="section" aria-labelledby="hero-title">
          <div className="container hero">
            <div className="hero-copy">
              <p className="caption-3 muted">Английский для разработчиков A2–B1</p>
              <h1 id="hero-title" className="heading-1 hero-title">
                С каких текстов
                <br /> начинать читать
                <br /> документацию?
              </h1>
              <p className="body-7 muted">
                Прочитайте от двух до четырёх коротких фрагментов в стиле настоящей документации
                и отметьте незнакомые слова. Мы предложим стартовую сложность, а выбрать другую
                можно в любой момент.
              </p>
              <div className="hero-cta">
                <button
                  className="btn btn-primary button-lg"
                  type="button"
                  disabled={busy}
                  onClick={() => start("hero")}
                >
                  {startLabel}
                  <ArrowRight />
                </button>
                {errorAlert("hero")}
                <ul className="proof caption-1 muted">
                  <li>
                    <Check size={16} />
                    Регистрация не нужна
                  </li>
                  <li>
                    <Check size={16} />
                    От двух до четырёх текстов
                  </li>
                  <li>
                    <Check size={16} />
                    Результат можно изменить
                  </li>
                </ul>
              </div>
            </div>
            <Demo />
          </div>
        </section>
      </main>
    </div>
  );
}

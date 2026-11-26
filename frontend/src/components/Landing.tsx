import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import {
  ArrowRight,
  Check,
  Clock,
  Folder,
  LockOpen,
  PaperPlaneTilt,
  Plus,
  Sliders,
  WarningCircle,
} from "./Icons";

type CtaOrigin = "nav" | "hero" | "final";

interface LandingProps {
  busy: boolean;
  error: string | null;
  signedIn: boolean;
  onStart: () => void;
  onLogin: () => void;
}

const DEMO_TEXT =
  "The function returns a list of matching items. If you omit the optional limit parameter, it returns all available results.";
const DEMO_INITIAL = ["omit", "optional"];
const DIFFICULT_SHARE = 0.2;

const TAGLINE =
  "Не нужно знать весь английский. Нужно понимать слова, из которых состоит документация.";

const LEVELS = [
  { name: "Основы", sample: "Open the file. Read the text. Save your changes." },
  {
    name: "Базовая документация",
    sample: "Before you install the application, check the system requirements.",
  },
  {
    name: "Уверенное чтение",
    sample: "If you omit the optional limit parameter, it returns all available results.",
  },
  {
    name: "Сложные тексты",
    sample:
      "Repeated requests may cause duplicate operations, so this behavior should only be enabled when the server can safely handle them.",
  },
];

const FAQ = [
  {
    q: "Это тест уровня английского?",
    a: "Нет. Мы смотрим только на слова, которые вы отметили как незнакомые. Результат подсказывает, с какой сложности начать, и не заменяет оценку по CEFR.",
  },
  {
    q: "Сколько текстов придётся прочитать?",
    a: "От двух до четырёх, каждый на несколько строк. Если первый текст трудный, мы покажем ещё один, проще, и на этом подбор закончится.",
  },
  {
    q: "Какое слово считать незнакомым?",
    a: "Любое, значение которого вам непонятно именно в этом предложении. Если непонятно выражение целиком, отметьте все его слова.",
  },
  {
    q: "Как вы решаете, что текст трудный?",
    a: "Если незнакомых слов больше 20% от учитываемых, текст считается трудным. Повторы, числа, знаки и имена функций не учитываются.",
  },
  {
    q: "Нужна ли регистрация?",
    a: "Нет. Подбор проходится без аккаунта. Создать аккаунт можно после результата, чтобы открыть его снова после нового входа.",
  },
  {
    q: "Что если я не согласен с рекомендацией?",
    a: "Выберите другую сложность на экране результата. Мы сохраним ваш выбор отдельно от рекомендации.",
  },
  {
    q: "Можно восстановить пароль?",
    a: "Пока нет. В первой версии нет почты и восстановления доступа, поэтому сохраните пароль в менеджере паролей.",
  },
  {
    q: "Когда появятся занятия?",
    a: "В разделе «Тренажёр» уже доступны короткие задания по рабочим ситуациям: выберите ответ и прочитайте объяснение. Также можно пройти подбор стартовой сложности для чтения документации.",
  },
];

function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/**
 * Scroll reveals, once per element and in reading order.
 * Sections rise into place as they enter the viewport. Tagline words switch from the muted
 * tone to full colour one by one as they cross a line at 65% of the viewport height.
 * Anything above a revealed element is revealed too, so jumping to an anchor never leaves
 * earlier content hidden.
 */
function useScrollReveal(
  root: RefObject<HTMLElement | null>,
  tagline: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const sections = Array.from(root.current?.querySelectorAll<HTMLElement>(".reveal") ?? []);
    const words = Array.from(
      tagline.current?.querySelectorAll<HTMLElement>(".tagline-word") ?? [],
    );
    if (prefersReducedMotion() || typeof IntersectionObserver === "undefined") {
      sections.forEach((section) => section.classList.add("is-visible"));
      words.forEach((word) => word.classList.add("is-on"));
      return;
    }

    let wordsOn = 0;
    function showWordsThrough(last: number) {
      let step = 0;
      for (; wordsOn <= last && wordsOn < words.length; wordsOn += 1) {
        const word = words[wordsOn];
        if (word === undefined) continue;
        word.style.transitionDelay = `${step * 60}ms`;
        word.classList.add("is-on");
        step += 1;
      }
    }

    let sectionsOn = 0;
    const sectionObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = sections.indexOf(entry.target as HTMLElement);
          for (; sectionsOn <= index; sectionsOn += 1) {
            sections[sectionsOn]?.classList.add("is-visible");
          }
          const taglineEl = tagline.current;
          if (
            taglineEl !== null &&
            taglineEl.compareDocumentPosition(entry.target) & Node.DOCUMENT_POSITION_FOLLOWING
          ) {
            showWordsThrough(words.length - 1);
          }
        }
      },
      { rootMargin: "0px 0px -10% 0px" },
    );
    const wordObserver = new IntersectionObserver(
      (entries) => {
        const crossed = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => words.indexOf(entry.target as HTMLElement));
        if (crossed.length > 0) showWordsThrough(Math.max(...crossed));
      },
      { rootMargin: "0px 0px -35% 0px", threshold: 1 },
    );
    sections.forEach((section) => sectionObserver.observe(section));
    words.forEach((word) => wordObserver.observe(word));
    return () => {
      sectionObserver.disconnect();
      wordObserver.disconnect();
    };
  }, [root, tagline]);
}

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

export function Landing({ busy, error, signedIn, onStart, onLogin }: LandingProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const taglineRef = useRef<HTMLParagraphElement>(null);
  const [origin, setOrigin] = useState<CtaOrigin>("hero");
  useScrollReveal(rootRef, taglineRef);

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
          <div className="nav-links title-4">
            <a className="nav-link" href="/trainer">Тренажёр</a>
            <a className="nav-link" href="#how">
              Как это работает
            </a>
            <a className="nav-link" href="#levels">
              Уровни
            </a>
            <a className="nav-link" href="#faq">
              Вопросы
            </a>
          </div>
          {signedIn ? null : (
            <button
              className="btn btn-ghost btn-sm button-sm btn-telegram nav-login"
              aria-label="Войти через Telegram"
              type="button"
              disabled={busy}
              onClick={onLogin}
            >
              <PaperPlaneTilt />
              <span>
                Войти<span className="nav-login-suffix"> через Telegram</span>
              </span>
            </button>
          )}
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
                <a className="title-3" href="/trainer">Открыть тренажёр →</a>
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

        <section className="section section-muted" aria-labelledby="problem-title">
          <div className="container reveal">
            <div className="section-head">
              <p className="caption-3 muted">Почему не обычный тест</p>
              <h2 id="problem-title" className="heading-2">
                Тест уровня проверяет грамматику. Документация проверяет другое
              </h2>
            </div>
            <div className="grid-2">
              <article className="tile">
                <p className="caption-3 muted">Обычный тест</p>
                <h3 className="title-1">Времена глаголов, артикли, эссе о хобби</h3>
                <p className="body-3 muted">
                  Буква уровня говорит мало о том, поймёте ли вы раздел про установку или
                  описание параметра функции.
                </p>
              </article>
              <article className="tile tile-dark">
                <p className="caption-3">Здесь</p>
                <h3 className="title-1">Тексты о файлах, установке, параметрах и запросах</h3>
                <p className="body-3">
                  Вы отмечаете слова, которые не поняли в контексте. Рекомендация опирается на
                  то, что вы прочитали, а не на абстрактные задания.
                </p>
              </article>
            </div>
          </div>
        </section>

        <section className="section" aria-labelledby="benefits-title">
          <div className="container reveal">
            <div className="section-head">
              <h2 id="benefits-title" className="heading-2">
                Что вы получаете за несколько минут
              </h2>
            </div>
            <div className="grid-4">
              <article className="tile tile-sm">
                <Folder size={28} strokeWidth={1.5} />
                <h3 className="title-2">Тексты из рабочего контекста</h3>
                <p className="body-6 muted">
                  Установка, параметры функций, повторные запросы. Слова, которые вы встретите
                  завтра в README.
                </p>
              </article>
              <article className="tile tile-sm">
                <Clock size={28} strokeWidth={1.5} />
                <h3 className="title-2">Короткий подбор</h3>
                <p className="body-6 muted">
                  От двух до четырёх текстов. Если первый оказался трудным, следующий будет
                  проще.
                </p>
              </article>
              <article className="tile tile-sm">
                <Sliders size={28} strokeWidth={1.5} />
                <h3 className="title-2">Решение остаётся за вами</h3>
                <p className="body-6 muted">
                  Рекомендация не окончательная. Не согласны, выберите другую сложность одним
                  нажатием.
                </p>
              </article>
              <article className="tile tile-sm">
                <LockOpen size={28} strokeWidth={1.5} />
                <h3 className="title-2">Без регистрации</h3>
                <p className="body-6 muted">
                  Аккаунт понадобится, только если захотите сохранить результат и открыть его
                  позже.
                </p>
              </article>
            </div>
          </div>
        </section>

        <section className="section" aria-label="Главная мысль">
          <div className="container">
            <p ref={taglineRef} className="heading-1 tagline">
              {TAGLINE.split(" ").map((word, index) => (
                <span key={index}>
                  <span className="tagline-word">{word}</span>{" "}
                </span>
              ))}
            </p>
          </div>
        </section>

        <section id="how" className="section section-muted" aria-labelledby="how-title">
          <div className="container reveal">
            <div className="section-head">
              <p className="caption-3 muted">Как это работает</p>
              <h2 id="how-title" className="heading-2">
                Три шага до рекомендации
              </h2>
            </div>
            <ol className="grid-3">
              <li className="tile">
                <span className="step-number title-4" aria-hidden="true">
                  1
                </span>
                <h3 className="title-1">Прочитайте короткий текст</h3>
                <p className="body-6 muted">
                  Первый фрагмент простой: про файлы и сохранение. Дальше сложность меняется по
                  вашим ответам.
                </p>
              </li>
              <li className="tile">
                <span className="step-number title-4" aria-hidden="true">
                  2
                </span>
                <h3 className="title-1">Отметьте незнакомые слова</h3>
                <p className="body-6 muted">
                  Нажмите на слова, значение которых непонятно в этом контексте. Всё понятно,
                  выберите «Все слова знакомы».
                </p>
              </li>
              <li className="tile">
                <span className="step-number title-4" aria-hidden="true">
                  3
                </span>
                <h3 className="title-1">Получите рекомендацию</h3>
                <p className="body-6 muted">
                  Один из четырёх уровней сложности с объяснением, почему именно он. Результат
                  можно сохранить в аккаунте.
                </p>
              </li>
            </ol>
          </div>
        </section>

        <section id="levels" className="section" aria-labelledby="levels-title">
          <div className="container reveal">
            <div className="section-head">
              <p className="caption-3 muted">Четыре уровня</p>
              <h2 id="levels-title" className="heading-2">
                Так выглядят тексты на каждом уровне
              </h2>
              <p className="body-3 muted">
                Это рабочие названия ступеней, а не уровни CEFR. Мы не выдаём сертификат, а
                подсказываем, с чего удобнее начать.
              </p>
            </div>
            <div className="grid-4">
              {LEVELS.map((level, index) => (
                <article key={level.name} className="level-card">
                  <div className="level-card-head">
                    <p className="caption-3 muted">Уровень {index + 1}</p>
                    <h3 className="title-2">{level.name}</h3>
                  </div>
                  <p className="level-card-sample body-6" lang="en">
                    {level.sample}
                  </p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="faq" className="section section-muted" aria-labelledby="faq-title">
          <div className="container faq reveal">
            <div className="section-head">
              <h2 id="faq-title" className="heading-2">
                Частые вопросы
              </h2>
            </div>
            <div className="faq-list">
              {FAQ.map((item) => (
                <details key={item.q} className="faq-item">
                  <summary className="title-2">
                    {item.q}
                    <span className="plus">
                      <Plus />
                    </span>
                  </summary>
                  <p className="body-3 muted">{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="section" aria-labelledby="cta-title">
          <div className="container reveal">
            <div className="final-cta">
              <h2 id="cta-title" className="heading-2">
                Начните с первого текста
              </h2>
              <p className="body-7">
                Регистрация не нужна. Рекомендацию можно изменить, а аккаунт создать потом, если
                захотите сохранить результат.
              </p>
              <button
                className="btn btn-marker button-lg"
                type="button"
                disabled={busy}
                onClick={() => start("final")}
              >
                {startLabel}
                <ArrowRight />
              </button>
              {errorAlert("final")}
            </div>
          </div>
        </section>
      </main>

      <footer className="container">
        <div className="footer">
          <p className="body-6 muted">English for Developers · учебный проект</p>
          <a className="body-6" href="#top">
            Наверх
          </a>
        </div>
      </footer>
    </div>
  );
}

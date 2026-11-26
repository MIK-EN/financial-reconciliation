import { useEffect, useRef, useState } from "react";

import { Question } from "./Question";
import { progressKey, readProgress, writeProgress } from "./progress";
import type { Answers, Exercise, Topic, TrainerData } from "./types";
import "./trainer.css";

export function Trainer() {
  const [data, setData] = useState<TrainerData | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    void fetch("/api/v1/trainer", {
      signal: controller.signal,
      credentials: "omit",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Content unavailable");
        const result: TrainerData = await response.json();
        if (!controller.signal.aborted) setData(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [attempt]);
  return (
    <div className="trainer">
      <a className="skip-link btn btn-primary" href="#trainer-main">
        Перейти к содержанию
      </a>
      <header className="trainer-header">
        <a className="brand title-4" href="/">
          <span className="brand-mark" aria-hidden="true">
            En
          </span>
          English for Developers
        </a>
        <a href="/" className="trainer-home">
          На главную <span aria-hidden="true">↗</span>
        </a>
      </header>
      <main id="trainer-main" className="trainer-main" tabIndex={-1}>
        {data !== null ? (
          <Practice key={data.content_hash} data={data} />
        ) : failed ? (
          <div className="trainer-intro">
            <h1 className="heading-3">Тренажёр пока недоступен</h1>
            <p role="alert">
              Не удалось загрузить задания. Попробуйте ещё раз.
            </p>
            <button
              className="btn btn-primary"
              onClick={() => setAttempt(attempt + 1)}
            >
              Повторить загрузку
            </button>
          </div>
        ) : (
          <p role="status">Загружаем задания…</p>
        )}
      </main>
    </div>
  );
}

function counts(topic: Topic, answers: Answers) {
  return {
    done: topic.exercises.filter((e) => answers[e.id] !== undefined).length,
    correct: topic.exercises.filter(
      (e) => answers[e.id] === e.correct_option_id,
    ).length,
  };
}

function Practice({ data }: { data: TrainerData }) {
  const [progress, setProgress] = useState(() => readProgress(data));
  const [active, setActive] = useState<{ topic: Topic; index: number } | null>(
    null,
  );
  const [summary, setSummary] = useState<Topic | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusTarget =
    active === null
      ? (summary?.id ?? "topics")
      : `${active.topic.id}-${active.index}`;
  useEffect(() => {
    heading.current?.focus();
  }, [focusTarget]);
  useEffect(() => {
    function sync(event: StorageEvent) {
      if (event.key === progressKey(data) || event.key === null)
        setProgress(readProgress(data));
    }
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, [data]);

  function save(exercise: Exercise, selected: string) {
    // Merge the latest other-tab changes; keep in-memory answers when storage is unavailable.
    const latest = readProgress(data);
    const answers = {
      ...progress.answers,
      ...latest.answers,
      [exercise.id]: selected,
    };
    const available = writeProgress(data, answers);
    setProgress({ answers, available });
  }

  const exercise = active?.topic.exercises[active.index];
  const total = data.content.topics.reduce(
    (sum, topic) => sum + counts(topic, progress.answers).done,
    0,
  );
  return (
    <>
      {!progress.available && (
        <p role="status" className="trainer-notice">
          Браузер не разрешил сохранить прогресс. Можно продолжать: ответы
          останутся до перезагрузки страницы.
        </p>
      )}
      {active !== null && exercise !== undefined ? (
        <>
          <button className="trainer-back" onClick={() => setActive(null)}>
            ← Все темы
          </button>
          <div className="trainer-task-heading">
            <p className="trainer-eyebrow">
              {active.topic.title} · {active.index + 1} из{" "}
              {active.topic.exercises.length} · {exercise.level}
            </p>
            <h1 className="heading-3" tabIndex={-1} ref={heading}>
              {exercise.title}
            </h1>
          </div>
          <Question
            key={exercise.id}
            exercise={exercise}
            onAnswer={(selected) => save(exercise, selected)}
            onNext={() => {
              if (active.index + 1 < active.topic.exercises.length) {
                setActive({ ...active, index: active.index + 1 });
              } else {
                setSummary(active.topic);
                setActive(null);
              }
            }}
            last={active.index + 1 === active.topic.exercises.length}
          />
        </>
      ) : summary !== null ? (
        <div className="trainer-intro trainer-summary">
          <span className="trainer-stamp" aria-hidden="true">
            ✓
          </span>
          <p className="trainer-eyebrow">{summary.title}</p>
          <h1 className="heading-3" ref={heading} tabIndex={-1}>
            Небольшой шаг. Полезный навык.
          </h1>
          <p>
            Пройдено {counts(summary, progress.answers).done} из{" "}
            {summary.exercises.length}. Правильно:{" "}
            {counts(summary, progress.answers).correct} из{" "}
            {summary.exercises.length}.
          </p>
          <p className="muted">
            Это результат последних ответов. Вернитесь к теме, чтобы закрепить
            выражения.
          </p>
          <button className="btn btn-primary" onClick={() => setSummary(null)}>
            Выбрать тему
          </button>
        </div>
      ) : (
        <>
          <div className="trainer-intro">
            <p className="trainer-eyebrow">
              <span className="trainer-dot" /> Тренажёр · A2–B1
            </p>
            <h1 className="trainer-title" ref={heading} tabIndex={-1}>
              Английский для
              <br />
              вашего рабочего дня<span className="trainer-title-dot">.</span>
            </h1>
            <p className="trainer-lead">
              Что сказать на дейлике? Как попросить ревью?
              <br className="trainer-wide" /> Попрактикуйтесь в знакомых
              ситуациях — по одному заданию.
            </p>
            <div className="trainer-meta">
              <span>◷ 1–2 минуты на задание</span>
              <span>Без регистрации</span>
              <span>12 коротких заданий</span>
            </div>
          </div>
          <div className="trainer-section-heading">
            <h2 className="heading-5">С чего начнём?</h2>
            <p className="muted">Пройдено {total} из 12</p>
          </div>
          <div className="trainer-topics">
            {data.content.topics.map((topic, index) => {
              const result = counts(topic, progress.answers);
              return (
                <button
                  key={topic.id}
                  className={`trainer-topic trainer-topic-${topic.id}`}
                  onClick={() => {
                    const next = topic.exercises.findIndex(
                      (e) => progress.answers[e.id] === undefined,
                    );
                    setActive({ topic, index: next < 0 ? 0 : next });
                  }}
                >
                  <span className="trainer-card-top">
                    <span className="trainer-symbol" aria-hidden="true">
                      {["⌘", "◉", "↗", "{ }"][index]}
                    </span>
                    <span className="trainer-card-number" aria-hidden="true">
                      0{index + 1} ↗
                    </span>
                  </span>
                  <span className="trainer-topic-title">{topic.title}</span>
                  <span className="trainer-topic-description">
                    {topic.description}
                  </span>
                  <span className="trainer-card-bottom">
                    Пройдено {result.done}/{topic.exercises.length} · Правильно{" "}
                    {result.correct}/{topic.exercises.length}
                    <span aria-hidden="true">
                      {result.done === topic.exercises.length ? "↻" : "→"}
                    </span>
                  </span>
                  <progress
                    value={result.done}
                    max={topic.exercises.length}
                    aria-label={`Прогресс: ${topic.title}`}
                  />
                </button>
              );
            })}
          </div>
          <p className="trainer-footnote">
            Выберите тему → прочитайте ситуацию → сравните варианты с
            объяснением.
            <br />
            Прогресс хранится в этом браузере. Последний ответ заменяет
            предыдущий.
          </p>
        </>
      )}
    </>
  );
}

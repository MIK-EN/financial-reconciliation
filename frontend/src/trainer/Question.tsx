import { useEffect, useRef, useState } from "react";
import type { Exercise } from "./types";

export function Question({
  exercise,
  onAnswer,
  onNext,
  last,
}: {
  exercise: Exercise;
  onAnswer: (id: string) => void;
  onNext: () => void;
  last: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const feedback = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (checked) feedback.current?.focus();
  }, [checked]);
  return (
    <div className="trainer-question">
      <div className="trainer-situation">
        <p className="trainer-eyebrow">Рабочая ситуация</p>
        <p lang="en">{exercise.situation}</p>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (selected === null || checked) return;
          onAnswer(selected);
          setChecked(true);
        }}
      >
        <fieldset className="trainer-options" disabled={checked}>
          <legend lang="en">{exercise.prompt}</legend>
          {exercise.options.map((option) => (
            <label
              key={option.id}
              className={`trainer-option ${selected === option.id ? "is-selected" : ""}`}
            >
              <input
                type="radio"
                name={exercise.id}
                value={option.id}
                checked={selected === option.id}
                onChange={() => setSelected(option.id)}
              />
              <span lang="en">{option.text}</span>
            </label>
          ))}
        </fieldset>
        {!checked && (
          <button
            className="btn btn-primary"
            disabled={selected === null}
            type="submit"
          >
            Проверить ответ
          </button>
        )}
      </form>
      {checked && (
        <section className="trainer-feedback" aria-labelledby="trainer-verdict">
          <h2
            id="trainer-verdict"
            className="heading-5"
            ref={feedback}
            tabIndex={-1}
          >
            {selected === exercise.correct_option_id
              ? "✓ Верно!"
              : "Попробуем разобраться"}
          </h2>
          {exercise.options.map((option) => (
            <div
              key={option.id}
              className={
                option.id === exercise.correct_option_id
                  ? "trainer-explanation is-best"
                  : "trainer-explanation"
              }
            >
              <p className="trainer-answer-label">
                {option.id === exercise.correct_option_id
                  ? "✓ Лучший вариант"
                  : "Другой вариант"}
                {option.id === selected ? " · Ваш ответ" : ""}
              </p>
              <p lang="en">{option.text}</p>
              <p className="body-6">{option.explanation}</p>
            </div>
          ))}
          <button className="btn btn-primary" onClick={onNext}>
            {last ? "Результат темы" : "Следующее задание"}{" "}
            <span aria-hidden="true">→</span>
          </button>
        </section>
      )}
    </div>
  );
}

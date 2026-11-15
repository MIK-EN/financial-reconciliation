import { type CompletedRun, type Level, isLevel } from "../types";

const levelNames: Record<Level, string> = {
  foundations: "Основы",
  basic_docs: "Базовая документация",
  confident_reading: "Уверенное чтение",
  complex_texts: "Сложные тексты",
};

interface ResultScreenProps {
  run: CompletedRun;
  busy: boolean;
  error: string | null;
  onSelectLevel: (level: Level) => void;
}

export function ResultScreen({ run, busy, error, onSelectLevel }: ResultScreenProps) {
  return (
    <main className="screen result-screen">
      <p className="eyebrow">Результат</p>
      <h1>Рекомендуем начать с: {levelNames[run.recommended_level]}</h1>
      <p className="lead">{run.explanation}</p>
      <p className="result-note">
        Это ориентир по отмеченным словам, а не оценка уровня английского. Вы можете выбрать
        другую сложность.
      </p>
      <label className="field">
        <span>Выбранная сложность</span>
        <select
          value={run.selected_level}
          disabled={busy}
          onChange={(event) => {
            if (isLevel(event.target.value)) onSelectLevel(event.target.value);
          }}
        >
          {Object.entries(levelNames).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <p>Выбрано: {levelNames[run.selected_level]}</p>
      {error === null ? null : (
        <p className="message message-error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}

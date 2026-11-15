import type { CompletedRun, Level } from "../types";

const levelNames: Record<Level, string> = {
  foundations: "Основы",
  basic_docs: "Базовая документация",
  confident_reading: "Уверенное чтение",
  complex_texts: "Сложные тексты",
};

interface ResultScreenProps {
  run: CompletedRun;
}

export function ResultScreen({ run }: ResultScreenProps) {
  return (
    <main className="screen result-screen">
      <p className="eyebrow">Результат</p>
      <h1>Рекомендуем начать с: {levelNames[run.recommended_level]}</h1>
      <p className="lead">{run.explanation}</p>
      <p className="result-note">
        Это ориентир по отмеченным словам, а не оценка уровня английского. Вы можете выбрать
        другую сложность.
      </p>
    </main>
  );
}

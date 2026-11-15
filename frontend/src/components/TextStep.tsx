import { useState } from "react";

import { loadDraft, saveDraft } from "../draft";
import type { ActiveRun } from "../types";

interface TextStepProps {
  run: ActiveRun;
  busy: boolean;
  error: string | null;
  onSubmit: (wordIds: string[]) => Promise<void>;
}

export function TextStep({ run, busy, error, onSubmit }: TextStepProps) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(loadDraft(run)));

  function toggleWord(wordId: string) {
    if (busy) return;
    const next = new Set(selected);
    if (next.has(wordId)) next.delete(wordId);
    else next.add(wordId);
    setSelected(next);
    saveDraft(run, [...next]);
  }

  const selectedIds = [...selected].sort();

  return (
    <main className="screen step-screen">
      <p className="step-number">Текст {run.step.ordinal}</p>
      <h1>Нажмите на слова, которые вам незнакомы</h1>
      <p className="step-help">
        Если непонятно выражение целиком, отметьте слова этого выражения. Повторяющееся
        слово отмечается сразу во всём тексте.
      </p>

      <p className="reading-text" lang="en">
        {run.step.segments.map((segment, index) => {
          const wordId = segment.word_id;
          return wordId === null ? (
            <span key={`${index}-${segment.text}`}>{segment.text}</span>
          ) : (
            <button
              className="word"
              type="button"
              key={`${index}-${wordId}`}
              aria-pressed={selected.has(wordId)}
              disabled={busy}
              onClick={() => toggleWord(wordId)}
            >
              {segment.text}
              <span className="selection-mark" aria-hidden="true">
                {selected.has(wordId) ? " ✓" : ""}
              </span>
            </button>
          );
        })}
      </p>

      {error === null ? null : (
        <p className="message message-error" role="alert">
          {error}
        </p>
      )}
      <button
        className="primary-action"
        type="button"
        disabled={busy}
        onClick={() => void onSubmit(selectedIds)}
      >
        {busy ? "Сохраняем…" : selectedIds.length === 0 ? "Все слова знакомы" : "Продолжить"}
      </button>
    </main>
  );
}

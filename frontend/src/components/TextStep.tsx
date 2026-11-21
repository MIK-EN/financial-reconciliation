import { useState } from "react";

import { loadDraft, saveDraft } from "../draft";
import type { ActiveRun } from "../types";
import { FlowShell } from "./FlowShell";
import { WarningCircle } from "./Icons";

interface TextStepProps {
  run: ActiveRun;
  busy: boolean;
  error: string | null;
  onSubmit: (wordIds: string[]) => Promise<void>;
}

function pluralWords(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "слово";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "слова";
  return "слов";
}

const MAX_TEXTS = 4;

export function TextStep({ run, busy, error, onSubmit }: TextStepProps) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(loadDraft(run)));

  function update(next: Set<string>) {
    setSelected(next);
    saveDraft(run, [...next]);
  }

  function toggleWord(wordId: string) {
    if (busy) return;
    const next = new Set(selected);
    if (next.has(wordId)) next.delete(wordId);
    else next.add(wordId);
    update(next);
  }

  const selectedIds = [...selected].sort();
  const count = selectedIds.length;

  return (
    <FlowShell busy={busy}>
      <div className="stack-12">
        <div className="step-meta">
          <p className="caption-3 muted">Текст {run.step.ordinal}</p>
          <span className="body-6 muted">всего от двух до четырёх</span>
          <span aria-hidden="true" style={{ display: "flex", gap: 4 }}>
            {Array.from({ length: MAX_TEXTS }, (_, index) => (
              <span
                key={index}
                style={{
                  width: 24,
                  height: 4,
                  borderRadius: 4,
                  background: index < run.step.ordinal ? "var(--ink)" : "var(--line)",
                }}
              />
            ))}
          </span>
        </div>
        <h1 className="heading-4">Нажмите на слова, которые вам незнакомы</h1>
        <p className="body-3 muted" style={{ maxWidth: 640 }}>
          Если непонятно выражение целиком, отметьте все его слова. Повторяющееся слово
          отмечается сразу во всём тексте.
        </p>
      </div>

      <div className="card reading-card">
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
              </button>
            );
          })}
        </p>
      </div>

      {error === null ? null : (
        <p className="message message-error body-6" role="alert">
          <WarningCircle />
          {error}
        </p>
      )}

      <div className="step-footer">
        <p className="title-4 muted" aria-live="polite">
          {count === 0 ? "Ничего не отмечено" : `Отмечено ${count} ${pluralWords(count)}`}
        </p>
        <div className="actions">
          {count === 0 ? null : (
            <button
              className="btn btn-ghost button-md"
              type="button"
              disabled={busy}
              onClick={() => update(new Set())}
            >
              Снять отметки
            </button>
          )}
          <button
            className="btn btn-primary button-md"
            type="button"
            disabled={busy}
            onClick={() => void onSubmit(selectedIds)}
          >
            {busy ? "Сохраняем…" : count === 0 ? "Все слова знакомы" : "Продолжить"}
          </button>
        </div>
      </div>
    </FlowShell>
  );
}

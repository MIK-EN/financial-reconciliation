import type { ActiveRun } from "./types";

interface DraftValue {
  word_ids: string[];
}

function draftKey(run: ActiveRun): string {
  return ["onboarding-draft", run.id, run.step.id, run.bundle_version].join(":");
}

function currentWordIds(run: ActiveRun): Set<string> {
  return new Set(
    run.step.segments.flatMap((segment) =>
      segment.word_id === null ? [] : [segment.word_id],
    ),
  );
}

function parseDraft(value: unknown, allowed: Set<string>): DraftValue | null {
  if (typeof value !== "object" || value === null || !("word_ids" in value)) {
    return null;
  }
  const wordIds = value.word_ids;
  if (!Array.isArray(wordIds)) {
    return null;
  }
  const validIds = new Set<string>();
  for (const id of wordIds) {
    if (typeof id !== "string") return null;
    if (allowed.has(id)) validIds.add(id);
  }
  return {
    word_ids: [...validIds].sort(),
  };
}

export function loadDraft(run: ActiveRun): string[] {
  try {
    const raw = window.sessionStorage.getItem(draftKey(run));
    if (raw === null) return [];
    const draft = parseDraft(JSON.parse(raw) as unknown, currentWordIds(run));
    return draft?.word_ids ?? [];
  } catch {
    return [];
  }
}

export function saveDraft(run: ActiveRun, wordIds: string[]): void {
  const allowed = currentWordIds(run);
  const draft = parseDraft({ word_ids: wordIds }, allowed);
  if (draft === null) return;
  try {
    window.sessionStorage.setItem(draftKey(run), JSON.stringify(draft));
  } catch {
    // Storage is an optional enhancement; the in-memory selection remains usable.
  }
}

export function clearDraft(run: ActiveRun): void {
  try {
    window.sessionStorage.removeItem(draftKey(run));
  } catch {
    // A storage failure must not change the server-authoritative flow.
  }
}

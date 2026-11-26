import type { Answers, TrainerData } from "./types";

export function progressKey(data: TrainerData): string {
  return `english-for-developers:trainer:v1:${data.content_hash}`;
}

export function readProgress(data: TrainerData): {
  answers: Answers;
  available: boolean;
} {
  let saved: string | null;
  try {
    saved = window.localStorage.getItem(progressKey(data));
  } catch {
    return { answers: {}, available: false };
  }
  const answers: Answers = {};
  try {
    const raw: unknown = JSON.parse(saved ?? "{}");
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
      return { answers, available: true };
    }
    for (const topic of data.content.topics) {
      for (const exercise of topic.exercises) {
        const selected: unknown = Object.hasOwn(raw, exercise.id)
          ? (raw as Record<string, unknown>)[exercise.id]
          : undefined;
        if (
          typeof selected === "string" &&
          exercise.options.some((o) => o.id === selected)
        ) {
          answers[exercise.id] = selected;
        }
      }
    }
  } catch {
    // A damaged record is a fresh start, not a reason to prevent practice.
  }
  return { answers, available: true };
}

export function writeProgress(data: TrainerData, answers: Answers): boolean {
  try {
    window.localStorage.setItem(progressKey(data), JSON.stringify(answers));
    return true;
  } catch {
    return false;
  }
}

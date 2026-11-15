import { useEffect, useState } from "react";

import {
  ApiRequestError,
  createBrowserSession,
  getContext,
  getRun,
  startRun,
  submitAnswer,
} from "./api";
import { ResultScreen } from "./components/ResultScreen";
import { StartScreen } from "./components/StartScreen";
import { TextStep } from "./components/TextStep";
import type { RunState } from "./types";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError && error.status === 503) {
    return "Сервис временно недоступен. Попробуйте ещё раз.";
  }
  if (error instanceof TypeError) {
    return "Не удалось связаться с сервером. Проверьте соединение и повторите попытку.";
  }
  return "Не удалось выполнить действие. Попробуйте ещё раз.";
}

function keepNewestRun(current: RunState | null, candidate: RunState): RunState {
  if (current?.id === candidate.id && current.revision > candidate.revision) {
    return current;
  }
  return candidate;
}

export function App() {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [run, setRun] = useState<RunState | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      try {
        const context = await getContext();
        if (cancelled) return;
        setCsrfToken(context.csrf_token);
        if (context.anonymous_run_id !== null) {
          const restored = await getRun(context.anonymous_run_id);
          if (!cancelled) setRun((current) => keepNewestRun(current, restored));
        }
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleStart() {
    setBusy(true);
    setError(null);
    try {
      let token = csrfToken;
      if (token === null) {
        const session = await createBrowserSession();
        token = session.csrf_token;
        setCsrfToken(token);
      }
      const started = await startRun(token);
      setRun((current) => keepNewestRun(current, started));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleAnswer(wordIds: string[]) {
    if (run?.status !== "active" || csrfToken === null) return;
    const submittedRun = run;
    setBusy(true);
    setError(null);
    try {
      const next = await submitAnswer(submittedRun.id, csrfToken, {
        step_id: submittedRun.step.id,
        mode: wordIds.length === 0 ? "all_known" : "unknown_words",
        word_ids: wordIds,
        content_version: submittedRun.bundle_version,
      });
      setRun((current) => keepNewestRun(current, next));
    } catch (caught) {
      if (caught instanceof ApiRequestError && caught.status === 409) {
        try {
          const restored = await getRun(submittedRun.id);
          setRun((current) => keepNewestRun(current, restored));
        } catch (restoreError) {
          setError(errorMessage(restoreError));
        }
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="screen loading-screen" aria-live="polite">
        Загружаем…
      </main>
    );
  }
  if (run === null) {
    return <StartScreen busy={busy} error={error} onStart={() => void handleStart()} />;
  }
  if (run.status === "active") {
    return (
      <TextStep
        key={run.step.id}
        run={run}
        busy={busy}
        error={error}
        onSubmit={handleAnswer}
      />
    );
  }
  return <ResultScreen run={run} />;
}

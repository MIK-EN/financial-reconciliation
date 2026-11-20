import { useEffect, useState } from "react";

import {
  ApiRequestError,
  claimRun,
  createBrowserSession,
  getContext,
  getRun,
  login as loginAccount,
  logout as logoutAccount,
  register as registerAccount,
  startRun,
  submitAnswer,
  updateSelection,
} from "./api";
import { LoadingScreen } from "./components/FlowShell";
import { ResultScreen } from "./components/ResultScreen";
import { StartScreen } from "./components/StartScreen";
import { TextStep } from "./components/TextStep";
import { AccountForm, type AccountMode } from "./components/AccountForm";
import { clearDraft } from "./draft";
import type { AccountContext, Level, RunState } from "./types";

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
  const [accountError, setAccountError] = useState<string | null>(null);
  const [guestCsrfToken, setGuestCsrfToken] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountContext | null>(null);
  const [accountMode, setAccountMode] = useState<AccountMode | null>(null);
  const [accountOfferDismissed, setAccountOfferDismissed] = useState(false);
  const [run, setRun] = useState<RunState | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      try {
        const context = await getContext();
        if (cancelled) return;
        setGuestCsrfToken(context.csrf_token);
        setAccount(context.account);
        const runId = context.anonymous_run_id ?? context.account?.current_run_id ?? null;
        if (runId !== null) {
          const restored = await getRun(runId);
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
      let token = guestCsrfToken;
      if (token === null) {
        const session = await createBrowserSession();
        token = session.csrf_token;
        setGuestCsrfToken(token);
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
    if (run?.status !== "active" || guestCsrfToken === null) return;
    const submittedRun = run;
    setBusy(true);
    setError(null);
    try {
      const next = await submitAnswer(submittedRun.id, guestCsrfToken, {
        step_id: submittedRun.step.id,
        mode: wordIds.length === 0 ? "all_known" : "unknown_words",
        word_ids: wordIds,
        content_version: submittedRun.bundle_version,
      });
      clearDraft(submittedRun);
      setRun((current) => keepNewestRun(current, next));
    } catch (caught) {
      if (caught instanceof ApiRequestError && caught.status === 409) {
        try {
          const restored = await getRun(submittedRun.id);
          if (restored.status === "completed" || restored.step.id !== submittedRun.step.id) {
            clearDraft(submittedRun);
          }
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

  async function handleSelection(level: Level) {
    if (run?.status !== "completed") return;
    const csrfToken = run.saved_to_account ? account?.csrf_token : guestCsrfToken;
    if (csrfToken == null) return;
    const submittedRun = run;
    setBusy(true);
    setError(null);
    try {
      const next = await updateSelection(
        submittedRun.id,
        csrfToken,
        level,
        submittedRun.revision,
      );
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

  async function handleRegister(username: string, password: string) {
    if (run?.status !== "completed" || guestCsrfToken === null) return;
    const completedRun = run;
    setBusy(true);
    setAccountError(null);
    try {
      const registered = await registerAccount(guestCsrfToken, {
        username,
        password,
        run_id: completedRun.id,
      });
      setAccount(registered);
      setGuestCsrfToken(null);
      setAccountMode(null);
      const saved = await getRun(completedRun.id);
      setRun((current) => keepNewestRun(current, saved));
    } catch (caught) {
      setAccountError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogin(username: string, password: string) {
    setBusy(true);
    setAccountError(null);
    try {
      let token = guestCsrfToken;
      if (token === null) {
        const session = await createBrowserSession();
        token = session.csrf_token;
        setGuestCsrfToken(token);
      }
      const loggedIn = await loginAccount(token, { username, password });
      setAccount(loggedIn);
      setAccountMode(null);
      if (run === null && loggedIn.current_run_id !== null) {
        const restored = await getRun(loggedIn.current_run_id);
        setRun((current) => keepNewestRun(current, restored));
      }
    } catch (caught) {
      setAccountError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    if (account === null) return;
    setBusy(true);
    setError(null);
    try {
      await logoutAccount(account.csrf_token);
      setAccount(null);
      setAccountMode(null);
      if (run?.status === "completed" && run.saved_to_account) setRun(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleClaim() {
    if (run?.status !== "completed" || account === null || run.saved_to_account) return;
    const guestRun = run;
    setBusy(true);
    setError(null);
    try {
      const saved = await claimRun(guestRun.id, account.csrf_token, guestRun.revision);
      setRun((current) => keepNewestRun(current, saved));
      setAccount({ ...account, current_run_id: guestRun.id });
      setGuestCsrfToken(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <LoadingScreen />;
  }
  if (run === null) {
    if (accountMode === "login") {
      return (
        <AccountForm
          mode="login"
          busy={busy}
          error={accountError}
          onSubmit={handleLogin}
          onCancel={() => setAccountMode(null)}
        />
      );
    }
    return (
      <StartScreen
        busy={busy}
        error={error}
        onStart={() => void handleStart()}
        onLogin={() => {
          setAccountError(null);
          setAccountMode("login");
        }}
      />
    );
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
  return (
    <ResultScreen
      run={run}
      busy={busy}
      error={error}
      account={account}
      accountOfferDismissed={accountOfferDismissed}
      accountForm={
        accountMode === null ? null : (
          <AccountForm
            key={accountMode}
            mode={accountMode}
            busy={busy}
            error={accountError}
            onSubmit={accountMode === "register" ? handleRegister : handleLogin}
            onCancel={() => setAccountMode(null)}
          />
        )
      }
      onSelectLevel={(level) => void handleSelection(level)}
      onRegister={() => {
        setAccountError(null);
        setAccountMode("register");
      }}
      onLogin={() => {
        setAccountError(null);
        setAccountMode("login");
      }}
      onLogout={() => void handleLogout()}
      onClaim={() => void handleClaim()}
      onDismissAccountOffer={() => {
        setAccountOfferDismissed(true);
        setAccountMode(null);
      }}
    />
  );
}

import { useEffect, useState } from "react";

import {
  ApiRequestError,
  claimRun,
  createBrowserSession,
  getContext,
  getRun,
  getTelegramNonce,
  login as loginAccount,
  logout as logoutAccount,
  register as registerAccount,
  signInWithTelegram,
  startRun,
  submitAnswer,
  updateSelection,
} from "./api";
import { FlowShell, LoadingScreen } from "./components/FlowShell";
import { Landing } from "./components/Landing";
import { ResultScreen } from "./components/ResultScreen";
import { TextStep } from "./components/TextStep";
import { AccountForm, type AccountMode, type TelegramOption } from "./components/AccountForm";
import { clearDraft } from "./draft";
import { type TelegramAuthResult, loadTelegramLibrary, openTelegramPopup } from "./telegram";
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

function telegramErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const code = error.body?.code;
    if (code === "registration_conflict") {
      return "Аккаунта с этим Telegram пока нет. Пройдите подбор сложности и сохраните результат через Telegram.";
    }
    if (code === "identity_conflict") {
      return "Этот Telegram только что привязан к аккаунту. Нажмите «Войти через Telegram» ещё раз.";
    }
    if (code === "already_authenticated") return "Вы уже вошли в аккаунт. Обновите страницу.";
    if (code === "telegram_unavailable") {
      return "Telegram сейчас недоступен. Попробуйте позже или войдите по логину и паролю.";
    }
    if (error.status === 401) return "Не удалось подтвердить вход через Telegram. Попробуйте ещё раз.";
  }
  return errorMessage(error);
}

type TelegramState =
  | { status: "off" | "loading" | "unavailable" }
  | {
      status: "ready";
      api: Awaited<ReturnType<typeof loadTelegramLibrary>>;
      clientId: string;
      nonce: string;
      csrfToken: string;
    };

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
  const [telegram, setTelegram] = useState<TelegramState>({ status: "off" });
  const [telegramAttempt, setTelegramAttempt] = useState(0);

  // Prepare Telegram while the account form is open: the nonce and the library
  // must be ready before the click, otherwise the browser blocks the popup.
  useEffect(() => {
    if (accountMode === null) return;
    let cancelled = false;

    async function prepare() {
      setTelegram({ status: "loading" });
      try {
        let csrfToken = guestCsrfToken;
        if (csrfToken === null) {
          const session = await createBrowserSession();
          csrfToken = session.csrf_token;
          if (!cancelled) setGuestCsrfToken(csrfToken);
        }
        const issued = await getTelegramNonce(csrfToken);
        const api = await loadTelegramLibrary();
        if (!cancelled) {
          setTelegram({
            status: "ready",
            api,
            clientId: issued.client_id,
            nonce: issued.nonce,
            csrfToken,
          });
        }
      } catch (caught) {
        if (cancelled) return;
        const disabled = caught instanceof ApiRequestError && caught.status === 404;
        setTelegram({ status: disabled ? "off" : "unavailable" });
      }
    }

    void prepare();
    return () => {
      cancelled = true;
    };
    // guestCsrfToken is read once per opening; a new token must not re-issue the nonce.
  }, [accountMode, telegramAttempt]);

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

  function handleTelegramClick() {
    if (telegram.status !== "ready") return;
    const { api, clientId, nonce, csrfToken } = telegram;
    setAccountError(null);
    openTelegramPopup(api, clientId, nonce, (result) => {
      void finishTelegramSignIn(result, csrfToken);
    });
  }

  async function finishTelegramSignIn(result: TelegramAuthResult, csrfToken: string) {
    if (result.id_token === undefined) {
      if (result.error !== "popup_closed") {
        setAccountError("Telegram не подтвердил вход. Попробуйте ещё раз.");
      }
      return;
    }
    const guestRun = run?.status === "completed" && !run.saved_to_account ? run : null;
    setBusy(true);
    setAccountError(null);
    try {
      const signedIn = await signInWithTelegram(csrfToken, {
        id_token: result.id_token,
        run_id: guestRun?.id ?? null,
      });
      setAccount(signedIn);
      setAccountMode(null);
      if (guestRun !== null) {
        // A new Telegram account claims the run and revokes the guest session;
        // an existing account leaves the guest run for an explicit claim.
        const refreshed = await getRun(guestRun.id);
        if (refreshed.status === "completed" && refreshed.saved_to_account) {
          setGuestCsrfToken(null);
        }
        setRun((current) => keepNewestRun(current, refreshed));
      } else if (run === null && signedIn.current_run_id !== null) {
        const restored = await getRun(signedIn.current_run_id);
        setRun((current) => keepNewestRun(current, restored));
      }
    } catch (caught) {
      setAccountError(telegramErrorMessage(caught));
      setTelegramAttempt((attempt) => attempt + 1); // Fetch a fresh nonce for the retry.
    } finally {
      setBusy(false);
    }
  }

  const telegramOption: TelegramOption | null =
    telegram.status === "off"
      ? null
      : telegram.status === "ready"
        ? { status: "ready", onClick: handleTelegramClick }
        : { status: telegram.status };

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
        <FlowShell busy={busy}>
          <AccountForm
            mode="login"
            busy={busy}
            error={accountError}
            onSubmit={handleLogin}
            onCancel={() => setAccountMode(null)}
            telegram={telegramOption}
          />
        </FlowShell>
      );
    }
    return (
      <Landing
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
            telegram={telegramOption}
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

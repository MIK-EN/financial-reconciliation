import {
  type AccountContext,
  type ApiErrorBody,
  type BrowserContext,
  type BrowserSession,
  type Level,
  type RunState,
  type TelegramNonce,
  parseAccountContext,
  parseApiError,
  parseBrowserContext,
  parseBrowserSession,
  parseRunState,
  parseTelegramNonce,
} from "./types";

type Decoder<T> = (value: unknown) => T;

export class ApiRequestError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.message ?? "Request failed");
    this.name = "ApiRequestError";
    this.status = status;
    this.body = body;
  }
}

function mutationHeaders(csrfToken?: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    ...(csrfToken === undefined ? {} : { "X-CSRF-Token": csrfToken }),
  };
}

async function requestJson<T>(
  path: string,
  decoder: Decoder<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiRequestError(response.status, parseApiError(value));
  }
  return decoder(value);
}

async function requestEmpty(path: string, init: RequestInit): Promise<void> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    const value: unknown = await response.json().catch(() => null);
    throw new ApiRequestError(response.status, parseApiError(value));
  }
}

export function createBrowserSession(csrfToken?: string): Promise<BrowserSession> {
  return requestJson("/api/v1/browser-session", parseBrowserSession, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: "{}",
  });
}

export function getContext(): Promise<BrowserContext> {
  return requestJson("/api/v1/context", parseBrowserContext);
}

export function startRun(csrfToken: string): Promise<RunState> {
  return requestJson("/api/v1/onboarding", parseRunState, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: "{}",
  });
}

export function getRun(runId: string): Promise<RunState> {
  return requestJson(`/api/v1/onboarding/${runId}`, parseRunState);
}

export function submitAnswer(
  runId: string,
  csrfToken: string,
  answer: {
    step_id: string;
    mode: "all_known" | "unknown_words";
    word_ids: string[];
    content_version: string;
  },
): Promise<RunState> {
  return requestJson(`/api/v1/onboarding/${runId}/answers`, parseRunState, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: JSON.stringify(answer),
  });
}

export function updateSelection(
  runId: string,
  csrfToken: string,
  selectedLevel: Level,
  expectedRevision: number,
): Promise<RunState> {
  return requestJson(`/api/v1/onboarding/${runId}/selection`, parseRunState, {
    method: "PUT",
    headers: mutationHeaders(csrfToken),
    body: JSON.stringify({
      selected_level: selectedLevel,
      expected_revision: expectedRevision,
    }),
  });
}

export function register(
  csrfToken: string,
  credentials: { username: string; password: string; run_id: string },
): Promise<AccountContext> {
  return requestJson("/api/v1/auth/register", parseAccountContext, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: JSON.stringify(credentials),
  });
}

export function login(
  csrfToken: string,
  credentials: { username: string; password: string },
): Promise<AccountContext> {
  return requestJson("/api/v1/auth/login", parseAccountContext, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: JSON.stringify(credentials),
  });
}

export function getTelegramNonce(csrfToken: string): Promise<TelegramNonce> {
  return requestJson("/api/v1/auth/telegram/nonce", parseTelegramNonce, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: "{}",
  });
}

export function signInWithTelegram(
  csrfToken: string,
  payload: { id_token: string; run_id: string | null },
): Promise<AccountContext> {
  return requestJson("/api/v1/auth/telegram", parseAccountContext, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: JSON.stringify(payload),
  });
}

export function logout(csrfToken?: string): Promise<void> {
  return requestEmpty("/api/v1/auth/logout", {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: "{}",
  });
}

export function claimRun(
  runId: string,
  csrfToken: string,
  expectedRevision: number,
): Promise<RunState> {
  return requestJson(`/api/v1/onboarding/${runId}/claim`, parseRunState, {
    method: "POST",
    headers: mutationHeaders(csrfToken),
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

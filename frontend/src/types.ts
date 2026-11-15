export type Level = "foundations" | "basic_docs" | "confident_reading" | "complex_texts";

export interface AccountContext {
  user_id: string;
  username: string;
  csrf_token: string;
  current_run_id: string | null;
  expires_at: string;
}

export interface BrowserContext {
  anonymous_session_id: string | null;
  csrf_token: string | null;
  saved_run_ids: string[];
  anonymous_run_id: string | null;
  account: AccountContext | null;
}

export interface BrowserSession {
  session_id: string;
  session_type: string;
  csrf_token: string;
  expires_at: string;
}

export interface Segment {
  text: string;
  word_id: string | null;
}

export interface ActiveRun {
  id: string;
  status: "active";
  revision: number;
  bundle_version: string;
  expires_at: string;
  step: {
    id: string;
    ordinal: number;
    text_id: string;
    segments: Segment[];
  };
}

export interface CompletedRun {
  id: string;
  status: "completed";
  revision: number;
  bundle_version: string;
  expires_at: string;
  recommended_level: Level;
  selected_level: Level;
  reason_code: string;
  explanation: string;
  saved_to_account: boolean;
}

export type RunState = ActiveRun | CompletedRun;

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id?: string;
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} is not an object`);
  }
  return value as JsonObject;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} is not a string`);
  }
  return value;
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${label} is not an integer`);
  }
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  return value === null ? null : string(value, label);
}

function parseAccount(value: unknown): AccountContext {
  const data = object(value, "account");
  return {
    user_id: string(data.user_id, "account.user_id"),
    username: string(data.username, "account.username"),
    csrf_token: string(data.csrf_token, "account.csrf_token"),
    current_run_id: nullableString(data.current_run_id, "account.current_run_id"),
    expires_at: string(data.expires_at, "account.expires_at"),
  };
}

export function parseAccountContext(value: unknown): AccountContext {
  return parseAccount(value);
}

export function parseBrowserContext(value: unknown): BrowserContext {
  const data = object(value, "context");
  if (!Array.isArray(data.saved_run_ids)) {
    throw new Error("context.saved_run_ids is not an array");
  }
  return {
    anonymous_session_id: nullableString(
      data.anonymous_session_id,
      "context.anonymous_session_id",
    ),
    csrf_token: nullableString(data.csrf_token, "context.csrf_token"),
    saved_run_ids: data.saved_run_ids.map((id) => string(id, "context.saved_run_ids[]")),
    anonymous_run_id: nullableString(data.anonymous_run_id, "context.anonymous_run_id"),
    account: data.account === null ? null : parseAccount(data.account),
  };
}

export function parseBrowserSession(value: unknown): BrowserSession {
  const data = object(value, "browser session");
  return {
    session_id: string(data.session_id, "browser_session.session_id"),
    session_type: string(data.session_type, "browser_session.session_type"),
    csrf_token: string(data.csrf_token, "browser_session.csrf_token"),
    expires_at: string(data.expires_at, "browser_session.expires_at"),
  };
}

export function isLevel(value: unknown): value is Level {
  return (
    value === "foundations" ||
    value === "basic_docs" ||
    value === "confident_reading" ||
    value === "complex_texts"
  );
}

function parseLevel(value: unknown, label: string): Level {
  if (!isLevel(value)) {
    throw new Error(`${label} is not a level`);
  }
  return value;
}

export function parseRunState(value: unknown): RunState {
  const data = object(value, "run");
  const common = {
    id: string(data.id, "run.id"),
    revision: number(data.revision, "run.revision"),
    bundle_version: string(data.bundle_version, "run.bundle_version"),
    expires_at: string(data.expires_at, "run.expires_at"),
  };
  if (data.status === "active") {
    const step = object(data.step, "run.step");
    if (!Array.isArray(step.segments)) {
      throw new Error("run.step.segments is not an array");
    }
    return {
      ...common,
      status: "active",
      step: {
        id: string(step.id, "run.step.id"),
        ordinal: number(step.ordinal, "run.step.ordinal"),
        text_id: string(step.text_id, "run.step.text_id"),
        segments: step.segments.map((segmentValue) => {
          const segment = object(segmentValue, "run.step.segment");
          return {
            text: string(segment.text, "run.step.segment.text"),
            word_id: nullableString(segment.word_id, "run.step.segment.word_id"),
          };
        }),
      },
    };
  }
  if (data.status !== "completed") {
    throw new Error("run.status is invalid");
  }
  if (typeof data.saved_to_account !== "boolean") {
    throw new Error("run.saved_to_account is not a boolean");
  }
  return {
    ...common,
    status: "completed",
    recommended_level: parseLevel(data.recommended_level, "run.recommended_level"),
    selected_level: parseLevel(data.selected_level, "run.selected_level"),
    reason_code: string(data.reason_code, "run.reason_code"),
    explanation: string(data.explanation, "run.explanation"),
    saved_to_account: data.saved_to_account,
  };
}

export function parseApiError(value: unknown): ApiErrorBody | null {
  try {
    const data = object(value, "api error");
    return {
      code: string(data.code, "api error.code"),
      message: string(data.message, "api error.message"),
      ...(typeof data.request_id === "string" ? { request_id: data.request_id } : {}),
    };
  } catch {
    return null;
  }
}

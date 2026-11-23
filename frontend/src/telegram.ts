// Loads the official Telegram Login library on demand and opens its popup.
// Only the "openid" scope is requested: the backend needs nothing but the
// stable subject, so no name, photo, phone or bot-messaging access is asked.

export const TELEGRAM_LIBRARY_URL = "https://oauth.telegram.org/js/telegram-login.js?6";

export interface TelegramAuthResult {
  id_token?: string;
  error?: string;
}

interface TelegramLoginApi {
  auth(
    options: { client_id: string; nonce: string; scope: string[]; lang: string },
    callback: (result: TelegramAuthResult) => void,
  ): void;
}

declare global {
  interface Window {
    Telegram?: { Login?: TelegramLoginApi };
  }
}

let loading: Promise<TelegramLoginApi> | null = null;

export function loadTelegramLibrary(): Promise<TelegramLoginApi> {
  if (window.Telegram?.Login !== undefined) return Promise.resolve(window.Telegram.Login);
  if (loading !== null) return loading;
  loading = new Promise<TelegramLoginApi>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = TELEGRAM_LIBRARY_URL;
    script.async = true;
    script.onload = () => {
      const api = window.Telegram?.Login;
      if (api === undefined) reject(new Error("Telegram library did not initialise"));
      else resolve(api);
    };
    script.onerror = () => reject(new Error("Telegram library failed to load"));
    document.head.appendChild(script);
  }).catch((error: unknown) => {
    loading = null; // A later attempt may succeed, e.g. after the network recovers.
    throw error;
  });
  return loading;
}

/** Must run synchronously inside a click handler so the popup is not blocked. */
export function openTelegramPopup(
  api: TelegramLoginApi,
  clientId: string,
  nonce: string,
  onResult: (result: TelegramAuthResult) => void,
): void {
  api.auth({ client_id: clientId, nonce, scope: [], lang: "ru" }, onResult);
}

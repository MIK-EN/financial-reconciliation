import { type FormEvent, useState } from "react";

export type AccountMode = "register" | "login";

interface AccountFormProps {
  mode: AccountMode;
  busy: boolean;
  error: string | null;
  onSubmit: (username: string, password: string) => Promise<void>;
  onCancel: () => void;
}

export function AccountForm({ mode, busy, error, onSubmit, onCancel }: AccountFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onSubmit(username, password);
  }

  return (
    <section className="account-panel" aria-labelledby="account-title">
      <h2 id="account-title">{mode === "register" ? "Сохранить результат" : "Войти"}</h2>
      <p>
        В первой версии нет восстановления пароля. Если вы его забудете, восстановить доступ
        к аккаунту не получится.
      </p>
      <form onSubmit={handleSubmit}>
        <label className="field">
          <span>Логин</span>
          <input
            name="username"
            autoComplete="username"
            minLength={3}
            maxLength={32}
            required
            value={username}
            disabled={busy}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="field">
          <span>Пароль</span>
          <input
            name="password"
            type="password"
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            minLength={15}
            maxLength={128}
            required
            value={password}
            disabled={busy}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error === null ? null : (
          <p className="message message-error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="primary-action" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : mode === "register" ? "Создать аккаунт" : "Войти"}
          </button>
          <button className="secondary-action" type="button" disabled={busy} onClick={onCancel}>
            Отмена
          </button>
        </div>
      </form>
    </section>
  );
}

import { type FormEvent, useState } from "react";

import { LockSimple, WarningCircle } from "./Icons";

export type AccountMode = "register" | "login";

interface AccountFormProps {
  mode: AccountMode;
  busy: boolean;
  error: string | null;
  onSubmit: (username: string, password: string) => Promise<void>;
  onCancel: () => void;
}

const USERNAME_PATTERN = /^[a-z0-9_]{3,32}$/;
const PASSWORD_MIN = 15;
const PASSWORD_MAX = 128;

interface FieldErrors {
  username?: string;
  password?: string;
}

function validate(mode: AccountMode, username: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  const normalized = username.trim().toLowerCase();
  if (normalized === "") errors.username = "Введите логин.";
  else if (mode === "register" && !USERNAME_PATTERN.test(normalized)) {
    errors.username = "Логин может содержать от 3 до 32 символов: латиницу, цифры и подчёркивание.";
  }
  if (password === "") errors.password = "Введите пароль.";
  else if (mode === "register" && password.length < PASSWORD_MIN) {
    const missing = PASSWORD_MIN - password.length;
    errors.password = `Пароль короче ${PASSWORD_MIN} символов. Добавьте ещё ${missing}.`;
  } else if (password.length > PASSWORD_MAX) {
    errors.password = `Пароль длиннее ${PASSWORD_MAX} символов.`;
  }
  return errors;
}

export function AccountForm({ mode, busy, error, onSubmit, onCancel }: AccountFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const isRegister = mode === "register";

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validate(mode, username, password);
    setFieldErrors(errors);
    if (errors.username !== undefined || errors.password !== undefined) return;
    void onSubmit(username, password);
  }

  return (
    <section className="card stack-16" aria-labelledby="account-title" style={{ maxWidth: 520 }}>
      <div className="stack-4">
        <h2 id="account-title" className="heading-5">
          {isRegister ? "Сохранить результат" : "Войти"}
        </h2>
        <p className="body-6 muted">
          {isRegister
            ? "Рекомендация и выбранная сложность сохранятся в новом аккаунте."
            : "Войдите, чтобы открыть сохранённый результат."}
        </p>
      </div>
      <p className="message message-warning body-6">
        <LockSimple />
        В первой версии нет восстановления пароля. Если вы его забудете, восстановить доступ к
        аккаунту не получится.
      </p>
      <form className="stack-16" onSubmit={handleSubmit} noValidate>
        <label className="field">
          <span className="title-4">Логин</span>
          <input
            className="input"
            name="username"
            autoComplete="username"
            maxLength={32}
            required
            value={username}
            disabled={busy}
            aria-invalid={fieldErrors.username !== undefined}
            aria-describedby="username-note"
            onChange={(event) => {
              setUsername(event.target.value);
              setFieldErrors((current) => ({ ...current, username: undefined }));
            }}
          />
          <span
            id="username-note"
            className={fieldErrors.username === undefined ? "caption-5 muted" : "caption-4 field-error"}
          >
            {fieldErrors.username ??
              (isRegister ? "От 3 до 32 символов: латиница, цифры и подчёркивание" : "")}
          </span>
        </label>
        <label className="field">
          <span className="title-4">Пароль</span>
          <input
            className="input"
            name="password"
            type="password"
            autoComplete={isRegister ? "new-password" : "current-password"}
            maxLength={PASSWORD_MAX}
            required
            value={password}
            disabled={busy}
            aria-invalid={fieldErrors.password !== undefined}
            aria-describedby="password-note"
            onChange={(event) => {
              setPassword(event.target.value);
              setFieldErrors((current) => ({ ...current, password: undefined }));
            }}
          />
          <span
            id="password-note"
            className={fieldErrors.password === undefined ? "caption-5 muted" : "caption-4 field-error"}
          >
            {fieldErrors.password ?? (isRegister ? `Не короче ${PASSWORD_MIN} символов` : "")}
          </span>
        </label>
        {error === null ? null : (
          <p className="message message-error body-6" role="alert">
            <WarningCircle />
            {error}
          </p>
        )}
        <div className="actions">
          <button className="btn btn-primary button-md" type="submit" disabled={busy}>
            {busy ? (isRegister ? "Сохраняем…" : "Входим…") : isRegister ? "Создать аккаунт" : "Войти"}
          </button>
          <button className="btn btn-ghost button-md" type="button" disabled={busy} onClick={onCancel}>
            Отмена
          </button>
        </div>
      </form>
    </section>
  );
}

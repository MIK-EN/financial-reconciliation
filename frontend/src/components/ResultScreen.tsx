import { type AccountContext, type CompletedRun, type Level, isLevel } from "../types";

const levelNames: Record<Level, string> = {
  foundations: "Основы",
  basic_docs: "Базовая документация",
  confident_reading: "Уверенное чтение",
  complex_texts: "Сложные тексты",
};

interface ResultScreenProps {
  run: CompletedRun;
  busy: boolean;
  error: string | null;
  account: AccountContext | null;
  accountOfferDismissed: boolean;
  onSelectLevel: (level: Level) => void;
  onRegister: () => void;
  onLogin: () => void;
  onLogout: () => void;
  onClaim: () => void;
  onDismissAccountOffer: () => void;
}

export function ResultScreen({
  run,
  busy,
  error,
  account,
  accountOfferDismissed,
  onSelectLevel,
  onRegister,
  onLogin,
  onLogout,
  onClaim,
  onDismissAccountOffer,
}: ResultScreenProps) {
  return (
    <main className="screen result-screen">
      <p className="eyebrow">Результат</p>
      <h1>Рекомендуем начать с: {levelNames[run.recommended_level]}</h1>
      <p className="lead">{run.explanation}</p>
      <p className="result-note">
        Это ориентир по отмеченным словам, а не оценка уровня английского. Вы можете выбрать
        другую сложность.
      </p>
      <label className="field">
        <span>Выбранная сложность</span>
        <select
          value={run.selected_level}
          disabled={busy}
          onChange={(event) => {
            if (isLevel(event.target.value)) onSelectLevel(event.target.value);
          }}
        >
          {Object.entries(levelNames).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <p>Выбрано: {levelNames[run.selected_level]}</p>
      {error === null ? null : (
        <p className="message message-error" role="alert">
          {error}
        </p>
      )}
      {run.saved_to_account && account !== null ? (
        <section className="account-status">
          <p className="message message-success">
            Результат сохранён в аккаунте {account.username}
          </p>
          <button className="text-action" type="button" disabled={busy} onClick={onLogout}>
            Выйти
          </button>
        </section>
      ) : account !== null ? (
        <section className="account-status">
          <p>Вы вошли как {account.username}</p>
          <p>Гостевой результат останется отдельным, пока вы явно его не сохраните.</p>
          <div className="actions">
            <button className="primary-action" type="button" disabled={busy} onClick={onClaim}>
              Сохранить этот результат в аккаунте
            </button>
            <button className="text-action" type="button" disabled={busy} onClick={onLogout}>
              Выйти
            </button>
          </div>
        </section>
      ) : account === null && !accountOfferDismissed ? (
        <section className="account-offer" aria-labelledby="account-offer-title">
          <h2 id="account-offer-title">Сохранить результат?</h2>
          <p>Аккаунт позволит открыть этот результат после нового входа.</p>
          <div className="actions">
            <button className="primary-action" type="button" onClick={onRegister}>
              Сохранить результат
            </button>
            <button className="secondary-action" type="button" onClick={onLogin}>
              Войти
            </button>
            <button className="text-action" type="button" onClick={onDismissAccountOffer}>
              Пока не сейчас
            </button>
          </div>
        </section>
      ) : null}
    </main>
  );
}

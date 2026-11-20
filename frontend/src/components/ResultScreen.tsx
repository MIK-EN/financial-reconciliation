import type { ReactNode } from "react";

import { type AccountContext, type CompletedRun, type Level, isLevel } from "../types";
import { FlowShell } from "./FlowShell";
import { Check, WarningCircle } from "./Icons";

const levels: { value: Level; name: string; description: string }[] = [
  { value: "foundations", name: "Основы", description: "Короткие фразы про файлы и действия." },
  {
    value: "basic_docs",
    name: "Базовая документация",
    description: "Установка, требования, простые инструкции.",
  },
  {
    value: "confident_reading",
    name: "Уверенное чтение",
    description: "Параметры функций и возвращаемые значения.",
  },
  {
    value: "complex_texts",
    name: "Сложные тексты",
    description: "Ограничения, повторы запросов, условия.",
  },
];

const levelNames = Object.fromEntries(levels.map((level) => [level.value, level.name])) as Record<
  Level,
  string
>;

interface ResultScreenProps {
  run: CompletedRun;
  busy: boolean;
  error: string | null;
  account: AccountContext | null;
  accountOfferDismissed: boolean;
  accountForm: ReactNode;
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
  accountForm,
  onSelectLevel,
  onRegister,
  onLogin,
  onLogout,
  onClaim,
  onDismissAccountOffer,
}: ResultScreenProps) {
  return (
    <FlowShell busy={busy}>
      <div className="stack-16">
        <p className="caption-3 muted">Результат</p>
        <h1 className="heading-3 hero-title" style={{ maxWidth: 680 }}>
          Рекомендуем начать с: {levelNames[run.recommended_level]}
        </h1>
        <p className="body-7 muted" style={{ maxWidth: 680 }}>
          {run.explanation}
        </p>
      </div>

      <section className="card stack-16" aria-labelledby="level-title">
        <div className="stack-4">
          <h2 id="level-title" className="heading-6">
            Выбранная сложность
          </h2>
          <p className="body-6 muted">
            Это ориентир по отмеченным словам, а не оценка уровня английского. Вы можете
            выбрать другую сложность.
          </p>
        </div>
        <fieldset className="levels">
          <legend className="visually-hidden">Выбранная сложность</legend>
          {levels.map((level) => (
            <label key={level.value} className="level">
              <input
                type="radio"
                name="level"
                value={level.value}
                checked={run.selected_level === level.value}
                disabled={busy}
                onChange={(event) => {
                  if (isLevel(event.target.value)) onSelectLevel(event.target.value);
                }}
              />
              <span className="level-radio" aria-hidden="true" />
              <span className="stack-4">
                <span
                  className="title-3"
                  style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}
                >
                  {level.name}
                  {level.value === run.recommended_level ? (
                    <span className="badge">Рекомендация</span>
                  ) : null}
                </span>
                <span className="body-6 muted">{level.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
      </section>

      {error === null ? null : (
        <p className="message message-error body-6" role="alert">
          <WarningCircle />
          {error}
        </p>
      )}

      {run.saved_to_account && account !== null ? (
        <section className="message message-success body-6" aria-label="Аккаунт">
          <Check />
          <p style={{ flexGrow: 1 }}>Результат сохранён в аккаунте {account.username}</p>
          <button
            className="btn btn-ghost btn-sm button-sm"
            type="button"
            disabled={busy}
            onClick={onLogout}
          >
            Выйти
          </button>
        </section>
      ) : account !== null ? (
        <section className="card-muted offer" aria-labelledby="claim-title">
          <div className="stack-4" style={{ maxWidth: 440 }}>
            <h2 id="claim-title" className="heading-6">
              Вы вошли как {account.username}
            </h2>
            <p className="body-6 muted">
              Гостевой результат останется отдельным, пока вы явно его не сохраните.
            </p>
          </div>
          <div className="actions">
            <button
              className="btn btn-primary button-md"
              type="button"
              disabled={busy}
              onClick={onClaim}
            >
              Сохранить этот результат в аккаунте
            </button>
            <button
              className="btn btn-ghost button-md"
              type="button"
              disabled={busy}
              onClick={onLogout}
            >
              Выйти
            </button>
          </div>
        </section>
      ) : accountForm !== null ? (
        accountForm
      ) : !accountOfferDismissed ? (
        <section className="card-muted offer" aria-labelledby="account-offer-title">
          <div className="stack-4" style={{ maxWidth: 440 }}>
            <h2 id="account-offer-title" className="heading-6">
              Сохранить результат?
            </h2>
            <p className="body-6 muted">
              Аккаунт позволит открыть рекомендацию после нового входа. Проходить подбор заново
              не придётся.
            </p>
          </div>
          <div className="actions">
            <button className="btn btn-primary button-md" type="button" onClick={onRegister}>
              Сохранить результат
            </button>
            <button className="btn btn-secondary button-md" type="button" onClick={onLogin}>
              Войти
            </button>
            <button className="btn btn-ghost button-md" type="button" onClick={onDismissAccountOffer}>
              Пока не сейчас
            </button>
          </div>
        </section>
      ) : null}
    </FlowShell>
  );
}

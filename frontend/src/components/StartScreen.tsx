interface StartScreenProps {
  busy: boolean;
  error: string | null;
  onStart: () => void;
  onLogin: () => void;
}

export function StartScreen({ busy, error, onStart, onLogin }: StartScreenProps) {
  return (
    <main className="screen start-screen">
      <p className="eyebrow">English for Developers</p>
      <h1>Подберём стартовую сложность</h1>
      <p className="lead">
        Вы увидите от двух до четырёх коротких текстов. Отметьте слова, значение которых
        вам непонятно в этом контексте. Это поможет предложить, с чего начать. Регистрация
        не нужна.
      </p>
      {error === null ? null : (
        <p className="message message-error" role="alert">
          {error}
        </p>
      )}
      <button className="primary-action" type="button" disabled={busy} onClick={onStart}>
        {busy ? "Начинаем…" : "Начать"}
      </button>
      <button className="secondary-action" type="button" disabled={busy} onClick={onLogin}>
        Войти
      </button>
    </main>
  );
}

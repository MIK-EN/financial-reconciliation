import type { ReactNode } from "react";

interface FlowShellProps {
  headerAction?: ReactNode;
  children: ReactNode;
  busy?: boolean;
}

/** Page frame for the onboarding flow: brand header and a centred reading column. */
export function FlowShell({ headerAction, children, busy = false }: FlowShellProps) {
  return (
    <div className="flow">
      <header className="flow-header">
        <span className="brand title-4">
          <span className="brand-mark" aria-hidden="true">
            En
          </span>
          English for Developers
        </span>
        {headerAction}
      </header>
      <main className="flow-main" aria-busy={busy}>
        {children}
      </main>
    </div>
  );
}

export function LoadingScreen() {
  return (
    <FlowShell busy>
      <p className="visually-hidden" role="status">
        Загружаем…
      </p>
      <div className="stack-12" aria-hidden="true">
        <div className="skeleton" style={{ width: 96, height: 16 }} />
        <div className="skeleton" style={{ width: "72%", height: 36 }} />
        <div className="skeleton" style={{ width: "88%", height: 24 }} />
      </div>
      <div className="skeleton" aria-hidden="true" style={{ height: 160, borderRadius: 16 }} />
    </FlowShell>
  );
}

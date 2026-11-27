import { useEffect, useRef, type ReactNode } from "react";
import { describeError } from "../lib/api";

/* ---------------- Badges ---------------- */
export function Badge({ value, className }: { value: string; className?: string }) {
  const normalized = value.toLowerCase().replace(/\s+/g, "-");
  return <span className={`badge ${normalized} ${className ?? ""}`}>{value}</span>;
}

/* ---------------- Layout primitives ---------------- */
export function Card({
  title,
  action,
  children,
  className,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || action) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {action && <div className="card-action">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

/* ---------------- States ---------------- */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="empty-state" role="alert">
      <div className="empty-title">Could not load this view</div>
      <p className="empty-body">{describeError(error)}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {children && <p className="empty-body">{children}</p>}
      {action}
    </div>
  );
}

export function LoadingBlock({ lines = 4 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-live="polite">
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className="skeleton line"
          style={{ width: `${92 - ((index * 13) % 40)}%` }}
        />
      ))}
    </div>
  );
}

export function Notice({
  tone = "warn",
  children,
}: {
  tone?: "warn" | "error" | "info";
  children: ReactNode;
}) {
  return <div className={`notice ${tone === "warn" ? "" : tone}`}>{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

/* ---------------- Modal ---------------- */
export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [onClose]);

  return (
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button ref={closeRef} type="button" className="btn ghost small" onClick={onClose}>
            Close ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  title,
  children,
  confirmLabel = "Confirm",
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div>{children}</div>
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className={`btn ${danger ? "danger" : "primary"}`}
          onClick={onConfirm}
          disabled={busy}
        >
          {busy ? <Spinner /> : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

/* ---------------- Form helpers ---------------- */
export function Field({
  label,
  hint,
  full,
  children,
}: {
  label: string;
  hint?: string;
  full?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`field ${full ? "full" : ""}`}>
      <label>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

/* ---------------- Data table ---------------- */
export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
  hideSmall?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  emptyTitle,
  emptyBody,
  onRetry,
  onRowClick,
  rowClassName,
  selectedKey,
}: {
  columns: Column<T>[];
  rows: T[] | null;
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: unknown;
  emptyTitle: string;
  emptyBody?: ReactNode;
  onRetry?: () => void;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
  selectedKey?: string | null;
}) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (loading && !rows) {
    return (
      <div className="table-wrap">
        <div className="table-loading" aria-busy="true">
          <LoadingBlock lines={5} />
        </div>
      </div>
    );
  }
  if (!rows || rows.length === 0) {
    return <EmptyState title={emptyTitle}>{emptyBody}</EmptyState>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.header}
                className={`${column.numeric ? "num" : ""} ${column.hideSmall ? "hide-small" : ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                className={`${onRowClick ? "clickable" : ""} ${selectedKey === key ? "selected" : ""} ${
                  rowClassName?.(row) ?? ""
                }`}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowClick(row);
                          return;
                        }
                        // Arrow keys move focus between clickable rows so an on-call
                        // responder can triage a queue without touching the mouse.
                        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                          event.preventDefault();
                          const sibling = (
                            event.key === "ArrowDown"
                              ? event.currentTarget.nextElementSibling
                              : event.currentTarget.previousElementSibling
                          ) as HTMLElement | null;
                          sibling?.focus();
                        }
                      }
                    : undefined
                }
              >
                {columns.map((column) => (
                  <td
                    key={column.header}
                    className={`${column.numeric ? "num" : ""} ${column.hideSmall ? "hide-small" : ""}`}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import type { Toast } from "../hooks/useToasts";

/** Fixed toast stack. Announced politely so a screen reader hears write results. */
export function Toasts({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.tone === "error" ? "error" : ""}`}>
          {toast.text}
        </div>
      ))}
    </div>
  );
}

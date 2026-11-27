import { useCallback, useState } from "react";

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "error";
}

/** Minimal toast queue: append, auto-dismiss after 6s, error tone optional. */
export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, text, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 6_000);
  }, []);

  return { toasts, notify };
}

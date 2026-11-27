import { useCallback, useEffect, useRef, useState } from "react";
import type { CursorPage } from "../lib/types";

export interface CursorPages<T> {
  items: T[] | null;
  loading: boolean;
  error: Error | null;
  /** The API returned a cursor for an older page. */
  hasOlder: boolean;
  /** A newer page is already loaded, so the user can step back. */
  hasNewer: boolean;
  pageNumber: number;
  goOlder: () => void;
  goNewer: () => void;
  reload: () => void;
}

interface State<T> {
  index: number;
  cursors: Array<string | null>;
  pages: Record<number, CursorPage<T>>;
}

const INITIAL_STATE: State<never> = { index: 0, cursors: [null], pages: {} };

/**
 * Keyset pagination over a `CursorPage` endpoint.
 *
 * The API only hands out forward (older) cursors, so visited pages are cached by index:
 * stepping back is instant and never re-queries. Callers that change filters must remount
 * the consuming component (or call `reload`) — a stale cursor is never reused across filters.
 */
export function useCursorPage<T>(
  load: (cursor: string | null, signal: AbortSignal) => Promise<CursorPage<T>>,
): CursorPages<T> {
  const [state, setState] = useState<State<T>>(() => ({ ...INITIAL_STATE, pages: {} }));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const cursor = state.cursors[state.index];
  const page = state.pages[state.index];

  useEffect(() => {
    if (page) {
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    loadRef
      .current(cursor, controller.signal)
      .then((result) => {
        if (!active) return;
        setState((previous) => ({
          ...previous,
          pages: { ...previous.pages, [previous.index]: result },
        }));
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (!active || (cause as Error)?.name === "AbortError") return;
        setError(cause as Error);
        setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [cursor, page, nonce]);

  const goOlder = useCallback(() => {
    setState((previous) => {
      const current = previous.pages[previous.index];
      if (!current?.next_cursor) return previous;
      const cursors = previous.cursors.slice();
      cursors[previous.index + 1] = current.next_cursor;
      return { ...previous, index: previous.index + 1, cursors };
    });
  }, []);

  const goNewer = useCallback(() => {
    setState((previous) =>
      previous.index === 0 ? previous : { ...previous, index: previous.index - 1 },
    );
  }, []);

  const reload = useCallback(() => {
    setState({ index: 0, cursors: [null], pages: {} });
    setNonce((value) => value + 1);
  }, []);

  return {
    items: page?.items ?? null,
    loading,
    error,
    hasOlder: Boolean(page?.next_cursor),
    hasNewer: state.index > 0,
    pageNumber: state.index + 1,
    goOlder,
    goNewer,
    reload,
  };
}

import { useEffect, useRef, useState } from 'react';

export type AsyncState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'error'; error: string };

/** Fire an async fetch on mount (or when deps change). */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading' });
  const counter = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const id = ++counter.current;
    setState({ status: 'loading' });
    fn()
      .then(data => {
        if (!cancelled && id === counter.current)
          setState({ status: 'ok', data });
      })
      .catch((err: unknown) => {
        if (!cancelled && id === counter.current)
          setState({ status: 'error', error: String(err) });
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}

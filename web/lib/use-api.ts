"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  /** true while refetching with previous data still shown */
  refreshing: boolean;
  reload: () => void;
}

/**
 * Fetch data on mount and whenever `deps` change; optionally poll.
 * Previous data is kept while refetching (no skeleton flash on refresh).
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  options: { pollMs?: number | ((data: T | undefined) => number | undefined) } = {},
): ApiState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });
  const dataRef = useRef<T | undefined>(undefined);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      setRefreshing(dataRef.current !== undefined);
      try {
        const result = await fetcherRef.current();
        if (cancelled) return;
        dataRef.current = result;
        setData(result);
        setError(undefined);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
          const poll =
            typeof options.pollMs === "function" ? options.pollMs(dataRef.current) : options.pollMs;
          if (poll) timer = setTimeout(run, poll);
        }
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, refreshing, reload };
}

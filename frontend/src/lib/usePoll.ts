import { useEffect, useRef } from "react";

/** Calls `fn` now and then every `ms` while `active`; never overlaps two calls. */
export function usePoll(fn: () => Promise<void>, ms: number, active: boolean, deps: unknown[] = []) {
  const saved = useRef(fn);
  saved.current = fn;

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        await saved.current();
      } finally {
        if (!stopped && active) timer = setTimeout(tick, ms);
      }
    };
    tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, active, ...deps]);
}

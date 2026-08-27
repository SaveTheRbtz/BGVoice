import { useEffect, useState } from "react";

import { errorMessage } from "./use-browser";

export function useResource<Item>(
  name: string,
  load: (name: string, signal?: AbortSignal) => Promise<Item>,
) {
  const [state, setState] = useState<{
    name: string;
    value?: Item;
    error?: string;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    load(name, controller.signal)
      .then((value) => setState({ name, value }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setState({ name, error: errorMessage(reason) });
      });
    return () => controller.abort();
  }, [load, name]);
  return state?.name === name
    ? { value: state.value ?? null, error: state.error ?? null }
    : { value: null, error: null };
}

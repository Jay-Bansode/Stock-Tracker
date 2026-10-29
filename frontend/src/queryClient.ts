import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { priceStore } from "./prices";

export const ME_KEY = ["me"] as const;

/**
 * Drop everything cached for the signed-in user and re-check the session. The "me" query is
 * reset (not just invalidated) so the app falls back to its loading state and then, on the
 * resulting 401, to the login page.
 */
export function resetSession(qc: QueryClient) {
  priceStore.disconnect();
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] });
  return qc.resetQueries({ queryKey: ME_KEY });
}

export function makeQueryClient(): QueryClient {
  // Any 401 while we think we're signed in means the session expired or was revoked.
  const onError = (err: unknown) => {
    if (err instanceof ApiError && err.status === 401 && qc.getQueryData(ME_KEY)) {
      void resetSession(qc);
    }
  };
  const qc: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
        refetchOnWindowFocus: true,
      },
    },
  });
  return qc;
}

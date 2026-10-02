import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiError } from "./api/client";
import { App } from "./App";
import { AuthProvider, UNAUTHORIZED_EVENT } from "./hooks/useAuth";
import { uploads } from "./services/uploader";
import { initTelegram } from "./telegram";

initTelegram();

const onError = (err: unknown) => {
  if (err instanceof ApiError && err.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
};

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});

uploads.onAssetsChanged = (projectId) => {
  void queryClient.invalidateQueries({ queryKey: ["assets", projectId] });
  void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  void queryClient.invalidateQueries({ queryKey: ["projects"] });
  void queryClient.invalidateQueries({ queryKey: ["me"] });
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);

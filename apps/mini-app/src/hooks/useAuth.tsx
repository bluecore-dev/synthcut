import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, api, clearToken, currentToken, setToken, tokenExpiresAt, unwrap } from "../api/client";
import { tg } from "../telegram";

export type AuthState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "outside-telegram" }
  | { status: "denied"; telegramId?: number }
  | { status: "error"; message: string };

const AuthContext = createContext<AuthState>({ status: "loading" });

export const UNAUTHORIZED_EVENT = "synthcut:unauthorized";

async function exchangeInitData(): Promise<void> {
  const res = await unwrap(api.POST("/api/v1/auth/telegram", { body: { init_data: tg!.initData } }));
  setToken(res.access_token, res.expires_at);
}

function describe(err: unknown): AuthState {
  if (err instanceof ApiError) {
    if (err.code === "not_authorized") {
      const id = (err.details as { telegram_id?: number } | undefined)?.telegram_id;
      return { status: "denied", telegramId: id };
    }
    if (err.code === "invalid_init_data") {
      return { status: "error", message: "Sessiya eskirgan — Mini App'ni yopib, qayta oching." };
    }
    return { status: "error", message: err.message };
  }
  return { status: "error", message: "Server bilan bog'lanib bo'lmadi" };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() => (tg ? { status: "loading" } : { status: "outside-telegram" }));

  useEffect(() => {
    if (!tg) return;
    let cancelled = false;

    const login = async () => {
      try {
        if (!currentToken() || tokenExpiresAt() - Date.now() < 5 * 60_000) await exchangeInitData();
        if (!cancelled) setState({ status: "ready" });
      } catch (err) {
        if (!cancelled) setState(describe(err));
      }
    };
    void login();

    // Sliding session: long uploads outlive a single token.
    const refresher = setInterval(async () => {
      if (!currentToken() || tokenExpiresAt() - Date.now() > 60 * 60_000) return;
      try {
        const res = await unwrap(api.POST("/api/v1/auth/refresh"));
        setToken(res.access_token, res.expires_at);
      } catch {
        /* the unauthorized handler below takes over if it really expired */
      }
    }, 5 * 60_000);

    const onUnauthorized = async () => {
      clearToken();
      try {
        await exchangeInitData();
        if (!cancelled) setState({ status: "ready" });
      } catch (err) {
        if (!cancelled) setState(describe(err));
      }
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      cancelled = true;
      clearInterval(refresher);
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

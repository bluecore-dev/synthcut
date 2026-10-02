import { Lock, Send, TriangleAlert } from "lucide-react";
import { Button } from "../components/ui";
import { Wordmark } from "../components/Wordmark";
import type { AuthState } from "../hooks/useAuth";
import { BOT_USERNAME } from "../telegram";

export function Gate({ state }: { state: Exclude<AuthState, { status: "ready" } | { status: "loading" }> }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col px-6 pb-10 pt-8">
      <Wordmark />
      <div className="flex flex-1 flex-col items-center justify-center text-center">
        {state.status === "outside-telegram" && (
          <>
            <div className="mb-5 grid size-16 place-items-center rounded-2xl border border-line bg-s1 text-accent">
              <Send className="size-7" aria-hidden />
            </div>
            <h1 className="text-lg font-bold">Telegram orqali oching</h1>
            <p className="mt-2 text-sm text-dim">
              SynthCut Telegram Mini App sifatida ishlaydi. Kirish Telegram imzosi bilan serverda tekshiriladi.
            </p>
            <a
              href={`https://t.me/${BOT_USERNAME}`}
              className="mt-6 inline-flex h-12 items-center rounded-xl bg-brand px-5 text-[15px] font-semibold text-white"
            >
              @{BOT_USERNAME}
            </a>
          </>
        )}
        {state.status === "denied" && (
          <>
            <div className="mb-5 grid size-16 place-items-center rounded-2xl border border-line bg-s1 text-warn">
              <Lock className="size-7" aria-hidden />
            </div>
            <h1 className="text-lg font-bold">Bu xususiy tizim</h1>
            <p className="mt-2 text-sm text-dim">Kirish faqat ruxsat ro'yxatidagi Telegram hisoblari uchun.</p>
            {state.telegramId && (
              <p className="mt-4 rounded-xl border border-line bg-s1 px-4 py-2 font-mono text-sm text-fg">
                Telegram ID: {state.telegramId}
              </p>
            )}
          </>
        )}
        {state.status === "error" && (
          <>
            <div className="mb-5 grid size-16 place-items-center rounded-2xl border border-line bg-s1 text-err">
              <TriangleAlert className="size-7" aria-hidden />
            </div>
            <h1 className="text-lg font-bold">Ulanib bo'lmadi</h1>
            <p className="mt-2 text-sm text-dim">{state.message}</p>
            <Button className="mt-6" onClick={() => window.location.reload()}>
              Qayta urinish
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

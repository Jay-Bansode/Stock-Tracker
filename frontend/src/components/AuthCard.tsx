import { useQueryClient } from "@tanstack/react-query";
import type { FormEvent, InputHTMLAttributes, ReactNode } from "react";
import type { Me } from "../types";
import { priceStore } from "../prices";
import { ME_KEY } from "../queryClient";

/** Centered card with the logo, shared by the signed-out pages. */
export function AuthCard({ title, subtitle, onSubmit, children, footer }: {
  title: string;
  subtitle?: string;
  onSubmit: (e: FormEvent) => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="grid min-h-screen place-items-center px-4 py-8">
      <div className="w-full max-w-sm space-y-3">
        <form onSubmit={onSubmit} className="card space-y-4 p-6">
          <div className="flex items-center gap-2">
            <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
              <rect width="32" height="32" rx="7" className="fill-teal-700" />
              <path d="M7 21l6-6 4 4 8-9" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div>
              <h1 className="font-semibold">{title}</h1>
              <p className="text-xs text-slate-500">{subtitle ?? "Watchlists & price alerts"}</p>
            </div>
          </div>
          {children}
        </form>
        {footer && <div className="text-center text-sm text-slate-500">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, ...input }: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <input className="input" {...input} />
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

/** After any endpoint that sets the session cookie: show the app as this user. */
export function useSignedIn() {
  const qc = useQueryClient();
  return (me: Me) => {
    qc.setQueryData(ME_KEY, me);
    priceStore.reconnect();
  };
}

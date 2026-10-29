import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { priceStore } from "../prices";

export default function LoginPage() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(username, password),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["me"] });
      priceStore.reconnect();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-6">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
            <rect width="32" height="32" rx="7" className="fill-teal-700" />
            <path d="M7 21l6-6 4 4 8-9" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <h1 className="font-semibold">Tracker</h1>
            <p className="text-xs text-slate-500">Watchlists &amp; price alerts</p>
          </div>
        </div>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Username</span>
          <input className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Password</span>
          <input className="input" type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {login.error && <p className="text-sm text-red-600">{login.error.message}</p>}
        <button className="btn btn-primary w-full" disabled={login.isPending || !password}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

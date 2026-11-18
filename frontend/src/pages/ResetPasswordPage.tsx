import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api } from "../api";
import { AuthCard, Field, useSignedIn } from "../components/AuthCard";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const signedIn = useSignedIn();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const reset = useMutation({
    mutationFn: () => api.resetPassword(token, password),
    onSuccess: (me) => {
      navigate("/watchlists", { replace: true }); // drop the token from the address bar
      signedIn(me);
    },
  });
  const mismatch = confirm !== "" && confirm !== password;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) reset.mutate();
  };

  const footer = (
    <Link to="/forgot-password" className="font-medium text-teal-700 hover:underline dark:text-teal-400">
      Request a new link
    </Link>
  );

  if (!token) {
    return (
      <AuthCard title="Reset your password" onSubmit={(e) => e.preventDefault()} footer={footer}>
        <p className="text-sm">This link is incomplete. Open the link from the email again, or request a new one.</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Choose a new password" subtitle="You'll be signed out on other devices" onSubmit={submit} footer={footer}>
      <Field label="New password" type="password" autoComplete="new-password" autoFocus minLength={8} maxLength={72} hint="At least 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} />
      <Field label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      {mismatch && <p className="text-sm text-red-600">Passwords don't match</p>}
      {reset.error && <p className="text-sm text-red-600">{reset.error.message}</p>}
      <button className="btn btn-primary w-full" disabled={reset.isPending || password.length < 8 || confirm !== password}>
        {reset.isPending ? "Saving…" : "Set new password"}
      </button>
    </AuthCard>
  );
}

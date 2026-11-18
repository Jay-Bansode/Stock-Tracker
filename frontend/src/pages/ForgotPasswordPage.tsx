import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { AuthCard, Field } from "../components/AuthCard";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const forgot = useMutation({ mutationFn: () => api.forgotPassword(email.trim()) });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    forgot.mutate();
  };

  const back = (
    <Link to="/login" className="font-medium text-teal-700 hover:underline dark:text-teal-400">
      Back to sign in
    </Link>
  );

  return (
    <AuthCard title="Reset your password" subtitle="We'll email you a link" onSubmit={submit} footer={back}>
      {forgot.isSuccess ? (
        <p className="text-sm" role="status">
          If <span className="font-medium">{email.trim()}</span> has an account, a reset link is on its way. It's valid for 30 minutes. Check your spam folder too.
        </p>
      ) : (
        <>
          <Field label="Email" type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
          {forgot.error && <p className="text-sm text-red-600">{forgot.error.message}</p>}
          <button className="btn btn-primary w-full" disabled={forgot.isPending || !email}>
            {forgot.isPending ? "Sending…" : "Send reset link"}
          </button>
        </>
      )}
    </AuthCard>
  );
}

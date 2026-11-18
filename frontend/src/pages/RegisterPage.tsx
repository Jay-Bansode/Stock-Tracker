import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { AuthCard, Field, useSignedIn } from "../components/AuthCard";

export default function RegisterPage() {
  const signedIn = useSignedIn();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const register = useMutation({ mutationFn: () => api.register(username.trim(), email.trim(), password), onSuccess: signedIn });
  const mismatch = confirm !== "" && confirm !== password;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) register.mutate();
  };

  return (
    <AuthCard
      title="Create your account"
      subtitle="Your own watchlists and alerts"
      onSubmit={submit}
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-teal-700 hover:underline dark:text-teal-400">
            Sign in
          </Link>
        </>
      }
    >
      <Field label="Username" autoComplete="username" autoFocus minLength={3} maxLength={32} pattern="[A-Za-z0-9_.\-]+" hint="3–32 letters, numbers, . _ or -" value={username} onChange={(e) => setUsername(e.target.value)} />
      <Field label="Email" type="email" autoComplete="email" hint="Used only to reset your password" value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="new-password" minLength={8} maxLength={72} hint="At least 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} />
      <Field label="Confirm password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      {mismatch && <p className="text-sm text-red-600">Passwords don't match</p>}
      {register.error && <p className="text-sm text-red-600">{register.error.message}</p>}
      <button className="btn btn-primary w-full" disabled={register.isPending || !username || !email || password.length < 8 || confirm !== password}>
        {register.isPending ? "Creating account…" : "Create account"}
      </button>
    </AuthCard>
  );
}

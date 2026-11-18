import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { AuthCard, Field, useSignedIn } from "../components/AuthCard";

export default function LoginPage() {
  const signedIn = useSignedIn();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({ mutationFn: () => api.login(username, password), onSuccess: signedIn });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <AuthCard
      title="Tracker"
      onSubmit={submit}
      footer={
        <>
          New here?{" "}
          <Link to="/register" className="font-medium text-teal-700 hover:underline dark:text-teal-400">
            Create an account
          </Link>
        </>
      }
    >
      <Field label="Username or email" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
      <div>
        <Field label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <Link to="/forgot-password" className="mt-1 inline-block text-xs text-teal-700 hover:underline dark:text-teal-400">
          Forgot password?
        </Link>
      </div>
      {login.error && <p className="text-sm text-red-600">{login.error.message}</p>}
      <button className="btn btn-primary w-full" disabled={login.isPending || !username || !password}>
        {login.isPending ? "Signing in…" : "Sign in"}
      </button>
    </AuthCard>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { api } from "./api";
import { ME_KEY } from "./queryClient";
import Layout from "./components/Layout";
import AlertsPage from "./pages/AlertsPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import SettingsPage from "./pages/SettingsPage";
import WatchlistsPage from "./pages/WatchlistsPage";

const Loading = () => <div className="grid h-screen place-items-center text-sm text-slate-500">Loading…</div>;

/** /login while signed in: go to the app, unless this is the sign-out on its way. */
function SignedInLogin() {
  const state = useLocation().state as { signingOut?: boolean } | null;
  return state?.signingOut ? <Loading /> : <Navigate to="/watchlists" replace />;
}

export default function App() {
  const me = useQuery({ queryKey: ME_KEY, queryFn: api.me, retry: false, staleTime: Infinity });
  const location = useLocation();
  const navigate = useNavigate();
  const signingOut = (location.state as { signingOut?: boolean } | null)?.signingOut;
  useEffect(() => {
    // Sign-out finished: drop the marker so signing in again from /login opens the app.
    if (me.isError && signingOut) navigate(location.pathname, { replace: true });
  }, [me.isError, signingOut, location.pathname, navigate]);

  if (me.isPending) return <Loading />;
  if (me.isError) {
    // Any other path shows the login form in place, so signing in lands back on that page.
    return (
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <Layout username={me.data.username}>
      <Routes>
        <Route path="/" element={<Navigate to="/watchlists" replace />} />
        <Route path="/watchlists" element={<WatchlistsPage />} />
        <Route path="/watchlists/:id" element={<WatchlistsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/login" element={<SignedInLogin />} />
        <Route path="*" element={<Navigate to="/watchlists" replace />} />
      </Routes>
    </Layout>
  );
}

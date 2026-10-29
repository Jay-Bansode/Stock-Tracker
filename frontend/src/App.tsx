import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router";
import { api } from "./api";
import Layout from "./components/Layout";
import AlertsPage from "./pages/AlertsPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";
import WatchlistsPage from "./pages/WatchlistsPage";

export default function App() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false, staleTime: Infinity });

  if (me.isPending) {
    return <div className="grid h-screen place-items-center text-sm text-slate-500">Loading…</div>;
  }
  if (me.isError) return <LoginPage />;

  return (
    <Layout username={me.data.username}>
      <Routes>
        <Route path="/" element={<Navigate to="/watchlists" replace />} />
        <Route path="/watchlists" element={<WatchlistsPage />} />
        <Route path="/watchlists/:id" element={<WatchlistsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/watchlists" replace />} />
      </Routes>
    </Layout>
  );
}

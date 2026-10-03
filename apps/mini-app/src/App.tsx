import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router";
import { Spinner } from "./components/ui";
import { useAuth } from "./hooks/useAuth";
import { AssetPage } from "./pages/Asset";
import { Gate } from "./pages/Gate";
import { Home } from "./pages/Home";
import { NewProject } from "./pages/NewProject";
import { Project } from "./pages/Project";
import { launchProjectId } from "./telegram";

function DeepLink() {
  const navigate = useNavigate();
  useEffect(() => {
    const id = launchProjectId();
    if (id) navigate(`/p/${id}`, { replace: false });
  }, [navigate]);
  return null;
}

export function App() {
  const auth = useAuth();
  if (auth.status === "loading") {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Spinner className="size-6" />
      </div>
    );
  }
  if (auth.status !== "ready") return <Gate state={auth} />;
  return (
    <BrowserRouter>
      <DeepLink />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/p/:id" element={<Project />} />
        <Route path="/p/:id/a/:assetId" element={<AssetPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

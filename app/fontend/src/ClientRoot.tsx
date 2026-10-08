import { lazy, Suspense, useEffect, useState } from "react";
import { LandingPage } from "./components/LandingPage";
import { PageBoundary, PageLoading } from "./components/PageBoundary";
import { apiEnabled, getSession, type AuthUser } from "./services/auth";

const loadWorkspace = () => import("./App");
const Workspace = lazy(() => loadWorkspace().then((module) => ({ default: module.App })));
let sessionRequest: Promise<AuthUser | null> | undefined;

export function ClientRoot() {
  const [checked, setChecked] = useState(!apiEnabled());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!apiEnabled()) return;
    let mounted = true;
    // Overlap account verification and workspace loading for bookmarked internal pages.
    if (["#catalogue", "#quotation", "#orders", "#admin", "#super-admin"].includes(window.location.hash)) {
      void loadWorkspace().catch(() => undefined);
    }
    sessionRequest ??= getSession();
    sessionRequest.then((account) => {
      if (!mounted) return;
      setUser(account);
      if (!account) window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }).catch((caught) => {
      if (mounted) setError(caught instanceof Error ? caught.message : "We could not connect to the account service.");
    }).finally(() => {
      if (mounted) setChecked(true);
    });
    return () => { mounted = false; };
  }, []);

  if (!checked) return <PageLoading />;
  if (!user) return <div className="app-shell">
    <LandingPage onLoginSuccess={(account) => {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#catalogue`);
      setError("");
      setUser(account);
    }} />
    {error && <div className="toast" role="alert">{error}</div>}
  </div>;
  return <PageBoundary><Suspense fallback={<PageLoading />}>
    <Workspace initialUser={user} />
  </Suspense></PageBoundary>;
}

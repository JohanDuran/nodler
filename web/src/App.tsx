import { useEffect, useState } from "react";
import { api } from "./api";
import type { SetupStatus } from "./types";
import Dashboard from "./pages/Dashboard";
import WorkflowEditor from "./pages/WorkflowEditor";
import Agents from "./pages/Agents";
import Projects from "./pages/Projects";
import Runs from "./pages/Runs";
import Setup from "./pages/Setup";

const PAGES = {
  dashboard: { label: "Dashboard", el: Dashboard },
  workflows: { label: "Workflows", el: WorkflowEditor },
  agents: { label: "Agents", el: Agents },
  projects: { label: "Projects", el: Projects },
  runs: { label: "Runs", el: Runs },
  setup: { label: "Setup", el: Setup },
} as const;
type Page = keyof typeof PAGES;

function currentPage(): Page {
  const h = window.location.hash.replace("#", "") as Page;
  return h in PAGES ? h : "dashboard";
}

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // First visit with something missing (no login, no project): start on the setup page.
  useEffect(() => {
    api.get<SetupStatus>("/setup").then((s) => {
      const missing = !s.ready || s.projects === 0;
      setNeedsSetup(missing);
      if (missing && !window.location.hash) window.location.hash = "setup";
    }).catch(() => {});
  }, [page === "setup"]); // re-check when leaving/entering setup

  const Page = PAGES[page].el;
  return (
    <div className="app">
      <header className="top">
        <div className="brand">nod<span>ler</span></div>
        <nav>
          {(Object.keys(PAGES) as Page[]).map((p) => (
            <button key={p} className={p === page ? "active" : ""} onClick={() => (window.location.hash = p)}>
              {PAGES[p].label}{p === "setup" && needsSetup && <span className="dot" title="Something needs your attention" />}
            </button>
          ))}
        </nav>
      </header>
      <main>
        <Page />
      </main>
    </div>
  );
}

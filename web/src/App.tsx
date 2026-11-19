import { useEffect, useState } from "react";
import Dashboard from "./pages/Dashboard";
import WorkflowEditor from "./pages/WorkflowEditor";
import Agents from "./pages/Agents";
import Projects from "./pages/Projects";
import Runs from "./pages/Runs";

const PAGES = {
  dashboard: { label: "Dashboard", el: Dashboard },
  workflows: { label: "Workflows", el: WorkflowEditor },
  agents: { label: "Agents", el: Agents },
  projects: { label: "Projects", el: Projects },
  runs: { label: "Runs", el: Runs },
} as const;
type Page = keyof typeof PAGES;

function currentPage(): Page {
  const h = window.location.hash.replace("#", "") as Page;
  return h in PAGES ? h : "dashboard";
}

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const Page = PAGES[page].el;
  return (
    <div className="app">
      <header className="top">
        <div className="brand">nod<span>ler</span></div>
        <nav>
          {(Object.keys(PAGES) as Page[]).map((p) => (
            <button key={p} className={p === page ? "active" : ""} onClick={() => (window.location.hash = p)}>
              {PAGES[p].label}
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

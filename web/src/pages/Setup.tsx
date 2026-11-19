import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { InstallHint, LoginSession, Project, RepoInfo, SetupStatus } from "../types";

const active = (s: LoginSession | null | undefined) => !!s && (s.state === "starting" || s.state === "waiting");

export default function Setup() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [checking, setChecking] = useState(false);

  const refresh = useCallback(async () => {
    setChecking(true);
    try { setStatus(await api.get<SetupStatus>("/setup")); } finally { setChecking(false); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  if (!status) return <p className="muted">Checking your computer…</p>;
  const claudeOk = status.claude.logged_in;
  const githubOk = status.github.logged_in && !status.github.missing_scopes?.length;
  const gitOk = status.git.installed;

  return (
    <div className="setup">
      <div className="row between">
        <div>
          <h1>Set up nodler</h1>
          <p className="muted">Connect your accounts once. nodler opens the official sign-in pages; it never sees your passwords.</p>
        </div>
        <button onClick={refresh} disabled={checking}>{checking ? "Checking…" : "Check again"}</button>
      </div>

      <Step n={1} done={claudeOk} title="Connect Claude"
        subtitle={claudeOk ? `Connected${status.claude.email ? ` as ${status.claude.email}` : ""}${status.claude.plan ? ` · ${status.claude.plan} plan` : ""}` : "The agents run on your Claude subscription."}>
        {!claudeOk && <LoginFlow provider="claude" initial={status.logins.claude} onDone={refresh} />}
      </Step>

      <Step n={2} done={githubOk} title="Connect GitHub"
        subtitle={githubOk ? `Connected as ${status.github.account}` : "nodler reads your project boards and opens pull requests."}>
        {!status.github.installed ? (
          <Install name="GitHub CLI" hint={status.github.install} onCheck={refresh} />
        ) : !githubOk && (
          <>
            {status.github.logged_in && (
              <p className="muted">You're signed in as <b>{status.github.account}</b>, but nodler needs one more permission
                ({status.github.missing_scopes?.join(", ")}). Approve it once:</p>
            )}
            <LoginFlow provider="github" initial={status.logins.github} onDone={refresh} />
          </>
        )}
      </Step>

      <Step n={3} done={gitOk} title="Git" subtitle={gitOk ? status.git.version ?? "Installed" : "Needed to work on your code."}>
        {!gitOk && <Install name="Git" hint={status.git.install} onCheck={refresh} />}
      </Step>

      <Step n={4} done={status.projects > 0} title="Add your first project"
        subtitle={status.projects > 0 ? `${status.projects} project(s) set up` : "Pick a repository; nodler prepares everything else."}
        locked={!(claudeOk && githubOk && gitOk)}>
        {claudeOk && githubOk && gitOk && <QuickProject onDone={refresh} hasProjects={status.projects > 0} />}
      </Step>

      {status.ready && status.projects > 0 && (
        <div className="card">
          <h2>You're ready</h2>
          <ol className="muted" style={{ margin: 0, paddingLeft: 18 }}>
            <li>Create an issue in your repository describing the change (what to do, and when it's done).</li>
            <li>On your project board, move it to <b>Ready</b>.</li>
            <li>On the <a href="#dashboard">Dashboard</a>, press <b>Resume</b> and watch the agents work.</li>
          </ol>
        </div>
      )}
    </div>
  );
}

function Step({ n, done, title, subtitle, locked, children }: {
  n: number; done: boolean; title: string; subtitle: string; locked?: boolean; children?: React.ReactNode;
}) {
  return (
    <div className={`card step ${done ? "done" : ""} ${locked ? "locked" : ""}`}>
      <div className="step-head">
        <div className="step-n">{done ? "✓" : n}</div>
        <div><h2 style={{ margin: 0 }}>{title}</h2><div className="muted">{subtitle}</div></div>
      </div>
      {children && <div className="step-body">{children}</div>}
    </div>
  );
}

function LoginFlow({ provider, initial, onDone }: { provider: "claude" | "github"; initial: LoginSession | null; onDone: () => void }) {
  const [session, setSession] = useState<LoginSession | null>(active(initial) ? initial : null);
  const [error, setError] = useState<string | null>(null);
  const [paste, setPaste] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!active(session)) return;
    const id = setInterval(async () => {
      const s = await api.get<LoginSession | null>(`/setup/login/${provider}`);
      setSession(s);
      if (s && !active(s)) onDone();
    }, 1500);
    return () => clearInterval(id);
  }, [session?.id, session?.state, provider, onDone]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setError(null);
    try { setSession(await api.post<LoginSession>(`/setup/login/${provider}`)); }
    catch (e) { setError(errorText(e)); }
  };
  const cancel = async () => setSession(await api.post<LoginSession>(`/setup/login/${provider}/cancel`));
  const sendCode = async () => { setSession(await api.post<LoginSession>(`/setup/login/${provider}/input`, { text: paste })); setPaste(""); };
  const copyAndOpen = async () => {
    if (session?.code) { try { await navigator.clipboard.writeText(session.code); setCopied(true); } catch { /* ignore */ } }
    if (session?.url) window.open(session.url, "_blank", "noopener");
  };

  const label = provider === "claude" ? "Connect Claude" : "Connect GitHub";
  if (!session || !active(session)) {
    return (
      <>
        {session?.state === "failed" && <div className="notice err">The sign-in didn't finish{session.message ? `: ${session.message}` : ""}. Try again.</div>}
        {session?.state === "cancelled" && <div className="notice warn">Sign-in cancelled.</div>}
        {error && <div className="notice err">{error}</div>}
        <button className="primary big" onClick={start}>{label}</button>
      </>
    );
  }

  if (provider === "github") {
    return (
      <div className="login-box">
        {!session.code ? <p className="muted">Starting…</p> : (
          <>
            <p>1. Copy this code:</p>
            <div className="device-code">{session.code}</div>
            <p>2. Open GitHub, paste the code, and approve <b>GitHub CLI</b>.</p>
            <div className="row">
              <button className="primary big" onClick={copyAndOpen}>{copied ? "Code copied · Open GitHub again" : "Copy code & open GitHub"}</button>
              <button onClick={cancel}>Cancel</button>
            </div>
            <p className="muted waiting">Waiting for you to approve on GitHub…</p>
          </>
        )}
      </div>
    );
  }

  const asksForCode = session.output.some((l) => /paste|code/i.test(l));
  return (
    <div className="login-box">
      <p>A browser window should open to sign in to Claude. Sign in and approve access.</p>
      <div className="row">
        {session.url && <a className="btn primary" href={session.url} target="_blank" rel="noopener">Open the sign-in page</a>}
        <button onClick={cancel}>Cancel</button>
      </div>
      {asksForCode && (
        <div className="row" style={{ marginTop: 10 }}>
          <input placeholder="If the page shows a code, paste it here" value={paste} onChange={(e) => setPaste(e.target.value)} style={{ flex: 1 }} />
          <button onClick={sendCode} disabled={!paste.trim()}>Send code</button>
        </div>
      )}
      <p className="muted waiting">Waiting for you to finish signing in…</p>
    </div>
  );
}

function Install({ name, hint, onCheck }: { name: string; hint?: InstallHint; onCheck: () => void }) {
  return (
    <div className="login-box">
      <p>{name} isn't installed on this computer.</p>
      {hint && (
        <>
          <p className="muted">On Windows, open PowerShell and run:</p>
          <div className="row"><code className="cmd">{hint.windows}</code>
            <button className="small" onClick={() => navigator.clipboard.writeText(hint.windows)}>Copy</button></div>
          <p className="muted">Or download it from <a href={hint.url} target="_blank" rel="noopener">{hint.url}</a>. Then restart nodler.</p>
        </>
      )}
      <button onClick={onCheck}>I installed it, check again</button>
    </div>
  );
}

function QuickProject({ onDone, hasProjects }: { onDone: () => void; hasProjects: boolean }) {
  const [repos, setRepos] = useState<RepoInfo[] | null>(null);
  const [filter, setFilter] = useState("");
  const [repo, setRepo] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ project: Project; board_url: string | null } | null>(null);

  useEffect(() => {
    api.get<RepoInfo[]>("/github/repos").then(setRepos).catch((e) => {
      const text = errorText(e);
      setError(/rate limit/i.test(text)
        ? "GitHub's hourly API limit is used up, so your repositories can't be listed right now. Type the repository below, or try again later."
        : text);
      setRepos([]);
    });
  }, []);

  const add = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.post<{ project: Project; board_url: string | null }>("/projects/quick", { repo, local_path: localPath });
      setResult(r); onDone();
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };

  if (result) {
    const p = result.project;
    return (
      <div className="login-box">
        <p className="ok"><b>{p.name}</b> is ready.</p>
        <ul className="muted" style={{ marginTop: 0 }}>
          <li>Code: <span className="mono">{p.local_path}</span></li>
          <li>Prepare command: <span className="mono">{p.setup_command || "none"}</span></li>
          <li>Test command: <span className="mono">{p.test_command || "none found: set one on the Projects page"}</span></li>
        </ul>
        <div className="row">
          {result.board_url && <a className="btn primary" href={result.board_url} target="_blank" rel="noopener">Open the project board</a>}
          <a className="btn" href="#projects">Review project settings</a>
        </div>
      </div>
    );
  }

  const shown = (repos ?? []).filter((r) => r.repo.toLowerCase().includes(filter.toLowerCase())).slice(0, 50);
  return (
    <div className="login-box">
      {hasProjects && <p className="muted">Add another project:</p>}
      {error && <div className="notice err">{error}</div>}
      {repos === null ? <p className="muted">Loading your repositories…</p> : (
        <>
          <input placeholder="Search your repositories" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div className="repo-list">
            {shown.map((r) => (
              <button key={r.repo} className={r.repo === repo ? "active" : ""} onClick={() => setRepo(r.repo)}>
                <b>{r.repo}</b> {r.private && <span className="badge">private</span>}
                {r.description && <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>}
              </button>
            ))}
            {shown.length === 0 && repos.length > 0 && <p className="muted">No repositories match.</p>}
          </div>
          {repos.length === 0 && (
            <label className="field" style={{ marginTop: 10 }}>Repository (owner/name)
              <input className="mono" placeholder="octocat/my-app" value={repo} onChange={(e) => setRepo(e.target.value.trim())} />
            </label>
          )}
          <label className="field" style={{ marginTop: 10 }}>Already on this computer? Folder path (optional; otherwise nodler downloads it)
            <input className="mono" value={localPath} onChange={(e) => setLocalPath(e.target.value)} placeholder="C:\Users\you\Projects\my-app" />
          </label>
          <p className="muted" style={{ fontSize: 12 }}>nodler will download the code if needed, detect how to install and test it, and create a GitHub project board with the right columns.</p>
          <button className="primary big" onClick={add} disabled={!repo || busy}>{busy ? "Setting up…" : repo ? `Add ${repo}` : "Pick a repository"}</button>
        </>
      )}
    </div>
  );
}

import { useState } from "react";
import { BASE, getToken, setToken } from "../api.js";

// JWT paste-and-save. The Worker (api.example.com) issues the token via
// the operator login; this card unblocks any operator who lands on
// the SPA without a token already in localStorage.
export default function SignInRequired({ compact = false }) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const hasToken = !!getToken();

  function save() {
    if (!val.trim()) return;
    setBusy(true);
    setToken(val.trim());
    // Reload so all in-flight components retry with the new bearer.
    window.location.reload();
  }

  function clearTok() {
    setToken("");
    window.location.reload();
  }

  return (
    <section className={`card border-gold/30 ${compact ? "" : ""}`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gold">
          Operator sign-in required
        </h2>
        <span className="font-mono text-[10px] text-zinc-500">{BASE}</span>
      </div>
      <p className="mt-2 text-sm text-zinc-400">
        Finance data lives behind your operator JWT. Paste your token below to unlock
        the Dashboard, Ledger, Invoices, Payouts, and Tax surfaces.
        {hasToken && <span className="ml-2 text-amber-300">A token is already saved but the API rejected it — paste a fresh one or clear it.</span>}
      </p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          className="input font-mono text-xs"
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="eyJhbGciOi… (paste JWT)"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); }}
        />
        <button className="btn btn-primary" disabled={busy || !val.trim()} onClick={save}>
          Save &amp; reload
        </button>
        {hasToken && (
          <button className="btn btn-ghost" disabled={busy} onClick={clearTok}>
            Clear token
          </button>
        )}
      </div>
      <p className="mt-2 text-[11px] text-zinc-500">
        Stored locally only (<span className="font-mono">localStorage</span>); the token never leaves
        this device except as a Bearer header on requests to{" "}
        <span className="font-mono">{BASE}</span>.
      </p>
    </section>
  );
}

import { useEffect, useState } from "react";
import { api, dollars, isAuthError } from "../api.js";
import PageError from "../components/PageError.jsx";
import SignInRequired from "../components/SignInRequired.jsx";

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [bridge, setBridge] = useState(null);
  const [accountsRollup, setAccountsRollup] = useState(null);
  const [bridgeErr, setBridgeErr] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.dashboard().then(setData).catch(setErr);
    api.bridgeStatus().then(setBridge).catch(setBridgeErr);

    // Best-effort chart-of-accounts rollup. Fail silently if auth blocks it —
    // the main `err` from /dashboard already surfaces the sign-in card.
    (async () => {
      try {
        const accts = await api.listAccounts();
        const bals = await Promise.all(
          accts.map(async (a) => {
            try { return { ...a, balance_cents: (await api.balance(a.code)).balance_cents }; }
            catch { return { ...a, balance_cents: 0 }; }
          })
        );
        setAccountsRollup(groupByType(bals));
      } catch { /* swallowed */ }
    })();
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>

      <BridgeCard bridge={bridge} bridgeErr={bridgeErr} />

      {/* Sign-in card always rendered when /dashboard returned 401, OR when
          no token is set and we have no data — gives the operator an entry
          point even on a fresh visit. */}
      {isAuthError(err) && <SignInRequired />}
      {err && !isAuthError(err) && <PageError err={err} />}
      {!err && !data && <div className="text-zinc-400">Loading dashboard…</div>}
      {data && <DashboardSections data={data} accountsRollup={accountsRollup} />}
    </div>
  );
}

function DashboardSections({ data, accountsRollup }) {
  return (
    <>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="YTD Revenue" value={dollars(data.pnl_ytd.revenue_cents)} accent />
        <Stat label="YTD Expenses" value={dollars(data.pnl_ytd.expense_cents)} />
        <Stat label="YTD Net" value={dollars(data.pnl_ytd.net_cents)} />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card title="Invoices">
          <Row label="Total" value={data.invoices.total} />
          <Row label="Sent" value={data.invoices.sent} />
          <Row label="Paid" value={data.invoices.paid} />
        </Card>
        <Card title="PM payout profiles">
          <Row label="Total" value={data.pms.total} />
          <Row label="Pending" value={data.pms.pending} />
          <Row label="Verified" value={data.pms.verified} />
          <Row label="Active" value={data.pms.active} />
        </Card>
        <Card title="Payouts">
          <Row label="Total" value={data.payouts.total} />
          <Row label="Processing" value={data.payouts.processing} />
          <Row label="Completed" value={data.payouts.completed} />
          <Row label="Failed" value={data.payouts.failed} />
        </Card>
      </section>

      {accountsRollup && <BalanceRollup rollup={accountsRollup} />}

      <section className="card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          The hard lines (do not cross)
        </h2>
        <ul className="space-y-1.5 text-sm text-zinc-300">
          <li>1. Acme Finance is <span className="text-gold">not</span> a money transmitter — PayPal/Dwolla rails only.</li>
          <li>2. No raw bank numbers in DB — provider tokens + last-4 only.</li>
          <li>3. No auto-filing of income tax returns — packets only.</li>
          <li>4. No customer ACH debit without NACHA-compliant consent + account validation.</li>
        </ul>
      </section>
    </>
  );
}

function groupByType(accounts) {
  const out = { asset: [], liability: [], equity: [], revenue: [], expense: [] };
  for (const a of accounts) {
    const type = (a.type || "").toLowerCase();
    if (out[type]) out[type].push(a);
  }
  // Revenue/Liability/Equity are credit-normal: ledger.balance() returns
  // Σdebit - Σcredit, so credit-normal balances arrive negative. Flip the
  // sign for display so the operator sees the "natural" positive figure.
  const flip = (rows, neg) => rows.map((r) => ({ ...r, display_cents: neg ? -r.balance_cents : r.balance_cents }));
  return {
    asset: flip(out.asset, false),
    liability: flip(out.liability, true),
    equity: flip(out.equity, true),
    revenue: flip(out.revenue, true),
    expense: flip(out.expense, false),
  };
}

function BalanceRollup({ rollup }) {
  const total = (rows) => rows.reduce((s, r) => s + (r.display_cents || 0), 0);
  const groups = [
    { key: "asset", label: "Assets", accent: true },
    { key: "liability", label: "Liabilities" },
    { key: "equity", label: "Equity" },
    { key: "revenue", label: "Revenue" },
    { key: "expense", label: "Expenses" },
  ];
  return (
    <section className="card">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
        Chart of accounts — rollup
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {groups.map((g) => (
          <div key={g.key} className="rounded border border-line/60 bg-ink/50 p-3">
            <div className="label">{g.label}</div>
            <div className={`font-mono text-xl ${g.accent ? "text-gold" : "text-zinc-100"}`}>
              {dollars(total(rollup[g.key]))}
            </div>
            <div className="mt-2 space-y-0.5 text-[11px] text-zinc-500">
              {rollup[g.key].slice(0, 4).map((r) => (
                <div key={r.code} className="flex justify-between gap-2">
                  <span className="truncate">{r.name}</span>
                  <span className="font-mono">{dollars(r.display_cents)}</span>
                </div>
              ))}
              {rollup[g.key].length > 4 && (
                <div className="text-zinc-600">+ {rollup[g.key].length - 4} more</div>
              )}
              {!rollup[g.key].length && <div className="text-zinc-600">—</div>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function BridgeCard({ bridge, bridgeErr }) {
  if (bridgeErr) {
    return (
      <section className="card border-red-900/50">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
            CRM bridge
          </h2>
          <span className="text-xs text-red-300">unreachable</span>
        </div>
        <p className="mt-2 text-sm text-zinc-400">
          Flask /api/bridge/status failed: {bridgeErr.message || String(bridgeErr)}
        </p>
      </section>
    );
  }
  if (!bridge) {
    return (
      <section className="card">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
          CRM bridge
        </h2>
        <p className="mt-2 text-sm text-zinc-400">Checking…</p>
      </section>
    );
  }

  const configured = bridge.configured;
  const reachable = bridge.reachable;
  let statusLabel;
  let statusClass;
  if (!configured) {
    statusLabel = "not configured";
    statusClass = "text-zinc-400";
  } else if (reachable === true) {
    statusLabel = "connected";
    statusClass = "text-emerald-300";
  } else if (reachable === false) {
    statusLabel = "configured · unreachable";
    statusClass = "text-amber-300";
  } else {
    statusLabel = "configured";
    statusClass = "text-zinc-300";
  }

  return (
    <section className="card">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
          CRM bridge
        </h2>
        <span className={`text-xs font-mono ${statusClass}`}>{statusLabel}</span>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Row label="Worker URL" value={bridge.worker_base_url || "—"} />
        <Row label="Customers from CRM" value={bridge.linked_customers} />
        <Row label="Last paid invoice" value={bridge.last_paid_at ? new Date(bridge.last_paid_at).toLocaleString() : "—"} />
      </div>
      {bridge.reach_error && (
        <p className="mt-2 text-xs text-amber-300">Reach error: {bridge.reach_error}</p>
      )}
      {bridge.schema_warning && (
        <p className="mt-2 text-xs text-amber-300">Schema: {bridge.schema_warning}</p>
      )}
      {!configured && (
        <p className="mt-2 text-xs text-zinc-500">
          Set <span className="font-mono">CRM_API_BASE_URL</span> and{" "}
          <span className="font-mono">FINANCE_RELAY_SECRET</span> in the Flask env to enable the bridge.
        </p>
      )}
    </section>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${accent ? "text-gold" : "text-zinc-100"}`}>
        {value}
      </div>
    </div>
  );
}

function Card({ title, children }) {
  return (
    <div className="card">
      <div className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-400">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-baseline justify-between text-sm">
      <span className="text-zinc-400">{label}</span>
      <span className="font-mono text-zinc-100">{value}</span>
    </div>
  );
}

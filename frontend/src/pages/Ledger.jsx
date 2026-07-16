import { useEffect, useMemo, useState } from "react";
import { api, dollars } from "../api.js";
import PageError from "../components/PageError.jsx";

export default function Ledger() {
  const [entries, setEntries] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [balances, setBalances] = useState({});
  const [err, setErr] = useState(null);
  const [view, setView] = useState("balance_sheet"); // balance_sheet | trial_balance | entries | accounts

  async function reload() {
    setErr(null);
    try {
      const [ents, accts] = await Promise.all([api.listEntries(), api.listAccounts()]);
      setEntries(ents);
      setAccounts(accts);
      const bal = {};
      await Promise.all(accts.map(async (a) => {
        try { bal[a.code] = (await api.balance(a.code)).balance_cents; }
        catch { bal[a.code] = null; }
      }));
      setBalances(bal);
    } catch (e) { setErr(e); }
  }
  useEffect(() => { reload(); }, []);

  // Trial Balance: derive per-account debit/credit totals by walking posted
  // entries client-side. The /api/ledger/balance/{code} endpoint returns
  // only the net — the raw legs come from /api/ledger/entries.
  const trialBalance = useMemo(() => buildTrialBalance(entries, accounts), [entries, accounts]);
  const balanceSheet = useMemo(() => buildBalanceSheet(accounts, balances), [accounts, balances]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Ledger</h1>
        <div className="flex flex-wrap gap-1">
          {[
            ["balance_sheet", "Balance Sheet"],
            ["trial_balance", "Trial Balance"],
            ["entries", "Entries"],
            ["accounts", "Chart of accounts"],
          ].map(([k, lbl]) => (
            <button
              key={k}
              onClick={() => setView(k)}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                view === k ? "bg-gold/15 text-gold" : "text-zinc-300 hover:bg-line/40 hover:text-gold"
              }`}
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {err && <PageError err={err} />}

      {view === "balance_sheet" && <BalanceSheetView bs={balanceSheet} />}
      {view === "trial_balance" && <TrialBalanceView tb={trialBalance} />}
      {view === "accounts" && <AccountsView accounts={accounts} balances={balances} />}
      {view === "entries" && <EntriesView entries={entries} />}
    </div>
  );
}

// -- Aggregators ------------------------------------------------------------

function buildTrialBalance(entries, accounts) {
  const acctByCode = Object.fromEntries(accounts.map((a) => [a.code, a]));
  const byCode = {}; // code → { debit, credit }
  for (const e of entries) {
    if (e.posted === false) continue; // skip unposted reservations
    for (const ln of e.lines || []) {
      const row = byCode[ln.account] || (byCode[ln.account] = { debit: 0, credit: 0 });
      if (ln.direction === "debit") row.debit += ln.amount_cents;
      else row.credit += ln.amount_cents;
    }
  }
  const rows = Object.entries(byCode)
    .map(([code, { debit, credit }]) => ({
      code,
      name: acctByCode[code]?.name || code,
      type: acctByCode[code]?.type || "—",
      debit,
      credit,
      net: debit - credit,
    }))
    .sort((a, b) => a.code.localeCompare(b.code));
  const total_debit = rows.reduce((s, r) => s + r.debit, 0);
  const total_credit = rows.reduce((s, r) => s + r.credit, 0);
  return { rows, total_debit, total_credit, balanced: total_debit === total_credit };
}

function buildBalanceSheet(accounts, balances) {
  // Balance-sheet view = Assets, Liabilities, Equity at point-in-time.
  // Revenue/Expense roll into Net Income, which is presented as a synthetic
  // equity row (P&L for the period). Sign flip: credit-normal types (liab,
  // equity, revenue) come from ledger.balance() as Σdebit-Σcredit which is
  // negative for normal balances — flip to display positively.
  const group = (type) =>
    accounts
      .filter((a) => (a.type || "").toLowerCase() === type)
      .map((a) => ({
        code: a.code,
        name: a.name,
        balance: balances[a.code] ?? 0,
      }));
  const flip = (rows) => rows.map((r) => ({ ...r, display: -r.balance }));

  const assets = group("asset").map((r) => ({ ...r, display: r.balance }));
  const liabilities = flip(group("liability"));
  const equity = flip(group("equity"));
  const revenue = flip(group("revenue"));
  const expense = group("expense").map((r) => ({ ...r, display: r.balance }));

  const sum = (rows) => rows.reduce((s, r) => s + (r.display || 0), 0);
  const total_assets = sum(assets);
  const total_liabilities = sum(liabilities);
  const total_equity = sum(equity);
  const net_income = sum(revenue) - sum(expense);
  const total_le_plus_ni = total_liabilities + total_equity + net_income;

  return {
    assets, liabilities, equity, revenue, expense,
    total_assets, total_liabilities, total_equity, net_income, total_le_plus_ni,
    balanced: total_assets === total_le_plus_ni,
  };
}

// -- Views ------------------------------------------------------------------

function BalanceSheetView({ bs }) {
  return (
    <>
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <BSGroup title="Assets" rows={bs.assets} total={bs.total_assets} accent />
        <div className="space-y-4">
          <BSGroup title="Liabilities" rows={bs.liabilities} total={bs.total_liabilities} />
          <BSGroup title="Equity" rows={bs.equity} total={bs.total_equity} />
          <BSGroup title="Net income (period)" rows={[]} total={bs.net_income} />
        </div>
      </section>

      <section className="card">
        <div className="flex items-baseline justify-between">
          <div className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
            Accounting identity
          </div>
          <div className={`text-xs font-mono ${bs.balanced ? "text-emerald-300" : "text-amber-300"}`}>
            {bs.balanced ? "balanced ✓" : "out of balance"}
          </div>
        </div>
        <div className="mt-2 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <Row label="Assets" value={dollars(bs.total_assets)} />
          <Row label="Liab + Equity + Net inc" value={dollars(bs.total_le_plus_ni)} />
          <Row label="Δ" value={dollars(bs.total_assets - bs.total_le_plus_ni)} />
        </div>
      </section>
    </>
  );
}

function BSGroup({ title, rows, total, accent }) {
  return (
    <div className="card">
      <div className="flex items-baseline justify-between">
        <div className="text-sm font-semibold uppercase tracking-wide text-zinc-400">{title}</div>
        <div className={`font-mono text-lg ${accent ? "text-gold" : "text-zinc-100"}`}>
          {dollars(total)}
        </div>
      </div>
      <div className="mt-2 space-y-1 text-sm">
        {rows.map((r) => (
          <div key={r.code} className="flex items-baseline justify-between gap-2">
            <span className="text-zinc-300 truncate">
              <span className="font-mono text-xs text-zinc-500 mr-2">{r.code}</span>
              {r.name}
            </span>
            <span className="font-mono text-zinc-200">{dollars(r.display)}</span>
          </div>
        ))}
        {!rows.length && <div className="text-zinc-500 text-xs">—</div>}
      </div>
    </div>
  );
}

function TrialBalanceView({ tb }) {
  return (
    <section className="card">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Trial balance (posted entries only)
        </h2>
        <div className={`text-xs font-mono ${tb.balanced ? "text-emerald-300" : "text-amber-300"}`}>
          {tb.balanced ? "balanced ✓" : "out of balance"}
        </div>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Code</th>
            <th>Account</th>
            <th>Type</th>
            <th className="text-right">Debit</th>
            <th className="text-right">Credit</th>
            <th className="text-right">Net</th>
          </tr>
        </thead>
        <tbody>
          {tb.rows.map((r) => (
            <tr key={r.code}>
              <td className="font-mono text-xs">{r.code}</td>
              <td className="text-zinc-200">{r.name}</td>
              <td className="text-xs text-zinc-400">{r.type}</td>
              <td className="font-mono text-right">{dollars(r.debit)}</td>
              <td className="font-mono text-right">{dollars(r.credit)}</td>
              <td className={`font-mono text-right ${r.net >= 0 ? "text-zinc-200" : "text-amber-200"}`}>
                {dollars(r.net)}
              </td>
            </tr>
          ))}
          {!tb.rows.length && (
            <tr><td colSpan="6" className="text-center text-zinc-500">No posted entries.</td></tr>
          )}
        </tbody>
        {tb.rows.length > 0 && (
          <tfoot>
            <tr>
              <td colSpan="3" className="font-semibold text-zinc-300">Totals</td>
              <td className="font-mono text-right font-semibold text-gold">{dollars(tb.total_debit)}</td>
              <td className="font-mono text-right font-semibold text-gold">{dollars(tb.total_credit)}</td>
              <td className="font-mono text-right">{dollars(tb.total_debit - tb.total_credit)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </section>
  );
}

function AccountsView({ accounts, balances }) {
  return (
    <section className="card">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
        Chart of accounts
      </h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {accounts.map((a) => (
          <div key={a.code} className="rounded border border-line/60 bg-ink/50 px-3 py-2">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-xs text-zinc-400">{a.code}</span>
              <span className="text-[10px] uppercase text-zinc-500">{a.type}</span>
            </div>
            <div className="text-sm text-zinc-200">{a.name}</div>
            <div className="mt-1 font-mono text-xs text-gold">{dollars(balances[a.code])}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function EntriesView({ entries }) {
  return (
    <section className="card">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">Entries</h2>
      <div className="space-y-2">
        {entries.map((e) => (
          <details key={e.id} className="rounded border border-line/60 bg-ink/50">
            <summary className="cursor-pointer px-3 py-2 text-sm">
              <span className="font-mono text-xs text-zinc-400 mr-3">{e.occurred_at?.slice(0,19).replace("T"," ")}</span>
              <span className="text-zinc-100">{e.entry_type}</span>
              {!e.posted && <span className="pill ml-2 bg-amber-900/40 text-amber-200">reservation</span>}
              {e.memo && <span className="ml-2 text-xs text-zinc-500">— {e.memo}</span>}
            </summary>
            <table className="table m-2">
              <thead>
                <tr><th>Account</th><th>Direction</th><th>Amount</th><th>Tax category</th></tr>
              </thead>
              <tbody>
                {e.lines.map((ln, i) => (
                  <tr key={i}>
                    <td className="font-mono text-xs">{ln.account}</td>
                    <td>
                      <span className={`pill ${ln.direction === "debit" ? "bg-emerald-900/40 text-emerald-200" : "bg-amber-900/40 text-amber-200"}`}>{ln.direction}</span>
                    </td>
                    <td className="font-mono">{dollars(ln.amount_cents)}</td>
                    <td className="text-xs text-zinc-400">{ln.tax_category || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        ))}
        {!entries.length && <div className="text-center text-zinc-500">No entries yet.</div>}
      </div>
    </section>
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

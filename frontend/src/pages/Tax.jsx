import { useEffect, useState } from "react";
import { api, dollars, isAuthError, BASE } from "../api.js";
import PageError from "../components/PageError.jsx";

export default function Tax() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [thresholds, setThresholds] = useState([]);
  const [packet, setPacket] = useState(null);
  const [err, setErr] = useState(null);

  async function reload() {
    setErr(null);
    try {
      const [t, p] = await Promise.all([api.thresholds(), api.scheduleC(year)]);
      setThresholds(t);
      setPacket(p);
    } catch (e) { setErr(e); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [year]);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Tax packet</h1>
        <div className="flex items-center gap-2">
          <label className="label !mb-0">Year</label>
          <input className="input w-24" type="number" min="2020" max="2099"
                 value={year} onChange={(e) => setYear(Number(e.target.value))} />
          <a className="btn btn-ghost" href={`${BASE}/tax/schedule-c.csv?year=${year}`} target="_blank" rel="noreferrer">
            Export CSV
          </a>
        </div>
      </div>

      {err && <PageError err={err} />}

      <section className="card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">Thresholds (DB-driven)</h2>
        <table className="table">
          <thead><tr><th>Year</th><th>Form</th><th>Threshold</th><th>Txn min</th><th>Notes</th></tr></thead>
          <tbody>
            {thresholds.map((t) => (
              <tr key={`${t.tax_year}-${t.form_type}`}>
                <td className="font-mono">{t.tax_year}</td>
                <td className="text-gold">{t.form_type}</td>
                <td className="font-mono">{dollars(t.threshold_cents)}</td>
                <td>{t.txn_count_min ?? "—"}</td>
                <td className="text-xs text-zinc-400">{t.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {packet && (
        <>
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Stat label="Revenue" value={dollars(packet.revenue_cents)} accent />
            <Stat label="Expense" value={dollars(packet.expense_cents)} />
            <Stat label="Net" value={dollars(packet.net_cents)} />
          </section>

          <section className="card">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">Expense by tax category</h2>
            <table className="table">
              <thead><tr><th>Category</th><th>Account</th><th>Amount</th></tr></thead>
              <tbody>
                {packet.expense_by_category.map((c, i) => (
                  <tr key={i}>
                    <td className="text-gold">{c.tax_category}</td>
                    <td className="font-mono text-xs">{c.account_code}</td>
                    <td className="font-mono">{dollars(c.amount_cents)}</td>
                  </tr>
                ))}
                {!packet.expense_by_category.length && (
                  <tr><td colSpan="3" className="text-center text-zinc-500">No expenses yet.</td></tr>
                )}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">Contractors (1099 watch)</h2>
            <table className="table">
              <thead><tr><th>Legal name</th><th>Entity</th><th>W-9</th><th>TIN •4</th><th>YTD paid</th><th>Eligible</th></tr></thead>
              <tbody>
                {packet.contractors.map((c) => (
                  <tr key={c.pm_user_id}>
                    <td>{c.legal_name}</td>
                    <td className="text-xs text-zinc-400">{c.entity_type}</td>
                    <td>{c.w9_status}</td>
                    <td className="font-mono text-xs">{c.tin_last4 ?? "—"}</td>
                    <td className="font-mono">{dollars(c.paid_cents)}</td>
                    <td>
                      <span className={`pill ${c.eligible ? "bg-emerald-900/40 text-emerald-200" : "bg-zinc-700 text-zinc-300"}`}>
                        {c.eligible ? "ELIGIBLE" : "below threshold"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!packet.contractors.length && (
                  <tr><td colSpan="6" className="text-center text-zinc-500">No PM profiles yet.</td></tr>
                )}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">Mileage</h2>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div><div className="label">Trips</div><div className="font-mono text-lg">{packet.mileage.trips}</div></div>
              <div><div className="label">Miles</div><div className="font-mono text-lg">{packet.mileage.total_miles.toFixed(2)}</div></div>
              <div><div className="label">Deduction</div><div className="font-mono text-lg text-gold">{dollars(packet.mileage.deduction_cents)}</div></div>
            </div>
          </section>
        </>
      )}

      <section className="card text-xs text-zinc-400">
        <span className="text-gold">Compliance line:</span> Acme Finance generates 1099 information returns and CPA-ready packets.
        It does <span className="font-semibold">not</span> auto-file income tax returns — those stay with a CPA or licensed e-file partner.
      </section>
    </div>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${accent ? "text-gold" : "text-zinc-100"}`}>{value}</div>
    </div>
  );
}

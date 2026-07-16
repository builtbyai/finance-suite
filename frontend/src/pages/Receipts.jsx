import { useEffect, useState } from "react";
import { api, dollars, isAuthError } from "../api.js";
import PageError from "../components/PageError.jsx";

export default function Receipts() {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ merchant: "", amount: "", txn_date: "" });
  const [err, setErr] = useState(null);

  async function reload() {
    setErr(null);
    try { setRows(await api.listReceipts()); }
    catch (e) { setErr(e); }
  }
  useEffect(() => { reload(); }, []);

  async function submit(e) {
    e.preventDefault();
    try {
      await api.createReceipt({
        merchant: form.merchant,
        total_cents: Math.round(Number(form.amount) * 100),
        txn_date: form.txn_date,
      });
      setForm({ merchant: "", amount: "", txn_date: "" });
      await reload();
    } catch (e) { setErr(e); }
  }

  async function confirm(id) {
    try { await api.confirmReceipt(id); await reload(); }
    catch (e) { setErr(e); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Receipts</h1>

      {isAuthError(err) && <PageError err={err} />}

      <form onSubmit={submit} className="card grid grid-cols-1 gap-3 md:grid-cols-4">
        <div>
          <label className="label">Merchant</label>
          <input className="input" value={form.merchant}
                 onChange={(e) => setForm({ ...form, merchant: e.target.value })}
                 placeholder="Home Depot #6543" required />
        </div>
        <div>
          <label className="label">Amount (USD)</label>
          <input className="input" type="number" step="0.01" min="0.01"
                 value={form.amount}
                 onChange={(e) => setForm({ ...form, amount: e.target.value })} required />
        </div>
        <div>
          <label className="label">Date</label>
          <input className="input" type="date" value={form.txn_date}
                 onChange={(e) => setForm({ ...form, txn_date: e.target.value })} />
        </div>
        <div className="flex items-end">
          <button className="btn btn-primary w-full" type="submit">Capture receipt</button>
        </div>
        {err && !isAuthError(err) && (
          <div className="md:col-span-4 text-sm text-red-300">{err.message || String(err)}</div>
        )}
      </form>

      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Merchant</th><th>Total</th><th>Date</th><th>Category</th><th>Confidence</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.merchant || "—"}</td>
                <td className="font-mono">{dollars(r.total_cents)}</td>
                <td className="text-xs text-zinc-400">{r.txn_date || "—"}</td>
                <td className="text-zinc-300">{r.category}</td>
                <td className="font-mono text-xs">{r.confidence?.toFixed(2)}</td>
                <td><span className={`pill ${r.status === "confirmed" ? "bg-emerald-900/40 text-emerald-200" : "bg-zinc-700 text-zinc-200"}`}>{r.status}</span></td>
                <td>
                  {r.status === "draft" && (
                    <button className="btn btn-ghost" onClick={() => confirm(r.id)}>Confirm</button>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan="7" className="text-center text-zinc-500">No receipts.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

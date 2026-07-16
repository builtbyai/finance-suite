import { useEffect, useState } from "react";
import { api, dollars, isAuthError } from "../api.js";
import PageError from "../components/PageError.jsx";

export default function Invoices() {
  const [rows, setRows] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [form, setForm] = useState({ customer_id: "", amount: "", memo: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function reload() {
    setErr(null);
    try {
      const [invs, custs] = await Promise.all([api.listInvoices(), api.listCustomers()]);
      setRows(invs);
      setCustomers(custs);
      if (!form.customer_id && custs.length) {
        setForm((f) => ({ ...f, customer_id: custs[0].id }));
      }
    } catch (e) {
      setErr(e);
    }
  }

  useEffect(() => { reload(); }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const created = await api.createInvoice({
        customer_id: form.customer_id,
        amount_cents: Math.round(Number(form.amount) * 100),
        memo: form.memo || undefined,
      });
      await api.sendInvoice(created.id);
      setForm({ ...form, amount: "", memo: "" });
      await reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  async function addCustomer() {
    const name = prompt("Customer name?");
    if (!name) return;
    const email = prompt("Email (optional)?") || undefined;
    await api.createCustomer({ name, email });
    await reload();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Invoices</h1>
        <button onClick={addCustomer} className="btn btn-ghost">+ Customer</button>
      </div>

      {isAuthError(err) && <PageError err={err} />}

      <form onSubmit={submit} className="card grid grid-cols-1 gap-3 md:grid-cols-4">
        <div>
          <label className="label">Customer</label>
          <select
            className="input"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
            required
          >
            <option value="" disabled>Select…</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Amount (USD)</label>
          <input
            type="number" step="0.01" min="0.01"
            className="input"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            required
          />
        </div>
        <div className="md:col-span-2">
          <label className="label">Memo</label>
          <input
            className="input"
            value={form.memo}
            onChange={(e) => setForm({ ...form, memo: e.target.value })}
            placeholder="Roof replacement — claim work"
          />
        </div>
        <div className="md:col-span-4">
          <button type="submit" disabled={busy} className="btn btn-primary">
            {busy ? "Sending…" : "Create + Send invoice"}
          </button>
          {err && !isAuthError(err) && (
            <span className="ml-3 text-sm text-red-300">{err.message || String(err)}</span>
          )}
        </div>
      </form>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Number</th>
              <th>Customer</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Issued</th>
              <th>Paid</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="font-mono text-xs text-zinc-200">{r.number}</td>
                <td className="text-zinc-300">{customers.find((c) => c.id === r.customer_id)?.name || r.customer_id}</td>
                <td className="font-mono">{dollars(r.amount_cents)}</td>
                <td><Pill status={r.status} /></td>
                <td className="text-xs text-zinc-400">{r.issued_at?.slice(0,10) || "—"}</td>
                <td className="text-xs text-zinc-400">{r.paid_at?.slice(0,10) || "—"}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan="6" className="text-center text-zinc-500">No invoices yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Pill({ status }) {
  const color = {
    draft: "bg-zinc-700 text-zinc-200",
    sent: "bg-amber-900/40 text-amber-200",
    paid: "bg-emerald-900/40 text-emerald-200",
    cancelled: "bg-zinc-800 text-zinc-400 line-through",
    refunded: "bg-red-900/40 text-red-200",
    partially_paid: "bg-amber-900/40 text-amber-200",
  }[status] || "bg-zinc-700 text-zinc-200";
  return <span className={`pill ${color}`}>{status}</span>;
}

import { useEffect, useState } from "react";
import { api, dollars, isAuthError } from "../api.js";
import PageError from "../components/PageError.jsx";

export default function Mileage() {
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ driver_user_id: "", miles: "", purpose: "", tax_year: new Date().getFullYear() });
  const [err, setErr] = useState(null);

  async function reload() {
    setErr(null);
    try {
      const [ms, us] = await Promise.all([api.listMileage(), api.listUsers()]);
      setRows(ms); setUsers(us);
      if (!form.driver_user_id && us.length) {
        setForm((f) => ({ ...f, driver_user_id: us.find(u => u.role === "pm")?.id || us[0].id }));
      }
    } catch (e) { setErr(e); }
  }
  useEffect(() => { reload(); }, []);

  async function submit(e) {
    e.preventDefault();
    try {
      await api.createMileage({
        driver_user_id: form.driver_user_id,
        miles: Number(form.miles),
        purpose: form.purpose || undefined,
        tax_year: Number(form.tax_year),
      });
      setForm({ ...form, miles: "", purpose: "" });
      await reload();
    } catch (e) { setErr(e); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Mileage</h1>

      {isAuthError(err) && <PageError err={err} />}

      <form onSubmit={submit} className="card grid grid-cols-1 gap-3 md:grid-cols-5">
        <div>
          <label className="label">Driver</label>
          <select className="input" value={form.driver_user_id}
                  onChange={(e) => setForm({ ...form, driver_user_id: e.target.value })}>
            {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Miles</label>
          <input className="input" type="number" step="0.1" min="0.1"
                 aria-label="Miles"
                 placeholder="12.5"
                 value={form.miles}
                 onChange={(e) => setForm({ ...form, miles: e.target.value })} required />
        </div>
        <div>
          <label className="label">Tax year</label>
          <input className="input" type="number" min="2020" max="2099"
                 value={form.tax_year}
                 onChange={(e) => setForm({ ...form, tax_year: e.target.value })} required />
        </div>
        <div className="md:col-span-2">
          <label className="label">Purpose</label>
          <input className="input" value={form.purpose}
                 onChange={(e) => setForm({ ...form, purpose: e.target.value })}
                 placeholder="Inspection — Smith roof" />
        </div>
        <div className="md:col-span-5">
          <button className="btn btn-primary" type="submit">Log trip</button>
          {err && !isAuthError(err) && (
            <span className="ml-3 text-sm text-red-300">{err.message || String(err)}</span>
          )}
        </div>
      </form>

      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Date</th><th>Driver</th><th>Miles</th><th>Rate</th><th>Deduction</th><th>Purpose</th></tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id}>
                <td className="text-xs text-zinc-400">{m.logged_at?.slice(0,10)}</td>
                <td>{users.find((u) => u.id === m.driver_user_id)?.name || m.driver_user_id.slice(0,8)}</td>
                <td className="font-mono">{m.miles.toFixed(2)}</td>
                <td className="font-mono text-xs">{(m.rate_cents / 100).toFixed(2)} ¢</td>
                <td className="font-mono">{dollars(m.deduction_cents)}</td>
                <td className="text-zinc-300">{m.purpose || "—"}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan="6" className="text-center text-zinc-500">No mileage logs.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

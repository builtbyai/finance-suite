import { useEffect, useState } from "react";
import { api, dollars, isAuthError } from "../api.js";
import PageError from "../components/PageError.jsx";

const CONSENT_TEXT = `I authorize Acme Finance and its payment processor to send approved payouts to the payout method I have provided. This authorization remains in effect until I remove or replace my payout method.`;

export default function Payouts() {
  const [profiles, setProfiles] = useState([]);
  const [payouts, setPayouts] = useState([]);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [pForm, setPForm] = useState({ pm_user_id: "", legal_name: "", entity_type: "individual" });

  async function reload() {
    setErr(null);
    try {
      const [pf, po, us] = await Promise.all([
        api.listProfiles(), api.listPayouts(), api.listUsers(),
      ]);
      setProfiles(pf); setPayouts(po); setUsers(us);
      if (!pForm.pm_user_id && us.length) {
        const pm = us.find((u) => u.role === "pm") || us[0];
        setPForm((f) => ({ ...f, pm_user_id: pm.id, legal_name: pm.name || "" }));
      }
    } catch (e) { setErr(e); }
  }
  useEffect(() => { reload(); }, []);

  async function createProfile(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createProfile(pForm);
      await reload();
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  }

  async function simulateBankLink(profileId) {
    // Dry-run flow: pretend Plaid Link succeeded. The backend dry_run path
    // will mint synthetic tokens and create a Dwolla funding source stub.
    const last4 = prompt("Bank last-4 (dry run)?", "1234") || "1234";
    try {
      await api.bankLinkExchange({
        profile_id: profileId,
        public_token: "public-sandbox-DRY",
        account_id: "account-DRY",
        bank_name: "Frost Bank",
        bank_last4: last4,
        account_type: "checking",
      });
      await reload();
    } catch (e) { setErr(e); }
  }

  async function submitW9(profileId) {
    const last4 = prompt("TIN last-4?", "6789");
    if (!last4) return;
    try {
      await api.submitW9(profileId, { tin_last4: last4 });
      await reload();
    } catch (e) { setErr(e); }
  }

  async function authorize(profileId) {
    try {
      await api.authorizeProfile(profileId, {
        consent_version: "pm-payout-v1",
        consent_text: CONSENT_TEXT,
      });
      await reload();
    } catch (e) { setErr(e); }
  }

  async function startPayout(profileId) {
    const amount = prompt("Payout amount (USD)?", "1450.00");
    if (!amount) return;
    try {
      await api.initiatePayout({
        profile_id: profileId,
        amount_cents: Math.round(Number(amount) * 100),
      });
      await reload();
    } catch (e) { setErr(e); }
  }

  async function completePayout(id) {
    try {
      await api.simulateComplete(id);
      await reload();
    } catch (e) { setErr(e); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">PM Payouts</h1>

      {isAuthError(err) && <PageError err={err} />}

      <form onSubmit={createProfile} className="card grid grid-cols-1 gap-3 md:grid-cols-4">
        <div>
          <label className="label">PM user</label>
          <select className="input" value={pForm.pm_user_id}
                  onChange={(e) => setPForm({ ...pForm, pm_user_id: e.target.value })}>
            {users.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
          </select>
        </div>
        <div>
          <label className="label">Legal name</label>
          <input className="input" aria-label="Legal name"
                 placeholder="Jordan Lee"
                 value={pForm.legal_name}
                 onChange={(e) => setPForm({ ...pForm, legal_name: e.target.value })} required />
        </div>
        <div>
          <label className="label">Entity</label>
          <select className="input" value={pForm.entity_type}
                  onChange={(e) => setPForm({ ...pForm, entity_type: e.target.value })}>
            <option value="individual">individual</option>
            <option value="sole_prop">sole proprietor</option>
            <option value="llc">LLC</option>
            <option value="s_corp">S corp</option>
            <option value="c_corp">C corp</option>
          </select>
        </div>
        <div className="flex items-end">
          <button className="btn btn-primary w-full" disabled={busy} type="submit">Add profile</button>
        </div>
        {err && !isAuthError(err) && (
          <div className="md:col-span-4 text-sm text-red-300">{err.message || String(err)}</div>
        )}
      </form>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Profiles</h2>
        <div className="space-y-3">
          {profiles.map((p) => (
            <div key={p.id} className="card flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="font-semibold">{p.legal_name}</div>
                <div className="text-xs text-zinc-500">{p.entity_type} · status <span className="text-gold">{p.status}</span> · W-9 <span className="text-gold">{p.w9_status}</span></div>
                <div className="text-xs text-zinc-500">
                  {p.bank_name ? `${p.bank_name} ••${p.bank_last4} (${p.account_type})` : "no bank linked"}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {p.status === "pending" && (
                  <button className="btn btn-ghost" onClick={() => simulateBankLink(p.id)}>Link bank (dry run)</button>
                )}
                {p.w9_status === "not_collected" && (
                  <button className="btn btn-ghost" onClick={() => submitW9(p.id)}>Collect W-9</button>
                )}
                {p.status === "verified" && (
                  <button className="btn btn-ghost" onClick={() => authorize(p.id)}>Sign authorization</button>
                )}
                {(p.status === "active" || p.status === "verified") && (
                  <button className="btn btn-primary" onClick={() => startPayout(p.id)}>Initiate payout</button>
                )}
              </div>
            </div>
          ))}
          {!profiles.length && (
            <div className="card text-center text-zinc-500">No PM profiles yet.</div>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Payouts</h2>
        <div className="card">
          <table className="table">
            <thead>
              <tr><th>PM</th><th>Amount</th><th>Status</th><th>Initiated</th><th>Completed</th><th></th></tr>
            </thead>
            <tbody>
              {payouts.map((po) => {
                const pf = profiles.find((p) => p.id === po.profile_id);
                return (
                  <tr key={po.id}>
                    <td>{pf?.legal_name || po.pm_user_id.slice(0,8)}</td>
                    <td className="font-mono">{dollars(po.amount_cents)}</td>
                    <td>
                      <span className={`pill ${
                        po.status === "completed" ? "bg-emerald-900/40 text-emerald-200" :
                        po.status === "processing" ? "bg-amber-900/40 text-amber-200" :
                        po.status === "failed" ? "bg-red-900/40 text-red-200" : "bg-zinc-700 text-zinc-200"
                      }`}>{po.status}{po.failure_code ? ` · ${po.failure_code}` : ""}</span>
                    </td>
                    <td className="text-xs text-zinc-400">{po.initiated_at?.slice(0,16).replace("T"," ") || "—"}</td>
                    <td className="text-xs text-zinc-400">{po.completed_at?.slice(0,16).replace("T"," ") || "—"}</td>
                    <td>
                      {po.status === "processing" && (
                        <button className="btn btn-ghost" onClick={() => completePayout(po.id)}>
                          Simulate webhook
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!payouts.length && (
                <tr><td colSpan="6" className="text-center text-zinc-500">No payouts yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

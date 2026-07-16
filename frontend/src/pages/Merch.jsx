import { useEffect, useState } from "react";
import { api, dollars } from "../api.js";
import PageError from "../components/PageError.jsx";

export default function Merch() {
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [err, setErr] = useState(null);

  async function reload() {
    setErr(null);
    try {
      const [p, o] = await Promise.all([api.listMerchProducts(), api.listMerchOrders()]);
      setProducts(p); setOrders(o);
    } catch (e) { setErr(e); }
  }
  useEffect(() => { reload(); }, []);

  async function order(productId) {
    const qty = Number(prompt("Qty?", "1") || "1");
    if (!qty) return;
    try {
      await api.createMerchOrder({
        product_id: productId, qty,
        ship_to: { name: "Test Customer", city: "Dallas", state_code: "TX", country_code: "US" },
        processor_fee_cents: 150,
      });
      await reload();
    } catch (e) { setErr(e); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Merch storefront</h1>

      {err && <PageError err={err} />}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {products.map((p) => (
          <div key={p.id} className="card">
            <div className="text-xs text-zinc-500">{p.sku}</div>
            <div className="text-lg font-semibold">{p.title}</div>
            <div className="mt-1 text-xs text-zinc-400">{p.fulfillment}</div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="font-mono text-zinc-300">{dollars(p.base_cost_cents)} cost</span>
              <span className="font-mono text-gold">{dollars(p.retail_cents)} retail</span>
            </div>
            <button className="btn btn-primary mt-3 w-full" onClick={() => order(p.id)}>Order test</button>
          </div>
        ))}
      </section>

      <section className="card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">Orders</h2>
        <table className="table">
          <thead>
            <tr><th>Date</th><th>Provider</th><th>Provider order</th><th>Qty</th><th>Total</th><th>COGS</th><th>Margin</th><th>Status</th></tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td className="text-xs text-zinc-400">{o.created_at?.slice(0,16).replace("T"," ")}</td>
                <td>{o.provider}</td>
                <td className="font-mono text-xs text-zinc-400">{o.provider_order_id}</td>
                <td>{o.qty}</td>
                <td className="font-mono">{dollars(o.total_cents)}</td>
                <td className="font-mono">{dollars(o.cogs_cents)}</td>
                <td className="font-mono text-gold">{dollars(o.total_cents - (o.cogs_cents || 0))}</td>
                <td><span className="pill bg-zinc-700 text-zinc-200">{o.status}</span></td>
              </tr>
            ))}
            {!orders.length && (
              <tr><td colSpan="8" className="text-center text-zinc-500">No orders.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

import { Link, NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Invoices from "./pages/Invoices.jsx";
import Payouts from "./pages/Payouts.jsx";
import Ledger from "./pages/Ledger.jsx";
import Receipts from "./pages/Receipts.jsx";
import Mileage from "./pages/Mileage.jsx";
import Tax from "./pages/Tax.jsx";
import Merch from "./pages/Merch.jsx";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/invoices", label: "Invoices" },
  { to: "/payouts", label: "Payouts" },
  { to: "/ledger", label: "Ledger" },
  { to: "/receipts", label: "Receipts" },
  { to: "/mileage", label: "Mileage" },
  { to: "/tax", label: "Tax" },
  { to: "/merch", label: "Merch" },
];

export default function App() {
  return (
    <div className="min-h-screen bg-ink text-zinc-100">
      <header className="border-b border-line bg-inkSoft/40 px-6 py-4">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-8">
          <Link to="/" className="flex items-center gap-3 whitespace-nowrap">
            <span
              className="grid h-8 w-8 shrink-0 select-none place-items-center rounded-md bg-gold/15 font-mono text-sm font-bold text-gold"
              aria-hidden="true"
            >
              AF
            </span>
            <span className="text-lg font-semibold tracking-tight text-gold">
              Acme Finance Suite
            </span>
            <span className="hidden text-xs text-zinc-500 2xl:inline">Self-owned ledger. Providers as rails.</span>
          </Link>
          <nav className="hidden shrink-0 gap-1 md:flex">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm transition ${
                    isActive
                      ? "bg-gold/10 text-gold"
                      : "text-zinc-300 hover:bg-line/40 hover:text-gold"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/invoices" element={<Invoices />} />
          <Route path="/payouts" element={<Payouts />} />
          <Route path="/ledger" element={<Ledger />} />
          <Route path="/receipts" element={<Receipts />} />
          <Route path="/mileage" element={<Mileage />} />
          <Route path="/tax" element={<Tax />} />
          <Route path="/merch" element={<Merch />} />
        </Routes>
      </main>
      <footer className="px-6 py-6 text-center text-xs text-zinc-500">
        Local-first build · No money movement without a verified webhook
      </footer>
    </div>
  );
}

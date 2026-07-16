// Where the Finance Suite calls live.
//   Dev (Vite dev server): VITE_API_BASE unset → "/api" → Vite proxy →
//                          local Flask on 127.0.0.1:5055.
//   Prod (Cloudflare Pages): VITE_API_BASE = "https://api.example.com/api"
//                          → CRM Worker. The Worker only owns the bridge
//                          surface (/api/finance/*) today; operator-facing
//                          /dashboard, /ledger, /receipts, etc. still need a
//                          public Flask host to land. Until then the dashboard
//                          BridgeCard works in prod but the rest of the UI
//                          will surface "Backend not reachable".
export const BASE = (import.meta.env?.VITE_API_BASE || "/api").replace(/\/+$/, "");

// JWT issued by the Worker, stored by the operator login flow under
// VITE_API_TOKEN_STORAGE_KEY (defaults to "finance:jwt"). When present every
// request adds Authorization: Bearer <token>; the Worker's /api/finance/*
// routes require it.
const TOKEN_KEY = import.meta.env?.VITE_API_TOKEN_STORAGE_KEY || "finance:jwt";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
export function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {}
}
export function isAuthError(err) {
  return !!err && (err.status === 401 || err.status === 403 || /401|unauthor|forbidden/i.test(err.message || ""));
}

function authHeader() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function req(path, init = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...authHeader(),
        ...(init.headers || {}),
      },
      ...init,
    });
  } catch (e) {
    // Network / DNS / CORS-preflight failure — fetch() throws TypeError.
    const err = new Error(`network error (${e.message || "fetch failed"})`);
    err.status = 0;
    throw err;
  }
  if (!res.ok) {
    let msg = `request failed (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch {}
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
}

export const api = {
  health: () => req("/health"),
  dashboard: () => req("/dashboard"),
  bridgeStatus: () => req("/bridge/status"),

  listCustomers: () => req("/customers"),
  createCustomer: (b) => req("/customers", { method: "POST", body: JSON.stringify(b) }),

  listUsers: () => req("/users"),
  createUser: (b) => req("/users", { method: "POST", body: JSON.stringify(b) }),

  listInvoices: () => req("/invoices"),
  createInvoice: (b) => req("/invoices", { method: "POST", body: JSON.stringify(b) }),
  sendInvoice: (id) => req(`/invoices/${id}/send`, { method: "POST" }),
  cancelInvoice: (id) => req(`/invoices/${id}/cancel`, { method: "POST" }),

  listProfiles: () => req("/payouts/profiles"),
  createProfile: (b) => req("/payouts/profiles", { method: "POST", body: JSON.stringify(b) }),
  submitW9: (id, b) => req(`/payouts/profiles/${id}/w9`, { method: "POST", body: JSON.stringify(b) }),
  authorizeProfile: (id, b) => req(`/payouts/profiles/${id}/authorize`, { method: "POST", body: JSON.stringify(b) }),
  bankLinkExchange: (b) => req("/bank-link/exchange", { method: "POST", body: JSON.stringify(b) }),
  bankLinkToken: (b) => req("/bank-link/token", { method: "POST", body: JSON.stringify(b) }),

  listPayouts: () => req("/payouts"),
  initiatePayout: (b) => req("/payouts/initiate", { method: "POST", body: JSON.stringify(b) }),
  simulateComplete: (id) => req(`/payouts/${id}/simulate-complete`, { method: "POST" }),

  listAccounts: () => req("/ledger/accounts"),
  listEntries: () => req("/ledger/entries"),
  balance: (code) => req(`/ledger/balance/${code}`),
  pnl: (year) => req(`/ledger/pnl?year=${year}`),

  listReceipts: () => req("/receipts"),
  createReceipt: (b) => req("/receipts", { method: "POST", body: JSON.stringify(b) }),
  confirmReceipt: (id) => req(`/receipts/${id}/confirm`, { method: "POST" }),

  listMileage: () => req("/mileage"),
  createMileage: (b) => req("/mileage", { method: "POST", body: JSON.stringify(b) }),

  thresholds: () => req("/tax/thresholds"),
  scheduleC: (year) => req(`/tax/schedule-c?year=${year}`),
  eligibility: (pmUserId, year) => req(`/tax/eligibility?pm_user_id=${pmUserId}&year=${year}`),

  listMerchProducts: () => req("/merch/products"),
  createMerchProduct: (b) => req("/merch/products", { method: "POST", body: JSON.stringify(b) }),
  listMerchOrders: () => req("/merch/orders"),
  createMerchOrder: (b) => req("/merch/orders", { method: "POST", body: JSON.stringify(b) }),
};

const _fmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function dollars(cents) {
  if (cents === null || cents === undefined) return "—";
  return _fmt.format(cents / 100);
}

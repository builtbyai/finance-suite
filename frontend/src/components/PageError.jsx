import { isAuthError } from "../api.js";
import SignInRequired from "./SignInRequired.jsx";

// Single error surface used by every page. 401/403 → sign-in card so the
// operator can paste a JWT and proceed. Anything else → red text with status.
export default function PageError({ err }) {
  if (!err) return null;
  if (isAuthError(err)) return <SignInRequired />;
  const status = err.status ? ` (HTTP ${err.status})` : "";
  return (
    <section className="card border-red-900/50">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-red-300">
        Backend not reachable{status}
      </h2>
      <p className="mt-2 text-sm text-zinc-400 break-words">{err.message || String(err)}</p>
    </section>
  );
}

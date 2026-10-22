import { useState, type FormEvent } from "react";
import { useAuth } from "../state";

export default function LoginPage() {
  const { login } = useAuth();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(u, p);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark">Au</span>
          <span className="brand-name">Gold AI Adaptive Agentic Scalper</span>
        </div>
        <p className="muted small">XAUUSD research and simulation platform. Real-money trading is disabled unless the owner grants it.</p>
        <label className="field">
          <span>Username</span>
          <input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" required />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required />
        </label>
        {err && <p className="state state-error">{err}</p>}
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

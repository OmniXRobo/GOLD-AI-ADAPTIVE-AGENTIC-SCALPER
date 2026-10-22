import { useState, type FormEvent } from "react";
import { Icon } from "../components/icons";
import { nativeApp } from "../native";
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
          <span className="brand-mark" aria-hidden="true">
            <Icon name="market" size={24} />
          </span>
          <span className="brand-name">
            Gold AI <small>Adaptive Agentic Scalper · XAUUSD</small>
          </span>
        </div>
        <label className="field">
          <span>Username</span>
          <input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" autoCapitalize="none" required />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required />
        </label>
        {err && <p className="state state-error">{err}</p>}
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
        <div className="login-safety">
          <Icon name="risk" size={16} />
          <span>Research and simulation platform. Real-money trading is disabled unless the owner grants it.</span>
        </div>
        {nativeApp.available() && (
          <button type="button" className="btn btn-ghost btn-small" onClick={() => nativeApp.openSettings()}>
            <Icon name="phone" size={16} /> Change server
          </button>
        )}
      </form>
    </div>
  );
}

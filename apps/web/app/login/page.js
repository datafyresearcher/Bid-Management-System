"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setSession } from "../../lib/api";

const DEMO = [
  ["admin@ahte.local", "admin123", "Admin"],
  ["bm@ahte.local", "bid123", "Bid Manager"],
  ["engineer@ahte.local", "prop123", "Proposal Engineer"],
  ["mgmt@ahte.local", "mgmt123", "Management"],
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@ahte.local");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setSession(data.token, data.user);
      router.replace("/");
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>AI Bid Management System</h1>
        <p>Tender discovery, triage, gated review and proposal drafting.</p>
        {error ? <div className="notice err">{error}</div> : null}
        <label>Email</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        <label>Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        <div className="mt-14">
          <button className="btn primary" type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
        <div className="demo-users">
          Demo accounts:
          <div>
            {DEMO.map(([mail, pass, label]) => (
              <button
                type="button"
                key={mail}
                onClick={() => {
                  setEmail(mail);
                  setPassword(pass);
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}

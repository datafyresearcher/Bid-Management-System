"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setSession } from "../../lib/api";
import ThemeToggle from "../../components/ThemeToggle";

// The one-click demo accounts exist to walk the fixtures pipeline. They are
// built in only when the deployment says it is a demo — a deployment reading
// the live portals does not advertise accounts and passwords on its sign-in
// screen.
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

const DEMO = [
  ["admin@ahte.local", "admin123", "Admin"],
  ["bm@ahte.local", "bid123", "Bid Manager"],
  ["engineer@ahte.local", "prop123", "Proposal Engineer"],
  ["mgmt@ahte.local", "mgmt123", "Management"],
];

export default function LoginPage() {
  const router = useRouter();
  const passwordRef = useRef(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      // Empty the password field before the client-side navigation. The
      // browser's password manager reads the field when the route changes,
      // and an empty field gives it nothing to offer to save — this is what
      // keeps the "Save password?" bar from appearing on every sign-in.
      if (passwordRef.current) passwordRef.current.value = "";
      setPassword("");
      router.replace("/");
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <ThemeToggle className="login-theme" />
      {/* Decorative side scenes: tender discovery radar (left) and the five
          gated workflow steps orbiting the brand (right). Purely ambient —
          hidden from assistive tech, untouchable, and only on wide screens. */}
      <div className="login-scene" aria-hidden="true">
        <div className="scene-radar">
          <span className="radar-ring r1" />
          <span className="radar-ring r2" />
          <span className="radar-ring r3" />
          <span className="radar-ring r4" />
          <span className="radar-sweep" />
          <span className="radar-center" />
          <span className="radar-blip b1" />
          <span className="radar-blip b2" />
          <span className="radar-blip b3" />
          <span className="radar-blip b4" />
          <div className="scene-chip radar-chip">
            <span className="chip-dot" />
            Leads Radar · scanning live portals
          </div>
        </div>
        <div className="scene-orbit">
          <span className="orbit-ring" />
          <span className="orbit-ring r2" />
          <span className="orbit-core">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/ahte-logo.png" alt="" width="52" height="52" />
          </span>
          <div className="orbit-spinner">
            {["G1", "G2", "G3", "G4", "G5"].map((gate, i) => (
              <span key={gate} className={`orbit-node n${i + 1}`}>
                <i>{gate}</i>
              </span>
            ))}
          </div>
          <div className="scene-chip orbit-chip">
            <span className="chip-dot" />
            G1 → G5 · every bid human-gated
          </div>
        </div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/ahte-logo.png" alt="AHTE logo" width="58" height="58" />
        </div>
        <h1>
          AHTE <span>BMS</span>
        </h1>
        <p className="login-company">AL-Hussain Traders &amp; Engineers PVT. LTD.</p>
        <p className="login-desc">
          AI Powered Bid Management System — tender discovery, triage, gated review and proposal
          drafting.
        </p>
        {error ? <div className="notice err">{error}</div> : null}
        <label htmlFor="login-email">Email</label>
        <input
          id="login-email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          required
        />
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          ref={passwordRef}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
        <button className="btn primary login-submit" type="submit" disabled={busy}>
          {busy ? (
            <>
              <span className="btn-spin" aria-hidden="true" />
              Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </button>
        {DEMO_MODE ? (
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
        ) : (
          <p className="demo-users">Sign in with the account issued by your administrator.</p>
        )}
      </form>
    </div>
  );
}

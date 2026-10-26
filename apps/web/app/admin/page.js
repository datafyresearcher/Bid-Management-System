"use client";

import { useCallback, useEffect, useState } from "react";
import { api, clearSession, fmtDateTime, getToken } from "../../lib/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function pct(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export default function AdminPage() {
  const [users, setUsers] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [quality, setQuality] = useState(null);
  const [evaluation, setEvaluation] = useState(null);
  const [evalBusy, setEvalBusy] = useState(false);
  const [audit, setAudit] = useState([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [userForm, setUserForm] = useState({ email: "", name: "", role: "bid_manager", password: "" });
  const [mapForm, setMapForm] = useState({ source_code: "", source_category: "", internal_category: "" });
  const [digestPreview, setDigestPreview] = useState(null);
  const [digestBusy, setDigestBusy] = useState(false);

  const load = useCallback(() => {
    api("/api/admin/users").then(setUsers).catch((e) => setError(e.message));
    api("/api/admin/category-mappings").then(setMappings).catch(() => setMappings([]));
    api("/api/admin/ai-quality").then(setQuality).catch(() => setQuality(null));
    api("/api/admin/audit?limit=150").then(setAudit).catch(() => setAudit([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runEvaluation = async () => {
    setEvalBusy(true);
    setError("");
    try {
      const result = await api("/api/admin/evaluation");
      setEvaluation(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setEvalBusy(false);
    }
  };

  const previewDigest = async () => {
    setDigestBusy(true);
    setError("");
    setInfo("");
    try {
      const result = await api("/api/admin/digest/preview");
      setDigestPreview(result.text);
      setInfo(
        `The brief lists ${result.ranked} ranked tender(s); ${result.overdue_gates} gate(s) past SLA, ${result.pending_gates} open.`
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setDigestBusy(false);
    }
  };

  const sendDigestNow = async () => {
    setDigestBusy(true);
    setError("");
    setInfo("");
    try {
      const result = await api("/api/admin/digest/send", { method: "POST" });
      setInfo(
        result.sent
          ? `Digest sent to ${result.recipients} recipient(s).`
          : "Digest built but not emailed — this deployment has no SMTP account (BMS_SMTP_HOST). It is recorded in the notification inbox."
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setDigestBusy(false);
    }
  };

  const act = async (fn, message) => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await fn();
      setInfo(message);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const downloadAudit = async () => {
    const resp = await fetch(`${API}/api/admin/audit/export`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (resp.status === 401) {
      clearSession();
      window.location.href = "/login";
      return;
    }
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "audit_log.csv";
    a.click();
    window.URL.revokeObjectURL(url);
  };

  return (
    <>
      <h2 className="page-title">Admin & AI Quality</h2>
      <p className="page-sub">Users, category mappings, AI metrics and the full decision audit trail.</p>

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      <div className="grid cols-2">
        <div className="card">
          <h3>Users</h3>
          <div className="inline-form">
            <div><label>Email</label><input value={userForm.email} onChange={(e) => setUserForm({ ...userForm, email: e.target.value })} /></div>
            <div><label>Name</label><input value={userForm.name} onChange={(e) => setUserForm({ ...userForm, name: e.target.value })} /></div>
            <div>
              <label>Role</label>
              <select value={userForm.role} onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}>
                {["admin", "bid_manager", "proposal_engineer", "finance", "management", "viewer"].map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div><label>Password</label><input type="password" value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} /></div>
            <button className="btn primary" disabled={busy || !userForm.email || !userForm.password} onClick={() => act(() => api("/api/admin/users", { method: "POST", body: JSON.stringify(userForm) }), "User created")}>
              Add user
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td data-label="Name">{u.name}</td>
                    <td data-label="Email">{u.email}</td>
                    <td data-label="Role">{u.role}</td>
                    <td data-label="Active">
                      <button
                        className={u.active ? "btn small primary" : "btn small"}
                        disabled={busy}
                        onClick={() => act(() => api(`/api/admin/users/${u.id}`, { method: "PUT", body: JSON.stringify({ active: !u.active }) }), "User updated")}
                      >
                        {u.active ? "active" : "disabled"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Category mappings</h3>
          <p className="muted">Map source portal categories to internal categories used by scoring.</p>
          <div className="inline-form">
            <div><label>Source code</label><input value={mapForm.source_code} onChange={(e) => setMapForm({ ...mapForm, source_code: e.target.value })} placeholder="ppra_punjab" /></div>
            <div><label>Source category</label><input value={mapForm.source_category} onChange={(e) => setMapForm({ ...mapForm, source_category: e.target.value })} /></div>
            <div>
              <label>Internal category</label>
              <select value={mapForm.internal_category} onChange={(e) => setMapForm({ ...mapForm, internal_category: e.target.value })}>
                <option value="">—</option>
                {["Substations", "Transmission Lines", "Renewable Energy", "Civil Infrastructure", "Transport Infrastructure", "Supply / Goods", "Services", "General"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <button
              className="btn primary"
              disabled={busy || !mapForm.source_code || !mapForm.source_category || !mapForm.internal_category}
              onClick={() => act(() => api("/api/admin/category-mappings", { method: "POST", body: JSON.stringify(mapForm) }), "Mapping saved")}
            >
              Save mapping
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Source</th><th>Source category</th><th>Internal</th><th></th></tr></thead>
              <tbody>
                {mappings.map((m) => (
                  <tr key={m.id}>
                    <td data-label="Source">{m.source_code}</td>
                    <td data-label="Source category">{m.source_category}</td>
                    <td data-label="Internal">{m.internal_category}</td>
                    <td data-label="">
                      <button className="btn small danger" disabled={busy} onClick={() => act(() => api(`/api/admin/category-mappings/${m.id}`, { method: "DELETE" }), "Mapping deleted")}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid cols-2 mt-14">
        <div className="card">
          <h3>AI quality metrics</h3>
          {quality ? (
            <>
              <div className="kv">
                <dt>Provider</dt>
                <dd>
                  {quality.provider?.provider} · {quality.provider?.model}
                  {quality.provider?.simulated ? <span className="badge badge-gray">simulated</span> : null}
                  {quality.provider?.enabled ? null : <span className="badge badge-red">not configured</span>}
                </dd>
                <dt>LLM calls by task</dt>
                <dd>
                  {Object.entries(quality.llm_by_task || {}).map(([task, m]) => `${task}: ${m.calls} (invalid ${m.invalid})`).join(" · ") || "no calls recorded yet"}
                </dd>
                <dt>Scoring overrides</dt><dd>{quality.screening_overrides} of {quality.scores_total} scores ({Math.round((quality.override_rate || 0) * 100)}%)</dd>
                <dt>Gate approvals / returns</dt><dd>{quality.gate_approvals} / {quality.gate_returns}</dd>
                <dt>Human approval rate</dt><dd>{Math.round((quality.gate_approval_rate || 0) * 100)}%</dd>
                <dt>Bids decided</dt><dd>{quality.outcomes_total}</dd>
                <dt>Win rate</dt>
                <dd>
                  {quality.outcomes_total
                    ? `${Math.round((quality.win_rate || 0) * 100)}% (${quality.outcomes_won} won / ${quality.outcomes_lost} lost)`
                    : "no outcomes recorded yet"}
                </dd>
                <dt>Avg score — won vs lost</dt>
                <dd>
                  {quality.calibration?.avg_score_won !== null && quality.calibration?.avg_score_won !== undefined
                    ? `${quality.calibration.avg_score_won} vs ${quality.calibration.avg_score_lost ?? "n/a"}`
                    : "not enough outcomes yet"}
                </dd>
                <dt>Extraction grades</dt>
                <dd>
                  {Object.entries(quality.extraction_grades || {}).map(([g, n]) => `${g}: ${n}`).join(" · ") || "—"}
                </dd>
                <dt>Proposal sections with gaps</dt>
                <dd>{quality.proposal_sections_with_gaps} of {quality.proposal_sections_total}</dd>
              </div>
              {quality.score_band_performance?.length ? (
                <div className="mt-14">
                  <h4 className="muted" style={{ marginBottom: 6 }}>Score band vs outcome</h4>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Band</th><th>Decided</th><th>Won</th><th>Win rate</th></tr></thead>
                      <tbody>
                        {quality.score_band_performance.map((b) => (
                          <tr key={b.band}>
                            <td data-label="Band">{b.band}</td>
                            <td data-label="Decided">{b.decided}</td>
                            <td data-label="Won">{b.wins}</td>
                            <td data-label="Win rate">{b.decided ? `${Math.round(b.win_rate * 100)}%` : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
              {quality.loss_reasons?.length ? (
                <div className="mt-14">
                  <h4 className="muted" style={{ marginBottom: 6 }}>Why bids were lost</h4>
                  <ul className="muted" style={{ fontSize: 13 }}>
                    {quality.loss_reasons.map((r) => <li key={r.reason}>{r.reason} — {r.count}</li>)}
                  </ul>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted">Not available.</p>
          )}
        </div>
        <div className="card">
          <h3>
            Extraction accuracy (gold set){" "}
            <button className="btn small" onClick={runEvaluation} disabled={evalBusy}>
              {evalBusy ? "Running…" : "Run evaluation"}
            </button>
          </h3>
          {evaluation ? (
            <>
              <div className="kv">
                <dt>Cases passed</dt>
                <dd>{evaluation.cases_passed} / {evaluation.cases_total}</dd>
                <dt>Case accuracy</dt><dd>{pct(evaluation.case_accuracy)}</dd>
                <dt>Micro accuracy (all fields)</dt><dd>{pct(evaluation.micro_accuracy)}</dd>
                <dt>Macro F1</dt><dd>{pct(evaluation.macro_f1)}</dd>
                <dt>Risk-flag recall</dt><dd>{pct(evaluation.risk_recall)}</dd>
              </div>
              <div className="table-wrap mt-14" style={{ maxHeight: 280, overflowY: "auto" }}>
                <table>
                  <thead><tr><th>Field</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
                  <tbody>
                    {Object.entries(evaluation.fields || {}).map(([field, d]) => (
                      <tr key={field}>
                        <td data-label="Field">{field}</td>
                        <td data-label="Precision">{pct(d.precision)}</td>
                        <td data-label="Recall">{pct(d.recall)}</td>
                        <td data-label="F1">{pct(d.f1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted mt-14" style={{ fontSize: 12 }}>
                Runs against a throwaway database, so it never touches live data. The gold set is a
                regression baseline — a production accuracy claim needs a gold set built from AHTE&apos;s
                own historical tender packages.
              </p>
            </>
          ) : (
            <p className="muted">Run the evaluation to measure extraction accuracy against the labelled gold set.</p>
          )}
        </div>
        <div className="card">
          <h3>Audit trail <button className="btn small" onClick={downloadAudit}>Download CSV</button></h3>
          <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}>
            <table>
              <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td data-label="When">{fmtDateTime(a.created_at)}</td>
                    <td data-label="Actor">{a.actor}</td>
                    <td data-label="Action">{a.action}{a.opportunity_id ? ` #${a.opportunity_id}` : ""}</td>
                    <td data-label="Detail" className="muted long-value">{a.detail ? JSON.stringify(a.detail).slice(0, 140) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <h3>
            Daily digest{" "}
            <button className="btn small" onClick={previewDigest} disabled={digestBusy}>
              {digestBusy ? "Working…" : "Preview"}
            </button>{" "}
            <button className="btn small primary" onClick={sendDigestNow} disabled={digestBusy}>
              Send now
            </button>
          </h3>
          <p className="muted">
            The ranked executive brief — the tenders worth attention, the ones closing soon, and the
            gate counts. It is sent to the configured recipients every morning by the scheduler; this
            checks what it says and that email delivery works.
          </p>
          {digestPreview ? <pre className="muted" style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{digestPreview}</pre> : null}
        </div>
      </div>
    </>
  );
}

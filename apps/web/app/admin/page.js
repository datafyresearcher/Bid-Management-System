"use client";

import { useCallback, useEffect, useState } from "react";
import { api, clearSession, fmtDateTime, getToken } from "../../lib/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AdminPage() {
  const [users, setUsers] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [quality, setQuality] = useState(null);
  const [audit, setAudit] = useState([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [userForm, setUserForm] = useState({ email: "", name: "", role: "bid_manager", password: "" });
  const [mapForm, setMapForm] = useState({ source_code: "", source_category: "", internal_category: "" });

  const load = useCallback(() => {
    api("/api/admin/users").then(setUsers).catch((e) => setError(e.message));
    api("/api/admin/category-mappings").then(setMappings).catch(() => setMappings([]));
    api("/api/admin/ai-quality").then(setQuality).catch(() => setQuality(null));
    api("/api/admin/audit?limit=150").then(setAudit).catch(() => setAudit([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
                    <td>{u.name}</td>
                    <td>{u.email}</td>
                    <td>{u.role}</td>
                    <td>
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
                    <td>{m.source_code}</td>
                    <td>{m.source_category}</td>
                    <td>{m.internal_category}</td>
                    <td>
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
                <dt>LLM calls by task</dt>
                <dd>
                  {Object.entries(quality.llm_by_task || {}).map(([task, m]) => `${task}: ${m.calls} (invalid ${m.invalid})`).join(" · ") || "none (deterministic mode)"}
                </dd>
                <dt>Scoring overrides</dt><dd>{quality.screening_overrides} of {quality.scores_total} scores ({Math.round((quality.override_rate || 0) * 100)}%)</dd>
                <dt>Gate approvals / returns</dt><dd>{quality.gate_approvals} / {quality.gate_returns}</dd>
                <dt>Human approval rate</dt><dd>{Math.round((quality.gate_approval_rate || 0) * 100)}%</dd>
              </div>
            </>
          ) : (
            <p className="muted">Not available.</p>
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
                    <td>{fmtDateTime(a.created_at)}</td>
                    <td>{a.actor}</td>
                    <td>{a.action}{a.opportunity_id ? ` #${a.opportunity_id}` : ""}</td>
                    <td className="muted">{a.detail ? JSON.stringify(a.detail).slice(0, 140) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

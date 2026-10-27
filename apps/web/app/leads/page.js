"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, cacheGet, cacheSet, fmtMoney } from "../../lib/api";
import BrandLoader from "../../components/Loading";

export default function LeadsPage() {
  const router = useRouter();
  const [leads, setLeads] = useState([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const hydrated = useRef(false);
  const [form, setForm] = useState({
    title: "", buyer: "", category_internal: "Substations", area: "Punjab",
    expected_window: "", estimated_value: "", confidence_tier: "Medium", source_label: "Manual entry",
  });

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    const url = `/api/leads?${params.toString()}`;
    if (!hydrated.current) {
      const cached = cacheGet(url);
      if (cached) {
        setLeads(cached.items);
        setTotal(cached.total);
        setLoading(false);
      }
      hydrated.current = true;
    }
    api(url)
      .then((data) => {
        setLeads(data.items);
        setTotal(data.total);
        cacheSet(url, data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [status, q]);

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

  const createLead = () =>
    act(
      () => api("/api/leads", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          estimated_value: form.estimated_value ? Number(form.estimated_value) : null,
        }),
      }),
      "Lead created"
    );

  const convert = (lead) =>
    act(async () => {
      const result = await api(`/api/leads/${lead.id}/convert`, { method: "POST" });
      router.push(`/opportunities/${result.opportunity_id}`);
    }, "Lead converted");

  if (loading && !error) return <BrandLoader />;

  return (
    <>
      <h2 className="page-title">Leads Radar</h2>
      <p className="page-sub">Pre-tender intelligence: annual plans, budget signals and email inbox harvest. Converted leads auto-link to published tenders.</p>

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      <div className="filters">
        <div className="grow">
          <label>Search</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="title or buyer" />
        </div>
        <div>
          <label>Status</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option value="Signal">Signal</option>
            <option value="Qualified">Qualified</option>
            <option value="Tracking">Tracking</option>
            <option value="Converted">Converted</option>
            <option value="Dropped">Dropped</option>
          </select>
        </div>
        <button className="btn" disabled={busy} onClick={() => act(() => api("/api/leads/import/annual-plan", { method: "POST" }), "Annual plan import done")}>
          Import annual plan
        </button>
        <button className="btn" disabled={busy} onClick={() => act(() => api("/api/leads/import/email/email_plan", { method: "POST" }), "Email inbox import done")}>
          Import email inbox
        </button>
      </div>

      <div className="card mb-14">
        <h3>Add manual signal</h3>
        <div className="inline-form">
          <div className="wide">
            <label>Title</label>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div className="wide">
            <label>Buyer</label>
            <input value={form.buyer} onChange={(e) => setForm({ ...form, buyer: e.target.value })} />
          </div>
          <div>
            <label>Category</label>
            <select value={form.category_internal} onChange={(e) => setForm({ ...form, category_internal: e.target.value })}>
              {["Substations", "Transmission Lines", "Renewable Energy", "Civil Infrastructure", "Supply / Goods", "Services", "General"].map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label>Area</label>
            <input value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} />
          </div>
          <div>
            <label>Window</label>
            <input value={form.expected_window} onChange={(e) => setForm({ ...form, expected_window: e.target.value })} placeholder="Q3 FY2026-27" />
          </div>
          <div>
            <label>Value (PKR)</label>
            <input value={form.estimated_value} onChange={(e) => setForm({ ...form, estimated_value: e.target.value })} />
          </div>
          <div>
            <label>Confidence</label>
            <select value={form.confidence_tier} onChange={(e) => setForm({ ...form, confidence_tier: e.target.value })}>
              <option>High</option><option>Medium</option><option>Low</option>
            </select>
          </div>
          <button className="btn primary" disabled={busy || !form.title} onClick={createLead}>Add lead</button>
        </div>
      </div>

      <p className="muted mb-14">{total} lead(s)</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Signal</th><th>Buyer</th><th>Area</th><th>Window</th><th>Value</th><th>Confidence</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {leads.map((l) => (
              <tr key={l.id}>
                <td data-label="Signal">
                  {l.title.slice(0, 90)}
                  <div className="muted">{l.source_code} · {l.source_label}</div>
                </td>
                <td data-label="Buyer">{l.buyer}</td>
                <td data-label="Area">{l.area}</td>
                <td data-label="Window">{l.expected_window || "—"}</td>
                <td data-label="Value">{fmtMoney(l.estimated_value, l.currency)}</td>
                <td data-label="Confidence">{l.confidence_tier}<div className="muted">{l.confidence_note}</div></td>
                <td data-label="Status">
                  <select
                    value={l.status}
                    disabled={busy || l.status === "Converted"}
                    onChange={(e) => act(() => api(`/api/leads/${l.id}/status`, { method: "POST", body: JSON.stringify({ status: e.target.value }) }), "Status updated")}
                  >
                    {["Signal", "Qualified", "Tracking", "Converted", "Dropped"].map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td data-label="">
                  <div className="row-actions">
                    {l.status !== "Converted" ? (
                      <button className="btn small primary" disabled={busy} onClick={() => convert(l)}>Convert & score</button>
                    ) : (
                      <a className="btn small" href={`/opportunities/${l.converted_opportunity_id}`}>View bid</a>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {leads.length === 0 ? <tr><td colSpan="8" data-label="" className="muted">No leads.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </>
  );
}

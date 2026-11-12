"use client";

import { useCallback, useEffect, useState } from "react";
import { api, cacheGet, cacheSet, fmtMoney } from "../../lib/api";import BrandLoader from "../../components/Loading";

const TABS = [
  ["company", "Company"],
  ["licenses", "Licences"],
  ["financials", "Financial Years"],
  ["projects", "Projects"],
  ["personnel", "Personnel"],
  ["equipment", "Equipment"],
  ["certificates", "Certificates"],
  ["shared", "Shared documents"],
  ["library", "Reference library"],
];

/** The reader-facing name of each summary card. */
const SUMMARY_LABELS = {
  licenses: "PEC licences",
  financial_years: "Financial years",
  projects: "Projects",
  personnel: "Personnel",
  equipment: "Plant & equipment",
  certificates: "Certificates",
  library: "Reference library",
};

export default function KbPage() {
  const [summary, setSummary] = useState(null);
  const [tab, setTab] = useState("company");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  const loadSummary = useCallback(() => {
    const cached = cacheGet("/api/kb/summary");
    if (cached) setSummary(cached);
    api("/api/kb/summary")
      .then((data) => {
        setSummary(data);
        cacheSet("/api/kb/summary", data);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  return (
    <>
      <h2 className="page-title">Knowledge Base</h2>
      <p className="page-sub">Single source of truth for company evidence. Only approved records are used by scoring and drafting.</p>

      {error ? <div className="notice err">{error}</div> : null}
      {info ? <div className="notice ok">{info}</div> : null}

      {summary ? (
        <div className="grid cols-4 mb-14">
          {Object.entries(summary).filter(([k]) => k !== "company").map(([key, val]) => (
            <div className="card" key={key}>
              <h3>{SUMMARY_LABELS[key] || key.replace("_", " ")}</h3>
              <div className="metric">{val.approved}<small>of {val.total} approved</small></div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>

      {tab === "company" ? <CompanyTab setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "licenses" ? <LicensesTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "financials" ? <FinancialsTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "projects" ? <ProjectsTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "personnel" ? <PersonnelTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "equipment" ? <EquipmentTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "certificates" ? <CertificatesTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "shared" ? <SharedDocumentsTab setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
      {tab === "library" ? <LibraryTab loadSummary={loadSummary} setInfo={setInfo} setError={setError} setBusy={setBusy} busy={busy} /> : null}
    </>
  );
}

function useCrud(path, loadSummary, setInfo, setError, setBusy) {
  const [rows, setRows] = useState([]);
  const load = useCallback(() => {
    api(path).then(setRows).catch((e) => setError(e.message));
  }, [path, setError]);
  useEffect(() => {
    load();
  }, [load]);

  const create = async (payload, message) => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await api(path, { method: "POST", body: JSON.stringify(payload) });
      setInfo(message);
      load();
      if (loadSummary) loadSummary();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const approve = async (id, approved) => {
    setBusy(true);
    try {
      await api(`${path}/${id}/approve`, { method: "POST", body: JSON.stringify({ approved }) });
      load();
      if (loadSummary) loadSummary();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return { rows, load, create, approve };
}

function CompanyTab({ setInfo, setError, setBusy, busy }) {
  const [form, setForm] = useState(null);
  useEffect(() => {
    const url = "/api/kb/company";
    const cached = cacheGet(url);
    if (cached) setForm(cached);
    api(url)
      .then((data) => {
        const value = data && data.id ? data : {
          name: "", legal_name: "", secp: "", ntn: "", tax_status: "Active", address: "", website: "", summary: "", blacklisted: false,
        };
        setForm(value);
        cacheSet(url, value);
      })
      .catch((e) => setError(e.message));
  }, [setError]);

  if (!form) return <BrandLoader />;

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/api/kb/company", { method: "PUT", body: JSON.stringify(form) });
      setInfo("Company profile saved");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="grid cols-2">
        <div><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div><label>Legal name</label><input value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} /></div>
        <div><label>SECP</label><input value={form.secp} onChange={(e) => setForm({ ...form, secp: e.target.value })} /></div>
        <div><label>NTN</label><input value={form.ntn} onChange={(e) => setForm({ ...form, ntn: e.target.value })} /></div>
        <div><label>Tax status</label><input value={form.tax_status} onChange={(e) => setForm({ ...form, tax_status: e.target.value })} /></div>
        <div><label>Website</label><input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} /></div>
        <div><label>Address</label><input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
        <div>
          <label>Blacklisted</label>
          <select value={form.blacklisted ? "yes" : "no"} onChange={(e) => setForm({ ...form, blacklisted: e.target.value === "yes" })}>
            <option value="no">No</option><option value="yes">Yes</option>
          </select>
        </div>
      </div>
      <label>Summary</label>
      <textarea value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
      <div className="mt-14">
        <button className="btn primary" disabled={busy || !form.name} onClick={save}>Save profile</button>
      </div>
    </div>
  );
}

function LicensesTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/licenses", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ number: "", category: "C-A", fields: "" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add licence</h3>
        <div className="inline-form">
          <div><label>Number</label><input value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} /></div>
          <div>
            <label>Category</label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {["C-A", "No Limit", "C-B", "C-1", "C-2", "C-3", "C-4"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="wide"><label>Fields (comma separated)</label><input value={form.fields} onChange={(e) => setForm({ ...form, fields: e.target.value })} /></div>
          <button className="btn primary" disabled={props.busy || !form.number} onClick={() => create({ ...form, fields: form.fields.split(",").map((s) => s.trim()).filter(Boolean) }, "Licence added")}>Add</button>
        </div>
      </div>
      <Table rows={rows} approve={approve} cols={["number", "category", "fields"]} busy={props.busy} />
    </>
  );
}

function FinancialsTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/financial-years", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ fiscal_year: "", turnover: "", net_worth: "", profit: "", auditor: "" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add financial year</h3>
        <div className="inline-form">
          <div><label>Fiscal year</label><input value={form.fiscal_year} onChange={(e) => setForm({ ...form, fiscal_year: e.target.value })} placeholder="2025-26" /></div>
          <div><label>Turnover (PKR)</label><input value={form.turnover} onChange={(e) => setForm({ ...form, turnover: e.target.value })} /></div>
          <div><label>Net worth</label><input value={form.net_worth} onChange={(e) => setForm({ ...form, net_worth: e.target.value })} /></div>
          <div><label>Profit</label><input value={form.profit} onChange={(e) => setForm({ ...form, profit: e.target.value })} /></div>
          <div><label>Auditor</label><input value={form.auditor} onChange={(e) => setForm({ ...form, auditor: e.target.value })} /></div>
          <button
            className="btn primary"
            disabled={props.busy || !form.fiscal_year}
            onClick={() => create({
              ...form,
              turnover: Number(form.turnover || 0),
              net_worth: Number(form.net_worth || 0),
              profit: Number(form.profit || 0),
            }, "Financial year added")}
          >
            Add
          </button>
        </div>
      </div>
      <Table rows={rows} approve={approve} cols={["fiscal_year", "turnover", "net_worth", "auditor"]} moneyCols={["turnover", "net_worth"]} busy={props.busy} />
    </>
  );
}

function ProjectsTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/projects", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ contract_no: "", client: "", category: "Substations", value: "", area: "Punjab", start_date: "", end_date: "", role: "Sole", funding_source: "" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add project experience</h3>
        <div className="inline-form">
          <div><label>Contract no</label><input value={form.contract_no} onChange={(e) => setForm({ ...form, contract_no: e.target.value })} /></div>
          <div className="wide"><label>Client</label><input value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} /></div>
          <div>
            <label>Category</label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {["Substations", "Transmission Lines", "Renewable Energy", "Civil Infrastructure", "Transport Infrastructure", "Supply / Goods", "Services"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div><label>Value (PKR)</label><input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} /></div>
          <div><label>Area</label><input value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} /></div>
          <div><label>Start</label><input value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} placeholder="2022" /></div>
          <div><label>End</label><input value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} placeholder="2025" /></div>
          <button className="btn primary" disabled={props.busy || !form.contract_no} onClick={() => create({ ...form, value: Number(form.value || 0) }, "Project added")}>Add</button>
        </div>
      </div>
      <Table rows={rows} approve={approve} cols={["contract_no", "client", "category", "value", "role"]} moneyCols={["value"]} busy={props.busy} />
    </>
  );
}

function PersonnelTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/personnel", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ name: "", position: "", pec_reg_no: "", years_experience: "", availability: "Available" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add personnel</h3>
        <div className="inline-form">
          <div className="wide"><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label>Position</label><input value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} /></div>
          <div><label>PEC reg no</label><input value={form.pec_reg_no} onChange={(e) => setForm({ ...form, pec_reg_no: e.target.value })} /></div>
          <div><label>Experience (yrs)</label><input value={form.years_experience} onChange={(e) => setForm({ ...form, years_experience: e.target.value })} /></div>
          <button className="btn primary" disabled={props.busy || !form.name} onClick={() => create({ ...form, years_experience: Number(form.years_experience || 0) }, "Personnel added")}>Add</button>
        </div>
      </div>
      <Table rows={rows} approve={approve} cols={["name", "position", "pec_reg_no", "years_experience", "availability"]} busy={props.busy} />
    </>
  );
}

function EquipmentTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/equipment", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ name: "", category: "", quantity: "1", ownership: "Owned", condition: "Good" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add equipment</h3>
        <div className="inline-form">
          <div className="wide"><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label>Category</label><input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></div>
          <div><label>Qty</label><input value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></div>
          <div>
            <label>Ownership</label>
            <select value={form.ownership} onChange={(e) => setForm({ ...form, ownership: e.target.value })}>
              <option>Owned</option><option>Leased</option><option>Rented</option>
            </select>
          </div>
          <button className="btn primary" disabled={props.busy || !form.name} onClick={() => create({ ...form, quantity: Number(form.quantity || 1) }, "Equipment added")}>Add</button>
        </div>
      </div>
      <Table rows={rows} approve={approve} cols={["name", "category", "quantity", "ownership", "condition"]} busy={props.busy} />
    </>
  );
}

function CertificatesTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/certificates", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ name: "", issuer: "", number: "", expires_at: "" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add certificate</h3>
        <div className="inline-form">
          <div className="wide"><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label>Issuer</label><input value={form.issuer} onChange={(e) => setForm({ ...form, issuer: e.target.value })} /></div>
          <div><label>Number</label><input value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} /></div>
          <div><label>Expires</label><input value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} placeholder="2027-12-31" /></div>
          <button className="btn primary" disabled={props.busy || !form.name} onClick={() => create(form, "Certificate added")}>Add</button>
        </div>
      </div>
      <Table rows={rows} approve={approve} cols={["name", "issuer", "number", "expires_at"]} busy={props.busy} />
    </>
  );
}

function LibraryTab(props) {
  const { rows, create, approve } = useCrud("/api/kb/library", props.loadSummary, props.setInfo, props.setError, props.setBusy);
  const [form, setForm] = useState({ title: "", type: "policy", tags: "", content_text: "" });
  return (
    <>
      <div className="card mb-14">
        <h3>Add a reference document</h3>
        <p className="muted">
          Reference material the system reads when it drafts — policies, procedures, manuals. This
          is not where the evidence every proposal carries goes; that belongs under Shared documents.
        </p>
        <div className="inline-form">
          <div className="wide"><label>Title</label><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
          <div><label>Type</label><input value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} /></div>
          <div className="wide"><label>Tags</label><input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></div>
          <button className="btn primary" disabled={props.busy || !form.title} onClick={() => create(form, "Library document added")}>Add</button>
        </div>
        <label>Content</label>
        <textarea value={form.content_text} onChange={(e) => setForm({ ...form, content_text: e.target.value })} />
      </div>
      <Table rows={rows} approve={approve} cols={["title", "type", "tags"]} busy={props.busy} />
    </>
  );
}

/**
 * The shared documents — the evidence every proposal carries.
 *
 * These are held once here instead of being uploaded for each tender. A
 * locked one is the master copy: it can only be changed or removed from
 * here, never from inside a proposal, so no bid is built on a document
 * somebody changed on the way past.
 */
function SharedDocumentsTab(props) {
  const [rows, setRows] = useState([]);
  const [categories, setCategories] = useState([]);
  const [form, setForm] = useState({
    title: "",
    category: "PEC certificate",
    type: "evidence",
    tags: "",
    content_text: "",
    locked: false,
    valid_until: "",
  });
  const [files, setFiles] = useState({});

  const load = useCallback(() => {
    api("/api/kb/shared")
      .then((data) => {
        setRows(data.documents || []);
        setCategories(data.categories || []);
      })
      .catch((e) => props.setError(e.message));
  }, [props.setError]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (fn, message) => {
    props.setBusy(true);
    props.setError("");
    props.setInfo("");
    try {
      await fn();
      props.setInfo(message);
      load();
    } catch (e) {
      props.setError(e.message);
    } finally {
      props.setBusy(false);
    }
  };

  const create = () =>
    run(
      () => api("/api/kb/shared", { method: "POST", body: JSON.stringify(form) }),
      "Shared document added"
    );

  const uploadFile = (id, file) => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    return run(
      () => api(`/api/kb/shared/${id}/file`, { method: "POST", body }),
      "File attached"
    );
  };

  const toggleLock = (doc) =>
    run(
      () =>
        api(`/api/kb/shared/${doc.id}`, {
          method: "PUT",
          body: JSON.stringify({
            title: doc.title,
            category: doc.category,
            type: doc.type,
            tags: doc.tags,
            content_text: "",
            shared: doc.shared,
            locked: !doc.locked,
            approved: doc.approved,
            valid_until: doc.valid_until,
          }),
        }),
      doc.locked ? "Unlocked — it can now be left out of a proposal" : "Locked — it now travels with every proposal"
    );

  const remove = (doc) => {
    if (!window.confirm(`Remove “${doc.title}” from the knowledge base?`)) return;
    return run(() => api(`/api/kb/shared/${doc.id}`, { method: "DELETE" }), "Shared document removed");
  };

  return (
    <>
      <div className="card mb-14">
        <h3>Add a shared document</h3>
        <p className="muted">
          Evidence the bid team attaches to the proposals it writes — the PEC certificate, the
          procurement forms, the financial predictions, the credit line certificate. It is kept once
          here rather than uploaded for every tender.
        </p>
        <div className="inline-form">
          <div className="wide">
            <label>Title</label>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div>
            <label>Type</label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {categories.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label>Valid until</label>
            <input value={form.valid_until} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} placeholder="2027-12-31" />
          </div>
          <div className="wide">
            <label>Tags</label>
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </div>
          <div className="wide">
            <label>Locked master copy</label>
            <select value={form.locked ? "yes" : "no"} onChange={(e) => setForm({ ...form, locked: e.target.value === "yes" })}>
              <option value="no">No — can be left out of a proposal</option>
              <option value="yes">Yes — always travels with the proposal</option>
            </select>
          </div>
          <button className="btn primary" disabled={props.busy || !form.title} onClick={create}>
            Add
          </button>
        </div>
        <label>Notes</label>
        <textarea value={form.content_text} onChange={(e) => setForm({ ...form, content_text: e.target.value })} />
      </div>

      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Type</th>
                <th>File</th>
                <th>Valid until</th>
                <th>Locked</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((doc) => (
                <tr key={doc.id}>
                  <td data-label="Document">
                    {doc.title}
                    <div className="muted">{doc.tags}</div>
                  </td>
                  <td data-label="Type">{doc.category}</td>
                  <td data-label="File">
                    <label className="sr-only">Attach a file to {doc.title}</label>
                    <input
                      type="file"
                      onChange={(e) => uploadFile(doc.id, e.target.files && e.target.files[0])}
                      disabled={props.busy}
                    />
                    {doc.has_file ? <div className="muted">A file is attached</div> : null}
                  </td>
                  <td data-label="Valid until">{doc.valid_until || "—"}</td>
                  <td data-label="Locked">
                    <button className={doc.locked ? "btn small primary" : "btn small"} disabled={props.busy} onClick={() => toggleLock(doc)}>
                      {doc.locked ? "Locked" : "Not locked"}
                    </button>
                  </td>
                  <td data-label="">
                    <div className="row-actions">
                      {doc.has_file ? (
                        <a className="btn small" href={`/api/kb/shared/${doc.id}/download`} target="_blank" rel="noreferrer noopener">
                          Open
                        </a>
                      ) : null}
                      <button className="btn small danger" disabled={props.busy} onClick={() => remove(doc)}>
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 ? <tr><td colSpan="6" data-label="" className="muted">No shared documents yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Table({ rows, approve, cols, moneyCols = [], busy }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {cols.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}
            <th>Approved</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {cols.map((c) => (
                <td key={c} data-label={c.replace(/_/g, " ")}>
                  {moneyCols.includes(c) ? fmtMoney(row[c]) : Array.isArray(row[c]) ? row[c].join(", ") : String(row[c] ?? "—")}
                </td>
              ))}
              <td data-label="Approved">
                <button className={row.approved ? "btn small primary" : "btn small"} disabled={busy} onClick={() => approve(row.id, !row.approved)}>
                  {row.approved ? "approved" : "pending"}
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 ? <tr><td colSpan={cols.length + 1} data-label="" className="muted">No records.</td></tr> : null}
        </tbody>
      </table>
    </div>
  );
}

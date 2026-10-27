"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, daysTo, fmtDate, fmtMoney, stateClass } from "../../lib/api";
import { ListSkeleton } from "../../components/Loading";

const FILTERS = [
  ["GATE1,GATE2,GATE3,GATE4,GATE5,DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT,SUBMITTED,EVALUATION", "Active pipeline"],
  ["GATE1,GATE2,GATE3,GATE4,GATE5", "Awaiting decisions"],
  ["DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT", "In preparation"],
  ["SUBMITTED,EVALUATION", "Submitted / evaluation"],
  ["WON,LOST,REJECTED,ABANDONED", "Closed"],
  ["", "Everything"],
];

export default function PipelinePage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [state, setState] = useState(FILTERS[0][0]);
  const [sort, setSort] = useState("deadline");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      sort,
    });
    if (state) params.set("state", state);
    api(`/api/opportunities?${params.toString()}`)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [state, sort, page, pageSize]);

  // A new filter is a new view, so it starts at the first page.
  useEffect(() => {
    setPage(1);
  }, [state, sort, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  const groups = items.reduce((acc, o) => {
    const key = o.state;
    if (!acc[key]) acc[key] = [];
    acc[key].push(o);
    return acc;
  }, {});

  if (loading && !error) {
    return (
      <ListSkeleton
        title="Bid Pipeline"
        sub="Opportunities by workflow state. Each gate requires a human decision before the next step."
      />
    );
  }

  return (
    <>
      <h2 className="page-title">Bid Pipeline</h2>
      <p className="page-sub">Opportunities by workflow state. Each gate requires a human decision before the next step.</p>

      {error ? <div className="notice err">{error}</div> : null}

      <div className="filters">
        <div>
          <label>View</label>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            {FILTERS.map(([value, label]) => (
              <option key={label} value={value}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Sort by</label>
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="deadline">Deadline</option>
            <option value="score">Score</option>
            <option value="created">Newest</option>
          </select>
        </div>
        <button className="btn" onClick={load}>Refresh</button>
        <span className="muted">{total} item(s)</span>
      </div>

      {total > 0 ? (
        <div className="pager">
          <p className="muted mb-14">Showing {first}–{last} of {total} item(s).</p>
          <div className="row-actions">
            <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
              ← Previous
            </button>
            <span className="muted">
              Page {page} of {pages}
            </span>
            <button className="btn" disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>
              Next →
            </button>
            {page < pages ? (
              <button className="btn" onClick={() => setPage(pages)}>
                Last page
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {Object.keys(groups).length === 0 ? <p className="muted">Nothing in this view.</p> : null}

      {Object.entries(groups).map(([groupState, groupItems]) => (
        <div key={groupState} className="mt-14">
          <h3 className="mb-14">
            <span className={stateClass(groupState)}>{groupState}</span>{" "}
            <span className="muted">{groupItems.length}</span>
          </h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Tender</th>
                  <th>Buyer</th>
                  <th>Value</th>
                  <th>Deadline</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {groupItems.map((o) => {
                  const d = daysTo(o.submission_deadline);
                  return (
                    <tr key={o.id}>
                      <td data-label="Tender"><Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 90)}</Link></td>
                      <td data-label="Buyer">{o.buyer_name}<div className="muted">{o.area}</div></td>
                      <td data-label="Value">{fmtMoney(o.estimated_value, o.currency)}</td>
                      <td data-label="Deadline" className={d !== null && d <= 7 ? "score-mid" : ""}>
                        {fmtDate(o.submission_deadline)}
                        {d !== null ? <div className="muted">{d}d left</div> : null}
                      </td>
                      <td data-label="Score">{o.score_total !== null && o.score_total !== undefined ? Math.round(o.score_total) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}

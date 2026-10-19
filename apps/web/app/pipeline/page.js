"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, daysTo, fmtDate, fmtMoney, stateClass } from "../../lib/api";

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
  const [state, setState] = useState(FILTERS[0][0]);
  const [sort, setSort] = useState("deadline");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    params.set("sort", sort);
    params.set("page_size", "100");
    api(`/api/opportunities?${params.toString()}`)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e.message));
  }, [state, sort]);

  useEffect(() => {
    load();
  }, [load]);

  const groups = items.reduce((acc, o) => {
    const key = o.state;
    if (!acc[key]) acc[key] = [];
    acc[key].push(o);
    return acc;
  }, {});

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
                      <td><Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 90)}</Link></td>
                      <td>{o.buyer_name}<div className="muted">{o.area}</div></td>
                      <td>{fmtMoney(o.estimated_value, o.currency)}</td>
                      <td className={d !== null && d <= 7 ? "score-mid" : ""}>
                        {fmtDate(o.submission_deadline)}
                        {d !== null ? <div className="muted">{d}d left</div> : null}
                      </td>
                      <td>{o.score_total !== null && o.score_total !== undefined ? Math.round(o.score_total) : "—"}</td>
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

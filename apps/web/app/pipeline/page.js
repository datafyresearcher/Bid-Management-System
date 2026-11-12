"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, cacheGet, cacheSet, daysTo, fmtDate, fmtMoney, stateClass, stateLabel } from "../../lib/api";
import BrandLoader from "../../components/Loading";

/**
 * The views on the pipeline.
 *
 * `deadline` narrows the list by whether the bidding window is still open.
 * A tender whose submission date has passed cannot be bid, so it is kept
 * out of the working views and shown on its own — but it stays on file and
 * stays reachable, which is what the bidding team asked for.
 */
const FILTERS = [
  {
    label: "Active pipeline",
    states: "GATE1,GATE2,GATE3,GATE4,GATE5,DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT",
    deadline: "open",
  },
  { label: "Awaiting a decision", states: "GATE1,GATE2,GATE3,GATE4,GATE5", deadline: "open" },
  {
    label: "In preparation",
    states: "DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT",
    deadline: "open",
  },
  { label: "Submitted / under evaluation", states: "SUBMITTED,EVALUATION", deadline: "" },
  { label: "Closed — decided", states: "WON,LOST,REJECTED,ABANDONED", deadline: "" },
  { label: "Past deadline", states: "", deadline: "expired" },
  { label: "Everything", states: "", deadline: "" },
];

export default function PipelinePage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [filterIndex, setFilterIndex] = useState(0);
  const [sort, setSort] = useState("deadline");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const hydrated = useRef(false);

  const filter = FILTERS[filterIndex];

  const load = useCallback(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      sort,
    });
    if (filter.states) params.set("state", filter.states);
    if (filter.deadline) params.set("deadline", filter.deadline);
    const url = `/api/opportunities?${params.toString()}`;
    if (!hydrated.current) {
      const cached = cacheGet(url);
      if (cached) {
        setItems(cached.items);
        setTotal(cached.total);
        setLoading(false);
      }
      hydrated.current = true;
    }
    api(url)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
        cacheSet(url, data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filter, sort, page, pageSize]);

  // A new filter is a new view, so it starts at the first page.
  useEffect(() => {
    setPage(1);
  }, [filterIndex, sort, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  // The tenders are grouped by the stage they are sitting in. In the
  // everything view the ones whose date has passed are pulled out into
  // their own section, because they can no longer be bid, and the ones
  // whose bid was decided are pulled out too.
  const groups = [];
  const bucket = (title, note, rows) => {
    if (!rows.length) return;
    const byState = rows.reduce((acc, o) => {
      const key = o.state;
      if (!acc[key]) acc[key] = [];
      acc[key].push(o);
      return acc;
    }, {});
    groups.push({ title, note, byState });
  };

  const expired = items.filter((o) => o.deadline_status === "expired");
  const decided = items.filter((o) => o.deadline_status === "closed");
  const stillOpen = items.filter((o) => o.deadline_status === "open");

  if (filterIndex === FILTERS.length - 1) {
    bucket("Still open", null, stillOpen);
    bucket(
      "Past deadline",
      "The submission date has passed. These records stay on file and can still be opened.",
      expired
    );
    bucket("Closed", "The bid was decided.", decided);
  } else if (filter.deadline === "expired") {
    bucket("Past deadline", "The submission date has passed.", expired);
  } else {
    bucket(null, null, stillOpen);
  }

  if (loading && !error) return <BrandLoader />;

  return (
    <>
      <h2 className="page-title">Bid Pipeline</h2>
      <p className="page-sub">
        Every tender on file, by the stage it has reached. Each stage needs a person to decide
        before the bid moves on.
      </p>

      {error ? <div className="notice err">{error}</div> : null}

      <div className="filters">
        <div>
          <label>View</label>
          <select value={filterIndex} onChange={(e) => setFilterIndex(Number(e.target.value))}>
            {FILTERS.map((f, i) => (
              <option key={f.label} value={i}>{f.label}</option>
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

      {groups.length === 0 ? <p className="muted">Nothing in this view.</p> : null}

      {groups.map((group) => (
        <div key={group.title || "current"} className="mt-14">
          {group.title ? (
            <h3 className="mb-14">
              {group.title} <span className="muted">{group.note}</span>
            </h3>
          ) : null}
          {Object.entries(group.byState).map(([groupState, groupItems]) => (
            <div key={groupState} className="mb-14">
              <h4 className="mb-14">
                <span className={stateClass(groupState)}>{stateLabel(groupState)}</span>{" "}
                <span className="muted">{groupItems.length}</span>
              </h4>
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
                      const expired = o.deadline_status === "expired";
                      return (
                        <tr key={o.id}>
                          <td data-label="Tender">
                            <Link href={`/opportunities/${o.id}`}>{o.title.slice(0, 90)}</Link>
                            {expired ? <div className="muted">Past deadline</div> : null}
                          </td>
                          <td data-label="Buyer">{o.buyer_name}<div className="muted">{o.area}</div></td>
                          <td data-label="Value">{fmtMoney(o.estimated_value, o.currency)}</td>
                          <td data-label="Deadline" className={d !== null && d <= 7 ? "score-mid" : ""}>
                            {fmtDate(o.submission_deadline)}
                            {d !== null ? <div className="muted">{expired ? "closed" : `${d}d left`}</div> : null}
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
        </div>
      ))}
    </>
  );
}

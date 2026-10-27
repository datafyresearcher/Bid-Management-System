"use client";

/**
 * Branded loading states.
 *
 * Every slow moment in the portal shows the same visual language: the AHTE
 * mark inside a turning halo where a full screen is coming, and shimmering
 * placeholders shaped like the content they stand in for where a page's
 * layout is already known. Both are pure CSS so they paint instantly, before
 * any data answers.
 */

/** The page heading block, repeated by each skeleton so titles never jump. */
function SkeletonHeader({ title, sub }) {
  return (
    <>
      {title ? <h2 className="page-title">{title}</h2> : null}
      {sub ? <p className="page-sub">{sub}</p> : null}
    </>
  );
}

export function BrandLoader({ label = "Loading" }) {
  return (
    <div className="brand-loader" role="status" aria-live="polite">
      <span className="brand-loader-mark">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/ahte-logo.png" alt="" width="44" height="44" />
      </span>
      <span className="brand-loader-label">
        {label}
        <span className="brand-loader-dots" aria-hidden="true">
          <i>.</i>
          <i>.</i>
          <i>.</i>
        </span>
      </span>
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <>
      <SkeletonHeader title="Dashboard" sub="Live view of discovery, screening and gate activity." />
      <div className="grid cols-4 mb-14">
        {[0, 1, 2, 3].map((i) => (
          <div className="card" key={i}>
            <div className="skeleton sk-label" />
            <div className="skeleton sk-metric" />
          </div>
        ))}
      </div>
      <div className="grid cols-2">
        {[0, 1].map((i) => (
          <div className="card" key={i}>
            <div className="section-title">
              <div className="skeleton sk-label" />
              <div className="skeleton sk-btn" />
            </div>
            <Rows />
          </div>
        ))}
      </div>
      <div className="grid cols-2 mt-14">
        {[0, 1].map((i) => (
          <div className="card" key={i}>
            <div className="skeleton sk-label" />
            <Rows rows={4} />
          </div>
        ))}
      </div>
    </>
  );
}

export function ListSkeleton({ title, sub }) {
  return (
    <>
      <SkeletonHeader title={title} sub={sub} />
      <div className="skeleton sk-field" />
      <div className="card">
        <Rows rows={9} />
      </div>
    </>
  );
}

export function DetailSkeleton() {
  return (
    <>
      <div className="skeleton sk-title" />
      <div className="skeleton sk-sub" />
      <div className="card mt-14">
        <div className="skeleton sk-label" />
        <Rows rows={5} />
      </div>
      <div className="grid cols-2 mt-14">
        {[0, 1].map((i) => (
          <div className="card" key={i}>
            <div className="skeleton sk-label" />
            <Rows rows={3} />
          </div>
        ))}
      </div>
    </>
  );
}

export function FormSkeleton() {
  return (
    <div className="card">
      {[0, 1, 2].map((i) => (
        <div key={i} className="sk-form-row">
          <div className="skeleton sk-label" />
          <div className="skeleton sk-field" />
        </div>
      ))}
    </div>
  );
}

/** Shimmering rows standing in for table/list lines. */
function Rows({ rows = 7 }) {
  return (
    <div className="sk-rows">
      {Array.from({ length: rows }, (_, i) => (
        <div className="sk-row" key={i} style={{ width: `${96 - (i % 4) * 9}%` }} />
      ))}
    </div>
  );
}

"use client";

/**
 * Provenance strip shown against a tender record.
 *
 * A bid manager has to answer "where did this come from?" without leaving the
 * screen, so this renders the publishing authority, the portal it was taken
 * from, and the exact reference number that was captured. When the reference
 * resolves to a notice on the authority's own site, that link is offered.
 */

const TIER_CLASS = {
  P0: "badge badge-green",
  P1: "badge badge-blue",
  P2: "badge badge-gray",
};

export function tierClass(tier) {
  return TIER_CLASS[tier] || "badge badge-gray";
}

export function sourceHealthClass(health) {
  if (health === "ok") return "badge badge-green";
  if (health === "error") return "badge badge-red";
  return "badge badge-gray";
}

export function sourceLink(source) {
  if (!source) return "";
  return source.notice_url || source.listing_url || source.portal_url || "";
}

/** The label shown on the badge — the portal name, or the code if unnamed. */
export function sourceName(source) {
  if (!source) return "";
  return source.name || source.code || "";
}

export default function SourceTag({ source, showAuthority = false }) {
  if (!source) {
    return (
      <div className="src-tag">
        <span className="badge badge-gray">No source recorded</span>
      </div>
    );
  }

  const href = sourceLink(source);
  const name = sourceName(source);

  return (
    <div className="src-tag">
      <div className="src-line">
        <span className="badge badge-blue">{name}</span>
        {source.tier ? <span className={tierClass(source.tier)}>Tier {source.tier}</span> : null}
      </div>
      <div className="src-ref">
        {source.reference ? <span className="src-refno">Ref {source.reference}</span> : null}
        {href ? (
          <a className="src-link" href={href} target="_blank" rel="noreferrer noopener">
            Open notice ↗
          </a>
        ) : null}
      </div>
    </div>
  );
}

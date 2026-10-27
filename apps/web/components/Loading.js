"use client";

/**
 * The one loading state used everywhere in the portal: a rotating gradient
 * ring with "Please wait…" beneath it, centered in the content area — the
 * same visual language on the dashboard, every tab, and the sign-in flow.
 * Pure CSS (transform/opacity), so it paints instantly and costs nothing.
 */
export default function BrandLoader({ label = "Please wait" }) {
  return (
    <div className="brand-loader" role="status" aria-live="polite">
      <span className="brand-loader-ring" aria-hidden="true" />
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

"use client";

import { useEffect, useState } from "react";

const THEME_KEY = "bms_theme";

/**
 * Switch between the light and dark looks.
 *
 * The theme itself lives on <html data-theme> so the very first paint is
 * already correct (the inline boot script in the root layout sets it before
 * React runs); this control only flips that attribute and remembers the
 * choice for the next visit.
 */
export default function ThemeToggle({ className = "" }) {
  // null until mounted: render the light icon so server and client agree,
  // then correct it the moment the real theme is known.
  const [theme, setTheme] = useState(null);

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  }, []);

  const toggle = () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    // Brief global color transition, then remove it so scrolling stays cheap.
    root.classList.add("theme-switching");
    root.dataset.theme = next;
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // Private browsing may refuse storage; the choice just does not persist.
    }
    window.setTimeout(() => root.classList.remove("theme-switching"), 320);
    setTheme(next);
  };

  const dark = theme === "dark";

  return (
    <button
      type="button"
      className={`theme-toggle ${className}`}
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {dark ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4 17 7M7 17l-1.6 1.6" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20.4 14.2A8.6 8.6 0 0 1 9.8 3.6a8.6 8.6 0 1 0 10.6 10.6Z" />
        </svg>
      )}
      <span className="theme-toggle-label">{dark ? "Light" : "Dark"}</span>
    </button>
  );
}

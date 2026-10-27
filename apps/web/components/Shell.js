"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, getToken, getUser } from "../lib/api";
import ThemeToggle from "./ThemeToggle";
import { BrandLoader } from "./Loading";

const APP_TAGLINE = "AI Powered Bid Management System";
const COMPANY_NAME = "AL-Hussain Traders & Engineers PVT. LTD.";
const COMPANY_WEBSITE = "https://www.ahte.com.pk";
const COMPANY_EMAIL = "info@ahte.com.pk";

const NAV = [
  ["/", "Dashboard", "grid"],
  ["/inbox", "Tender Inbox", "inbox"],
  ["/pipeline", "Pipeline", "funnel"],
  ["/review", "Review Queue", "clipboard"],
  ["/leads", "Leads Radar", "radar"],
  ["/kb", "Knowledge Base", "book"],
  ["/admin", "Admin & Quality", "sliders"],
];

const ICON_PATHS = {
  grid: (
    <>
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.6" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6" />
    </>
  ),
  inbox: (
    <>
      <path d="M3 13.5h4.2l1.4 2.6h6.8l1.4-2.6H21" />
      <path d="M4.8 5.2h14.4l1.8 8.3v4.3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4.3l1.8-8.3Z" />
      <path d="M12 2.6v7.2" />
      <path d="m9.4 7.4 2.6 2.6 2.6-2.6" />
    </>
  ),
  funnel: (
    <>
      <path d="M3.2 4.8h17.6l-6.9 8.1v6.3l-3.8 1.9v-8.2L3.2 4.8Z" />
    </>
  ),
  clipboard: (
    <>
      <path d="M9 3.2h6v2.4H9V3.2Z" />
      <path d="M9 4.8H6.2A1.8 1.8 0 0 0 4.4 6.6v13a1.8 1.8 0 0 0 1.8 1.8h11.6a1.8 1.8 0 0 0 1.8-1.8v-13a1.8 1.8 0 0 0-1.8-1.8H15" />
      <path d="m8.6 13.2 2.4 2.4 4.4-4.8" />
    </>
  ),
  radar: (
    <>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="12" cy="12" r="3.1" />
      <path d="M12 1.8v3.1M12 19.1v3.1M1.8 12h3.1M19.1 12h3.1" />
    </>
  ),
  book: (
    <>
      <path d="M4 5.2A2.6 2.6 0 0 1 6.6 2.6H20v15.6H6.6A2.6 2.6 0 0 0 4 20.8V5.2Z" />
      <path d="M4 17.6a2.6 2.6 0 0 1 2.6-2.6H20" />
    </>
  ),
  sliders: (
    <>
      <path d="M3.5 7h8.2M16.2 7h4.3M3.5 12h3.4M11.4 12h9.1M3.5 17h9.4M17.4 17h3.1" />
      <circle cx="14" cy="7" r="2.4" />
      <circle cx="9.1" cy="12" r="2.4" />
      <circle cx="15.2" cy="17" r="2.4" />
    </>
  ),
};

function NavIcon({ name }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_PATHS[name]}
    </svg>
  );
}

export default function Shell({ children }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (pathname === "/login") {
      setReady(true);
      return;
    }
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    // Paint the shell immediately from the cached session and revalidate
    // against the API in the background. Waiting for /api/auth/me before
    // rendering a single pixel made every reload feel slower than it is;
    // the cached user is one page load old at worst, and the revalidation
    // below corrects name/role changes (a 401 clears the session and
    // returns to sign-in).
    const cached = getUser();
    if (cached) {
      setUser(cached);
      setReady(true);
    }
    api("/api/auth/me")
      .then((me) => {
        setUser(me);
        setReady(true);
      })
      .catch(() => {});
  }, [pathname, router]);

  // Navigating always closes the mobile drawer.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // While the drawer is open: Escape closes it and the page behind it does not scroll.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [menuOpen]);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!ready) {
    return (
      <div className="layout">
        <main className="main">
          <BrandLoader label="Preparing your workspace" />
        </main>
      </div>
    );
  }

  const logout = () => {
    clearSession();
    router.replace("/login");
  };

  return (
    <div className="layout">
      <header className="appbar">
        <button
          className="appbar-toggle"
          onClick={() => setMenuOpen(true)}
          aria-label="Open navigation"
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <span className="appbar-brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/ahte-logo.png" alt="" width="26" height="26" />
          <span>
            <strong>AHTE</strong> <span>BMS</span>
          </span>
        </span>
        <ThemeToggle className="appbar-theme" />
      </header>

      {menuOpen ? <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" /> : null}

      <aside className={menuOpen ? "sidebar open" : "sidebar"} id="primary-nav">
        <div className="brand">
          <button className="sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Close navigation">
            ×
          </button>
          <div className="brand-mark">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/ahte-logo.png" alt="AHTE" width="52" height="52" />
          </div>
          <h1 className="brand-title">
            <span className="brand-title-main">AHTE</span>
            <span className="brand-title-suffix">BMS</span>
          </h1>
          <span className="brand-tagline">{APP_TAGLINE}</span>
          <span className="brand-company">{COMPANY_NAME}</span>
        </div>

        <nav aria-label="Primary">
          {NAV.filter(([href]) => href !== "/admin" || (user && user.role === "admin")).map(([href, label, icon]) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link key={href} href={href} className={active ? "active" : ""} aria-current={active ? "page" : undefined}>
                <NavIcon name={icon} />
                <span className="nav-label">{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="userbox">
          <strong>{user ? user.name : "—"}</strong>
          <span>{user ? `${user.role} · ${user.email}` : ""}</span>
          <div className="userbox-actions">
            <ThemeToggle />
            <button className="signout" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>

        <div className="companycontact">
          <a href={COMPANY_WEBSITE} target="_blank" rel="noreferrer noopener">
            www.ahte.com.pk
          </a>
          <a href={`mailto:${COMPANY_EMAIL}`}>{COMPANY_EMAIL}</a>
        </div>

        <div className="poweredby">
          <div className="poweredby-rule" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="poweredby-logo"
            src="/brand/datafy-associates-logo.png"
            alt="Datafy Associates"
            width="138"
            height="58"
          />
          <span className="poweredby-text">Powered by Datafy Associates</span>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

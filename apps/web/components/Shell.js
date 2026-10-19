"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, getToken, getUser } from "../lib/api";

const APP_TAGLINE = "AI Powered Bid Management System";

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
    setUser(getUser());
    api("/api/auth/me")
      .then((me) => {
        setUser(me);
        setReady(true);
      })
      .catch(() => {});
  }, [pathname, router]);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!ready) {
    return (
      <div className="layout">
        <main className="main">
          <p className="muted">Loading session…</p>
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
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/ahte-logo.png" alt="AHTE" width="52" height="52" />
          </div>
          <h1 className="brand-title">
            <span className="brand-title-main">AHTE</span>
            <span className="brand-title-suffix">BMS</span>
          </h1>
          <span className="brand-tagline">{APP_TAGLINE}</span>
        </div>

        <nav>
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
          <button onClick={logout}>Sign out</button>
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

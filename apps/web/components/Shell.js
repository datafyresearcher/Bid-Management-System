"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, getToken, getUser } from "../lib/api";

const NAV = [
  ["/", "Dashboard"],
  ["/inbox", "Tender Inbox"],
  ["/pipeline", "Pipeline"],
  ["/review", "Review Queue"],
  ["/leads", "Leads Radar"],
  ["/kb", "Knowledge Base"],
  ["/admin", "Admin & Quality"],
];

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
          <h1>BMS</h1>
          <span>AI Bid Management System</span>
        </div>
        <nav>
          {NAV.filter(([href]) => href !== "/admin" || (user && user.role === "admin")).map(([href, label]) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link key={href} href={href} className={active ? "active" : ""}>
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="userbox">
          <strong>{user ? user.name : "—"}</strong>
          <span>{user ? `${user.role} · ${user.email}` : ""}</span>
          <button onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

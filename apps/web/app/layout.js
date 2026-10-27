import "./globals.css";
import Shell from "../components/Shell";

export const metadata = {
  title: "AHTE BMS — AI Powered Bid Management System",
  description:
    "AI-assisted tender discovery, triage and proposal management for AL-Hussain Traders & Engineers PVT. LTD.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#0a2c38",
};

// Runs before the first paint: picks the saved theme, falling back to the
// system preference, so the page never flashes the wrong look on open.
const THEME_BOOT = `(function(){try{var t=localStorage.getItem("bms_theme");if(t!=="dark"&&t!=="light"){t=window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme="light";}})();`;

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

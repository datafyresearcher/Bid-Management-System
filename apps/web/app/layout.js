import "./globals.css";
import Shell from "../components/Shell";

export const metadata = {
  title: "AHTE BMS — AI Powered Bid Management System",
  description: "AI-assisted tender discovery, triage and proposal management for AHTE",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#0a2c38",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

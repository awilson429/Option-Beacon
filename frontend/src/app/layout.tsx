import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OptionBeacon · Options Desk",
  description: "SPY and QQQ decision support with isolated scalp research.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body>{children}</body>
    </html>
  );
}

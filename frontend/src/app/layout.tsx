import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OptionBeacon · Trade Desk",
  description: "OptionBeacon trading command center and decision support.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body>{children}</body>
    </html>
  );
}

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OptionBeacon · Market Command",
  description: "OptionBeacon snapshot-driven trading terminal.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body>{children}</body>
    </html>
  );
}

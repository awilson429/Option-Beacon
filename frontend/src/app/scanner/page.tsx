import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { ScannerDesk } from "@/components/scanner-desk";

export const metadata: Metadata = {
  title: "OptionBeacon · Scanner",
  description: "Persisted SPY and QQQ scanner state with independent OB/BROAD decisions.",
};

export default function ScannerPage() {
  return <AppShell><ScannerDesk/></AppShell>;
}

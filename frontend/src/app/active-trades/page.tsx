import type { Metadata } from "next";
import { ActiveTradesDesk } from "@/components/active-trades-desk";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "OptionBeacon · Active Trades",
  description: "Read-only operational view of persisted OB and BROAD positions.",
};

export default function ActiveTradesPage() {
  return <AppShell><ActiveTradesDesk/></AppShell>;
}

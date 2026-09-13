import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { TradeDesk } from "@/components/trade-desk";

export const metadata:Metadata={
  title:"OptionBeacon · Market Command",
  description:"Canonical persisted OptionBeacon trading terminal.",
};

export default function Home() {
  return <AppShell><TradeDesk/></AppShell>;
}

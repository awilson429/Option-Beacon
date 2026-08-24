import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { OptionsDesk } from "@/components/options-desk";

export const metadata: Metadata = {
  title: "OptionBeacon · Options Desk",
  description: "SPY and QQQ decision support with isolated scalp research.",
};

export default function OptionsPage() {
  return <AppShell><OptionsDesk/></AppShell>;
}

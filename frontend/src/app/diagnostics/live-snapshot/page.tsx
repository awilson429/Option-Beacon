import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { LiveSnapshotDebug } from "@/components/live-snapshot-debug";

export const metadata:Metadata={title:"OptionBeacon · Live Snapshot Diagnostics"};

export default function LiveSnapshotPage(){return <AppShell><LiveSnapshotDebug/></AppShell>}

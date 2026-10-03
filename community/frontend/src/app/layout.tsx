import type { Metadata, Viewport } from "next";
import { SessionProvider } from "../ui/session";
import { ApplicationShell } from "../ui/Shell";
import "./globals.css";
export const metadata: Metadata = { title: { default: "SynchroHQ", template: "%s · SynchroHQ" }, description: "Collect. Sync. Act. Together.", manifest: "/manifest.webmanifest", icons: { icon: "/icon.svg", apple: "/icon.svg" } };
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#07304a" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr" suppressHydrationWarning><body><SessionProvider><ApplicationShell>{children}</ApplicationShell></SessionProvider></body></html>;
}

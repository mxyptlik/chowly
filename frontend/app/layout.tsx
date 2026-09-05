import type { Metadata } from "next";
import "./globals.css";
import { ClientProviders } from "../components/client-providers";

export const metadata: Metadata = {
  title: "Chowly — table service, unhurried",
  description: "QR dining and restaurant operations for thoughtful service.",
  applicationName: "Chowly",
  manifest: "/manifest.json",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "Chowly" },
  icons: {
    icon: [{ url: "/icons/chowly.svg", type: "image/svg+xml" }],
    apple: [{ url: "/icons/chowly.svg", type: "image/svg+xml" }],
  },
};

export const viewport = {
  themeColor: "#151719",
  colorScheme: "dark light",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">Skip to main content</a>
        <ClientProviders>
          <div id="main-content" tabIndex={-1}>{children}</div>
        </ClientProviders>
      </body>
    </html>
  );
}

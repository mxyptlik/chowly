"use client";

import { StaffAuthProvider } from "../lib/auth";
import { ConnectivityProvider } from "../lib/offline/connectivity";
import { PwaRegistration } from "../app/pwa-registration";
import { ServiceRail } from "./service-rail";
import { ToastProvider } from "./ui";
import { AmbientBackground } from "./ambient-background";
import { ThemeProvider, ThemeToggle } from "./theme-provider";
import { RouteLoader } from "./route-loader";

export function ClientProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AmbientBackground />
      <ThemeToggle />
      <StaffAuthProvider>
        <ConnectivityProvider>
          <ToastProvider>
            <PwaRegistration />
            <RouteLoader />
            {children}
            <ServiceRail />
          </ToastProvider>
        </ConnectivityProvider>
      </StaffAuthProvider>
    </ThemeProvider>
  );
}

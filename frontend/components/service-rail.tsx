"use client";

import { useEffect, useState } from "react";
import { useConnectivity } from "../lib/offline/connectivity";

type InstallPrompt = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export function ServiceRail() {
  const { online, pendingCount, conflictCount, syncNow } = useConnectivity();
  const [installPrompt, setInstallPrompt] = useState<InstallPrompt | null>(null);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    const capture = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as InstallPrompt);
    };
    const finish = () => {
      setInstalled(true);
      setInstallPrompt(null);
    };
    window.addEventListener("beforeinstallprompt", capture);
    window.addEventListener("appinstalled", finish);
    setInstalled(window.matchMedia("(display-mode: standalone)").matches);
    return () => {
      window.removeEventListener("beforeinstallprompt", capture);
      window.removeEventListener("appinstalled", finish);
    };
  }, []);

  async function install() {
    if (!installPrompt) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  }

  return (
    <aside className="service-rail" aria-label="Connection and application status">
      <div className={`connection-state ${online ? "is-online" : "is-offline"}`} role="status" aria-live="polite">
        <span className="connection-dot" aria-hidden="true" />
        <span>{online ? "Online" : "Offline — changes need connection"}</span>
      </div>
      {pendingCount > 0 && <button className="rail-action" onClick={() => void syncNow()} disabled={!online}>{pendingCount} pending sync</button>}
      {conflictCount > 0 && <span className="rail-conflict" role="alert">{conflictCount} need attention</span>}
      {!installed && installPrompt && <button className="rail-action" onClick={() => void install()}>Install app</button>}
    </aside>
  );
}

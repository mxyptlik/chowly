"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiClient } from "../api";
import { indexedDbOutbox, replayOutbox } from "./outbox";

type ConnectivityState = {
  online: boolean;
  pendingCount: number;
  conflictCount: number;
  syncNow: () => Promise<void>;
};

const ConnectivityContext = createContext<ConnectivityState | null>(null);

export function ConnectivityProvider({ children }: { children: React.ReactNode }) {
  const [online, setOnline] = useState(true);
  const [pendingCount, setPendingCount] = useState(0);
  const [conflictCount, setConflictCount] = useState(0);

  const refreshCounts = useCallback(async () => {
    try {
      const items = await indexedDbOutbox.list();
      setPendingCount(items.filter((item) => item.state !== "CONFLICT").length);
      setConflictCount(items.filter((item) => item.state === "CONFLICT").length);
    } catch {
      setPendingCount(0);
      setConflictCount(0);
    }
  }, []);

  const syncNow = useCallback(async () => {
    if (!navigator.onLine) return;
    await replayOutbox(indexedDbOutbox, apiClient);
    await refreshCounts();
  }, [refreshCounts]);

  useEffect(() => {
    const update = () => {
      setOnline(navigator.onLine);
      if (navigator.onLine) void syncNow();
    };
    update();
    void refreshCounts();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, [refreshCounts, syncNow]);

  const value = useMemo(() => ({ online, pendingCount, conflictCount, syncNow }), [conflictCount, online, pendingCount, syncNow]);
  return <ConnectivityContext.Provider value={value}>{children}</ConnectivityContext.Provider>;
}

export function useConnectivity() {
  const context = useContext(ConnectivityContext);
  if (!context) throw new Error("useConnectivity must be used inside ConnectivityProvider");
  return context;
}

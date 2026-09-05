"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

export type NoticeTone = "info" | "success" | "warning" | "danger";

export function Notice({ tone = "info", title, children }: { tone?: NoticeTone; title?: string; children: React.ReactNode }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      {title && <strong className="notice-title">{title}</strong>}
      <div>{children}</div>
    </div>
  );
}

export function StatusRegion({ children, urgent = false, className = "" }: { children: React.ReactNode; urgent?: boolean; className?: string }) {
  return <div className={className} role={urgent ? "alert" : "status"} aria-live={urgent ? "assertive" : "polite"} aria-atomic="true">{children}</div>;
}

type Toast = { id: string; message: string; tone: NoticeTone };
type ToastContextValue = { announce: (message: string, tone?: NoticeTone) => void };
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const announce = useCallback((message: string, tone: NoticeTone = "success") => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4200);
  }, []);
  const value = useMemo(() => ({ announce }), [announce]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => <div className={`toast toast-${toast.tone}`} key={toast.id} role={toast.tone === "danger" ? "alert" : "status"}><span>{toast.message}</span><button type="button" onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))} aria-label="Dismiss notification">×</button></div>)}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}

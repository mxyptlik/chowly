"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export function RouteLoader() {
  const pathname = usePathname();
  const [loading, setLoading] = useState(false);
  useEffect(() => { setLoading(false); }, [pathname]);
  useEffect(() => {
    const begin = (event: MouseEvent) => {
      const link = (event.target as Element | null)?.closest("a[href]") as HTMLAnchorElement | null;
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || link.target === "_blank") return;
      const next = new URL(link.href, window.location.href);
      if (next.origin === window.location.origin && next.pathname !== window.location.pathname) setLoading(true);
    };
    document.addEventListener("click", begin);
    return () => document.removeEventListener("click", begin);
  }, []);
  useEffect(() => {
    const beginHistoryNavigation = () => setLoading(true);
    window.addEventListener("popstate", beginHistoryNavigation);
    return () => window.removeEventListener("popstate", beginHistoryNavigation);
  }, []);
  if (!loading) return null;
  return <div className="route-loader" role="status" aria-live="polite"><span className="route-loader-mark" aria-hidden="true" /><span>Opening your next page…</span></div>;
}

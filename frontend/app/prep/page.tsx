"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ActionButton, Notice, StatusBadge } from "../../components/ui";
import { StaffChrome } from "../../components/staff/staff-chrome";
import { ApiError, apiClient } from "../../lib/api";
import { RequireStaffAccess, useStaffAuth } from "../../lib/auth";
import { useConnectivity } from "../../lib/offline/connectivity";

type QueueLine = { line_id: string; order_id: string; table_label: string; item_name: string; quantity: number; modifiers: { name: string }[]; special_instruction?: string | null; queue_destination: "KITCHEN" | "BAR"; status: string; order_version: string };
const errorMessage = (reason: unknown, fallback: string) => reason instanceof ApiError ? reason.message : fallback;

function PreparationQueue() {
  const { session } = useStaffAuth();
  const { online } = useConnectivity();
  const [queue, setQueue] = useState<QueueLine[]>([]);
  const [notice, setNotice] = useState("");
  const location = session?.locations.find((item) => item.id === session.active_location_id);
  const refresh = useCallback(async () => setQueue(await apiClient.get<QueueLine[]>("/staff/prep")), []);

  useEffect(() => {
    void refresh().catch((reason) => setNotice(errorMessage(reason, "The preparation queue is reconnecting…")));
    const interval = window.setInterval(() => void refresh().catch(() => undefined), 5000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const food = useMemo(() => queue.filter((line) => line.queue_destination === "KITCHEN"), [queue]);
  const drinks = useMemo(() => queue.filter((line) => line.queue_destination === "BAR"), [queue]);

  async function progress(line: QueueLine) {
    if (!session) return;
    const requiredRole = line.queue_destination === "KITCHEN" ? "CHEF" : "BARTENDER";
    if (!session.roles.includes(requiredRole)) {
      setNotice(`Your signed-in role cannot update the ${line.queue_destination === "KITCHEN" ? "kitchen" : "bar"} queue.`);
      return;
    }
    const action = line.status === "PENDING" ? "claim" : "ready";
    if (!online && action === "claim") { setNotice("Claiming needs a confirmed connection. It is never guessed offline."); return; }
    try {
      await apiClient.post(`/staff/lines/${line.line_id}/${action}`, { expected_version: line.order_version }, { headers: action === "ready" ? { "Idempotency-Key": crypto.randomUUID() } : undefined });
      setNotice(action === "claim" ? `${session.name} claimed ${line.item_name}.` : `${line.item_name} is ready for service.`);
      await refresh();
    } catch (reason) {
      setNotice(errorMessage(reason, "That line could not be updated."));
    }
  }

  function column(title: string, lines: QueueLine[], type: "KITCHEN" | "BAR") {
    return <section className="panel"><h2>{title} <span className="pill">{lines.length}</span></h2>{lines.length ? lines.map((line) => <article key={line.line_id} className={`prep-card ${type === "BAR" ? "drink" : ""}`}><span className="type-label">{line.table_label} · <StatusBadge status={line.status} /></span><h3>{line.quantity} × {line.item_name}</h3>{line.modifiers?.length > 0 && <p>{line.modifiers.map((modifier) => modifier.name).join(", ")}</p>}{line.special_instruction && <p>Note: {line.special_instruction}</p>}<ActionButton disabled={!online && line.status === "PENDING"} tone={line.status === "PENDING" ? "ink" : "sun"} onClick={() => void progress(line)}>{line.status === "PENDING" ? "Claim line" : "Mark ready"}</ActionButton></article>) : <p className="loading">Clear board.</p>}</section>;
  }

  return (
    <StaffChrome eyebrow="Station control" title="Make the next good thing."><p className="subcopy">{location?.name} · Customer contact details never enter this workspace.</p>{notice && <Notice tone="info" title="Preparation update">{notice}</Notice>}<div className="ops-grid">{session?.roles.includes("CHEF") && column("Kitchen", food, "KITCHEN")}{session?.roles.includes("BARTENDER") && column("Cold bar", drinks, "BAR")}</div></StaffChrome>
  );
}

export default function PrepPage() {
  return <RequireStaffAccess roles={["CHEF", "BARTENDER"]}><PreparationQueue /></RequireStaffAccess>;
}

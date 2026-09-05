"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Image from "next/image";
import QRCode from "qrcode";
import { ActionButton, FieldInput, Notice, StatusBadge } from "../../../components/ui";
import { RequireStaffAccess, useStaffAuth } from "../../../lib/auth";
import { apiClient, ApiError } from "../../../lib/api";
import { StaffChrome } from "../../../components/staff/staff-chrome";

type DiningTable = { id: string; label: string; capacity: number; is_enabled: boolean; is_active: boolean };
type TableQr = { table_label: string; menu_url: string; expires_at: string };
const message = (reason: unknown) => reason instanceof ApiError ? reason.message : "Chowly could not confirm that action.";

export default function TablesWorkspace() {
  return <RequireStaffAccess roles={["WAITER", "MANAGER", "TENANT_OWNER"]}><TablesPage /></RequireStaffAccess>;
}

function TablesPage() {
  const { session } = useStaffAuth();
  const locationId = session?.active_location_id ?? "";
  const canManageTables = session?.roles.some((role) => role === "MANAGER" || role === "TENANT_OWNER") ?? false;
  const [tables, setTables] = useState<DiningTable[]>([]);
  const [label, setLabel] = useState("");
  const [capacity, setCapacity] = useState("2");
  const [qr, setQr] = useState<TableQr | null>(null);
  const [qrImage, setQrImage] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    if (!locationId) return;
    setTables(await apiClient.get<DiningTable[]>(`/staff/locations/${encodeURIComponent(locationId)}/tables`));
  }, [locationId]);
  useEffect(() => { void load().catch((reason) => setNotice(message(reason))); }, [load]);
  useEffect(() => { if (qr) void QRCode.toDataURL(qr.menu_url, { width: 480, margin: 2, errorCorrectionLevel: "M" }).then(setQrImage); }, [qr]);

  async function add(event: FormEvent) {
    event.preventDefault(); setPending(true); setNotice("");
    try { await apiClient.post(`/staff/locations/${encodeURIComponent(locationId)}/tables`, { label: label.trim(), capacity: Number(capacity) }); setLabel(""); await load(); setNotice("Table added."); }
    catch (reason) { setNotice(message(reason)); } finally { setPending(false); }
  }
  async function showQr(table: DiningTable, regenerate = false) {
    setPending(true); setNotice("");
    try { setQr(await apiClient.request<TableQr>(`/staff/locations/${encodeURIComponent(locationId)}/tables/${encodeURIComponent(table.id)}/qr${regenerate ? "/regenerate" : ""}`, { method: regenerate ? "POST" : "GET" })); }
    catch (reason) { setNotice(message(reason)); } finally { setPending(false); }
  }

  return <StaffChrome eyebrow="Room setup" title="Every table, ready to serve.">
    {notice && <Notice tone={notice === "Table added." ? "success" : "danger"} title="Tables & QR">{notice}</Notice>}
    <section className="admin-grid">
      {canManageTables ? <form className="panel" onSubmit={add}><p className="eyebrow">Add a table</p><h2>Set up the room</h2><FieldInput label="Table name" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Table 01" required /><FieldInput label="Seats" type="number" min="1" max="50" value={capacity} onChange={(event) => setCapacity(event.target.value)} required /><ActionButton type="submit" pending={pending}>Add table</ActionButton></form> : <section className="panel"><p className="eyebrow">Table access</p><h2>Find and present a table QR.</h2><p>Waiters can display or refresh the daily QR when a table tablet needs a new code. Managers configure the room layout.</p></section>}
      <section className="panel"><p className="eyebrow">Live table list</p><h2>{tables.length} table{tables.length === 1 ? "" : "s"}</h2><div className="table-workspace-list">{tables.map((table) => <article className="admin-row" key={table.id}><span><b>{table.label}</b><small>{table.capacity} seats · {table.is_enabled ? "enabled" : "disabled"}</small></span><StatusBadge status={table.is_active ? "ACTIVE" : "AVAILABLE"} /><div className="action-row"><ActionButton tone="quiet" pending={pending} onClick={() => void showQr(table)}>Show QR</ActionButton><ActionButton tone="sun" pending={pending} onClick={() => void showQr(table, true)}>Refresh QR</ActionButton></div></article>)}</div></section>
    </section>
    {qr && <section className="panel qr-print-card"><p className="eyebrow">Daily table menu pass</p><h2>{qr.table_label}</h2>{qrImage && <Image className="table-qr-image" src={qrImage} alt={`Scannable daily menu QR for ${qr.table_label}`} width={480} height={480} unoptimized />}<p>Valid until {new Date(qr.expires_at).toLocaleString()}.</p><div className="action-row"><ActionButton tone="quiet" onClick={() => void navigator.clipboard.writeText(qr.menu_url)}>Copy menu link</ActionButton><a className="action action-ink" href={qr.menu_url} target="_blank" rel="noreferrer">Open menu</a><ActionButton tone="sun" onClick={() => window.print()}>Print QR</ActionButton></div></section>}
  </StaffChrome>;
}

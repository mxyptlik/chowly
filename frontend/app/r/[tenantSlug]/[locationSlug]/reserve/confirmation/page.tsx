"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiClient } from "../../../../../../lib/api";
import { ReservationQrPass } from "../../../../../../components/diner/reservation-qr-pass";

type Reservation = { id: string; party_size: number; requested_at: string; status: string };

function Workspace() {
  const token = useSearchParams().get("token");
  const reservationToken = token ?? "";
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [message, setMessage] = useState("");
  const [partySize, setPartySize] = useState(2);
  const [requestedAt, setRequestedAt] = useState("");
  const [passUrl, setPassUrl] = useState("");

  const load = useCallback(async () => {
    if (!reservationToken) return;
    const found = await apiClient.get<Reservation>(`/public/reservations/status/${encodeURIComponent(reservationToken)}`);
    setReservation(found);
    setPartySize(found.party_size);
    setRequestedAt(new Date(found.requested_at).toISOString().slice(0, 16));
  }, [reservationToken]);

  useEffect(() => { void load().catch(() => setMessage("This private reservation link is unavailable.")); }, [load]);
  if (!reservationToken) return <main className="app-shell"><h1 className="app-title">Link <em>missing.</em></h1></main>;

  async function update() {
    try {
      await apiClient.patch(`/public/reservations/status/${encodeURIComponent(reservationToken)}`, { party_size: partySize, requested_at: new Date(requestedAt).toISOString() });
      setMessage("Updated for restaurant review.");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not update your reservation."); }
  }
  async function cancel() {
    try {
      await apiClient.post(`/public/reservations/status/${encodeURIComponent(reservationToken)}/cancel`);
      setMessage("Reservation cancelled.");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not cancel your reservation."); }
  }
  async function createPass() {
    try {
      const result = await apiClient.post<{ qr_pass_token: string }>(`/public/reservations/status/${encodeURIComponent(reservationToken)}/qr-pass`);
      setPassUrl(`${location.origin}/ops/verify-reservation?pass=${encodeURIComponent(result.qr_pass_token)}`);
      setMessage("Your private check-in QR is ready.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not create your check-in pass."); }
  }
  async function copyLink() {
    try { await navigator.clipboard.writeText(location.href); setMessage("Private reservation link copied."); }
    catch { setMessage("Copy is unavailable here. Select this page’s address to save it."); }
  }

  return <main className="app-shell">
    <p className="eyebrow">Your reservation</p><h1 className="app-title">Manage your<br /><em>place.</em></h1>
    {reservation ? <section className="panel reservation-workspace">
      <p><b>{reservation.status}</b> · Ref {reservation.id.slice(0, 8).toUpperCase()}</p>
      <label className="form-label">Party size<input className="control" type="number" min="1" value={partySize} onChange={(event) => setPartySize(Number(event.target.value))} /></label>
      <label className="form-label">Date and time<input className="control" type="datetime-local" value={requestedAt} onChange={(event) => setRequestedAt(event.target.value)} /></label>
      <div className="action-row"><button className="button primary" type="button" onClick={() => void update()}>Save changes</button><button className="button" type="button" onClick={() => void copyLink()}>Copy private link</button><button className="button" type="button" onClick={() => void createPass()}>Create check-in QR</button><button className="button danger" type="button" onClick={() => void cancel()}>Cancel reservation</button></div>
      {passUrl && <ReservationQrPass passUrl={passUrl} reservationReference={reservation.id.slice(0, 8).toUpperCase()} />}
      {message && <p className="field-hint" role="status">{message}</p>}
    </section> : <p>Loading reservation…</p>}
    <Link className="button" href="/restaurants">Find a restaurant</Link>
  </main>;
}

export default function Page() { return <Suspense fallback={<main className="app-shell">Loading reservation…</main>}><Workspace /></Suspense>; }

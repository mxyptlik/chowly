"use client";

import { useState } from "react";
import { apiClient } from "../../../lib/api";
import { RequireStaffAccess } from "../../../lib/auth";
import { StaffChrome } from "../../../components/staff/staff-chrome";
import { ReservationPassScanner } from "../../../components/staff/reservation-pass-scanner";
import { Notice } from "../../../components/ui";

type Reservation = { id: string; party_size: number; requested_at: string; status: string; contact: { name: string; phone: string } };

function tokenFrom(value: string) {
  try { return new URL(value).searchParams.get("pass") ?? value.trim(); }
  catch { return value.includes("pass=") ? value.split("pass=")[1]?.split("&")[0] ?? "" : value.trim(); }
}

function VerifyReservationWorkspace() {
  const [pass, setPass] = useState("");
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [message, setMessage] = useState("");
  async function verify(value = pass) {
    const token = tokenFrom(value);
    if (!token) { setMessage("Scan or paste a reservation QR pass first."); return; }
    try {
      setMessage("Checking pass…");
      setReservation(await apiClient.get<Reservation>(`/staff/reservations/qr-pass/${encodeURIComponent(token)}`));
      setPass(token);
      setMessage("Pass verified. Check the arrival details before checking in.");
    } catch (error) { setReservation(null); setMessage(error instanceof Error ? error.message : "Pass not valid."); }
  }
  async function checkIn() {
    try {
      setReservation(await apiClient.post<Reservation>(`/staff/reservations/qr-pass/${encodeURIComponent(pass)}/check-in`));
      setMessage("Guest checked in. This action was recorded.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not check in guest."); }
  }

  return <StaffChrome eyebrow="Reservation arrival" title="Verify a guest pass.">
    <section className="panel reservation-verification">
      <ReservationPassScanner onPass={(token) => { setPass(token); void verify(token); }} />
      <div className="reservation-paste"><label className="form-label">Reservation QR pass or link<input className="control" value={pass} onChange={(event) => setPass(event.target.value)} placeholder="Paste scanned pass or link" autoCapitalize="off" autoCorrect="off" /></label><button className="button" type="button" onClick={() => void verify()}>Verify pasted pass</button></div>
      {reservation && <article className="admin-row reservation-verification-result"><span><b>{reservation.contact.name} · {reservation.party_size} guests</b><small>{new Date(reservation.requested_at).toLocaleString()} · {reservation.status}</small></span>{reservation.status === "CONFIRMED" && <button className="button primary" type="button" onClick={() => void checkIn()}>Check in guest</button>}</article>}
      <p className="field-hint">Only check in a guest after you have confirmed their arrival. A QR pass is private; never copy it into notes or share it.</p>
      {message && <p className="field-hint" role="status">{message}</p>}
    </section>
  </StaffChrome>;
}

export default function VerifyReservation() {
  return <RequireStaffAccess roles={["WAITER", "MANAGER"]} fallback={<Notice tone="warning" title="Reservation check-in restricted">Sign in as an assigned waiter or manager.</Notice>}><VerifyReservationWorkspace /></RequireStaffAccess>;
}

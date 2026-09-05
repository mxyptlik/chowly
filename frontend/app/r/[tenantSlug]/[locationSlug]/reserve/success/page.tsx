"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { apiClient } from "../../../../../../lib/api";

type Reservation = { id: string; party_size: number; requested_at: string; status: string };

function Success() {
  const token = useSearchParams().get("token"); const [reservation, setReservation] = useState<Reservation | null>(null);
  useEffect(() => { if (token) void apiClient.get<Reservation>(`/public/reservations/status/${encodeURIComponent(token)}`).then(setReservation); }, [token]);
  if (!token) return <main className="app-shell"><h1 className="app-title">Reservation link<br /><em>missing.</em></h1></main>;
  return <main className="app-shell"><p className="eyebrow">CHOWLY° · RESERVATION RECEIPT</p><h1 className="app-title">✓ You’re<br /><em>on the list.</em></h1><p className="subcopy">Your reservation request was received. The restaurant will confirm the details.</p>{reservation && <section className="panel"><p><strong>Reference</strong> · {reservation.id.slice(0, 8).toUpperCase()}</p><p>{reservation.party_size} guests · {new Date(reservation.requested_at).toLocaleString()}</p></section>}<Link className="button primary" href={`../confirmation?token=${encodeURIComponent(token)}`}>View your reservation</Link></main>;
}
export default function ReservationSuccessPage() { return <Suspense fallback={<main className="app-shell"><p className="eyebrow">Reservation receipt</p><h1 className="app-title">Saving your<br /><em>place.</em></h1></main>}><Success /></Suspense>; }

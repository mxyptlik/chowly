"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "../../lib/api";
import { sanitizePhoneInput } from "../../lib/phone";
import { Notice, StatusRegion } from "../ui/feedback";
import { ActionButton, FieldInput, FieldSelect, FieldTextArea } from "../ui/form-controls";

type Status = { id: string; status: string; requested_at: string };
type Location = { slug: string; name: string; address?: string | null };
type Restaurant = { slug: string; name: string; locations?: Location[] };
type PublicLocationResponse = { restaurant: { name: string }; location: { name: string } };
type Props = { tenantSlug?: string; locationSlug?: string; confirmationPath?: string; successPath?: string };

export function ReservationForm({ tenantSlug: fixedTenant, locationSlug: fixedLocation, confirmationPath, successPath }: Props = {}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [tenant, setTenant] = useState(fixedTenant ?? "");
  const [location, setLocation] = useState(fixedLocation ?? "");
  const [fixedLocationName, setFixedLocationName] = useState("");
  const [party, setParty] = useState(2);
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState("");
  const selected = useMemo(() => restaurants.find((row) => row.slug === tenant), [restaurants, tenant]);
  const locations = selected?.locations ?? [];
  const fixed = Boolean(fixedTenant && fixedLocation);

  const refresh = useCallback(async (value = token) => {
    if (!value) return;
    try {
      const out = await apiClient.get<Status>(`/public/reservations/status/${encodeURIComponent(value)}`);
      setStatus(`Reservation ${out.id.slice(0, 8).toUpperCase()} is ${out.status.toLowerCase()} for ${new Date(out.requested_at).toLocaleString()}.`);
    } catch {
      setStatus("This reservation status link is no longer available.");
    }
  }, [token]);

  useEffect(() => {
    const saved = sessionStorage.getItem("chowly:reservation-access-token");
    if (saved) {
      setToken(saved);
      void refresh(saved);
    }
  }, [refresh]);

  useEffect(() => {
    if (!fixedTenant) {
      void apiClient.get<Restaurant[]>("/public/restaurants")
        .then(setRestaurants)
        .catch(() => setError("Restaurant choices are unavailable right now. Please try again."));
    }
  }, [fixedTenant]);

  useEffect(() => {
    if (!fixedTenant || !fixedLocation) return;
    void apiClient.get<PublicLocationResponse>(`/public/restaurants/${encodeURIComponent(fixedTenant)}/locations/${encodeURIComponent(fixedLocation)}`)
      .then((out) => setFixedLocationName(`${out.restaurant.name} — ${out.location.name}`))
      .catch(() => setError("This restaurant location is unavailable right now. Please return to the restaurant page and try again."));
  }, [fixedLocation, fixedTenant]);

  async function submit() {
    if (!name.trim() || !phone.trim() || !tenant || !location || !when) {
      setError("Choose a restaurant and location, then provide your name, phone number, party size, and preferred time.");
      return;
    }
    setPending(true);
    setError("");
    try {
      const out = await apiClient.post<{ id: string; status: string; access_token: string }>("/public/reservations", {
        customer_name: name.trim(), customer_phone: phone.trim(), tenant_slug: tenant,
        location_slug: location, party_size: party, requested_at: new Date(when).toISOString(), note: note.trim() || null,
      });
      sessionStorage.setItem("chowly:reservation-access-token", out.access_token);
      setToken(out.access_token);
      if (successPath) { router.push(`${successPath}?token=${encodeURIComponent(out.access_token)}`); return; }
      setMessage(`Reservation request ${out.id.slice(0, 8).toUpperCase()} is ${out.status.toLowerCase()}. The service team will confirm it.`);
      await refresh(out.access_token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "We could not submit your request.");
    } finally {
      setPending(false);
    }
  }

  const locationLabel = fixedLocationName || "this restaurant location";
  return <main className="app-shell">
    <p className="eyebrow">Reservation request</p>
    <h1 className="app-title">Save a place<br /><em>at the table.</em></h1>
    <p className="subcopy">{fixed ? `Request a table at ${locationLabel}. ` : "Choose a restaurant and location. "}No account is required.</p>
    <section className="panel">
      <FieldInput label="Your name" value={name} onChange={(event) => setName(event.target.value)} required />
      <FieldInput label="Phone number" type="tel" inputMode="tel" autoComplete="tel" maxLength={18} value={phone} onChange={(event) => setPhone(sanitizePhoneInput(event.target.value))} pattern="[+0-9() -]+" required hint="Use an 11-digit Nigerian number, e.g. 08012345678." />
      {fixed ? <p className="field-hint">Reservation for <strong>{locationLabel}</strong>.</p> : <>
        <FieldSelect label="Restaurant" value={tenant} onChange={(event) => { setTenant(event.target.value); setLocation(""); }} required>
          <option value="">Choose a restaurant</option>{restaurants.map((row) => <option key={row.slug} value={row.slug}>{row.name}</option>)}
        </FieldSelect>
        <FieldSelect label="Restaurant location" value={location} onChange={(event) => setLocation(event.target.value)} required disabled={!tenant}>
          <option value="">Choose a location</option>{locations.map((row) => <option key={row.slug} value={row.slug}>{row.name}{row.address ? ` — ${row.address}` : ""}</option>)}
        </FieldSelect>
      </>}
      <FieldInput label="Party size" type="number" min={1} max={100} value={party} onChange={(event) => setParty(Number(event.target.value))} />
      <FieldInput label="Preferred date and time" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} required />
      <FieldTextArea label="Note" optional value={note} onChange={(event) => setNote(event.target.value)} />
      <ActionButton pending={pending} onClick={submit}>Request reservation</ActionButton>
      {token && <>
        {confirmationPath && <Link className="button primary" href={`${confirmationPath}?token=${encodeURIComponent(token)}`}>View reservation confirmation</Link>}
        <ActionButton tone="quiet" onClick={() => refresh()}>Refresh reservation status</ActionButton>
      </>}
      <StatusRegion>{message && <Notice tone="success">{message}</Notice>}{status && <Notice tone="info" title="Reservation status">{status}</Notice>}{error && <Notice tone="danger">{error}</Notice>}</StatusRegion>
    </section>
  </main>;
}

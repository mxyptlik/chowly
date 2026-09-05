import { ReservationForm } from "../../../../../components/diner/reservation-form";

/** The form resolves the human-readable restaurant and location name from the
 * public route. URL slugs remain routing keys, never customer-facing labels. */
export default async function PublicReservationPage({ params }: { params: Promise<{ tenantSlug: string; locationSlug: string }> }) {
  const { tenantSlug, locationSlug } = await params;
  return <ReservationForm tenantSlug={tenantSlug} locationSlug={locationSlug} confirmationPath={`/r/${tenantSlug}/${locationSlug}/reserve/confirmation`} successPath={`/r/${tenantSlug}/${locationSlug}/reserve/success`} />;
}

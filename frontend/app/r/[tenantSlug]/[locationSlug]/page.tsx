import { LocationLanding } from "../../../../components/public/public-restaurant";

export default async function LocationPage({ params }: { params: Promise<{ tenantSlug: string; locationSlug: string }> }) {
  const { tenantSlug, locationSlug } = await params;
  return <LocationLanding tenantSlug={tenantSlug} locationSlug={locationSlug} />;
}

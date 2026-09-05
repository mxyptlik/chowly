import { PublicMenu } from "../../../../../components/public/public-menu";

export default async function MenuPage({ params }: { params: Promise<{ tenantSlug: string; locationSlug: string }> }) {
  const { tenantSlug, locationSlug } = await params;
  return <PublicMenu tenantSlug={tenantSlug} locationSlug={locationSlug} />;
}

import { RestaurantLanding } from "../../../components/public/public-restaurant";

export default async function RestaurantPage({ params }: { params: Promise<{ tenantSlug: string }> }) {
  const { tenantSlug } = await params;
  return <RestaurantLanding tenantSlug={tenantSlug} />;
}

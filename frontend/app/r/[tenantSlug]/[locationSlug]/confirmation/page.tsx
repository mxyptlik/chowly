import { redirect } from "next/navigation";

type Props = {
  params: Promise<{
    tenantSlug: string;
    locationSlug: string;
  }>;
  searchParams: Promise<{
    token?: string;
  }>;
};

export default async function ReservationConfirmationRedirect({
  params,
  searchParams,
}: Props) {
  const { tenantSlug, locationSlug } = await params;
  const { token } = await searchParams;

  const destination =
    `/r/${encodeURIComponent(tenantSlug)}` +
    `/${encodeURIComponent(locationSlug)}` +
    `/reserve/confirmation` +
    (token
      ? `?token=${encodeURIComponent(token)}`
      : "");

  redirect(destination);
}
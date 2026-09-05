"use client";

import { use } from "react";
import { DinerOrderJourney } from "../../../components/diner/order-journey";

export default function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  return <DinerOrderJourney orderId={use(params).id} />;
}

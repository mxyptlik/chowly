"use client";

import { use } from "react";
import { DinerMenu } from "../../../components/diner/diner-menu";

export default function DinePage({ params }: { params: Promise<{ code: string }> }) {
  return <DinerMenu code={use(params).code} />;
}

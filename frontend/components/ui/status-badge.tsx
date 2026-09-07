const labels: Record<string, string> = {
  PENDING: "Pending",
  PENDING_SYNC: "Pending sync",
  SUBMITTED: "Submitted",
  PREPARING: "Preparing",
  DELAYED: "Delayed",
  READY_FOR_SERVICE: "Ready for service",
  SERVED: "Served",
  PAID: "Paid",
  CANCELLED: "Cancelled",
  CONFLICT: "Needs attention",
};

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toUpperCase();
  return <span className={`status-badge status-${normalized.toLowerCase().replaceAll("_", "-")}`}>{labels[normalized] ?? normalized.replaceAll("_", " ")}</span>;
}

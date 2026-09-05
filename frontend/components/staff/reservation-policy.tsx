"use client";

import { FormEvent, useEffect, useState } from "react";

import { ActionButton, FieldInput, Notice } from "../ui";
import { apiClient, ApiError } from "../../lib/api";

type ReservationPolicy = {
  customer_edits_enabled: boolean;
  customer_edit_cutoff_minutes: number;
  customer_cancellations_enabled: boolean;
  customer_cancellation_cutoff_minutes: number;
};

type LocationWithReservationPolicy = ReservationPolicy & { id: string };

const defaultPolicy: ReservationPolicy = {
  customer_edits_enabled: true,
  customer_edit_cutoff_minutes: 120,
  customer_cancellations_enabled: true,
  customer_cancellation_cutoff_minutes: 30,
};

function messageFor(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Chowly could not save the reservation policy.";
}

/** Location managers and owners control the customer self-service boundary here. */
export function ReservationPolicyPanel({ locationId }: { locationId: string }) {
  const [policy, setPolicy] = useState<ReservationPolicy>(defaultPolicy);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!locationId) return;
    let active = true;
    void apiClient
      .get<LocationWithReservationPolicy>(`/staff/locations/${locationId}`)
      .then((location) => {
        if (!active) return;
        setPolicy({
          customer_edits_enabled: location.customer_edits_enabled,
          customer_edit_cutoff_minutes: location.customer_edit_cutoff_minutes,
          customer_cancellations_enabled: location.customer_cancellations_enabled,
          customer_cancellation_cutoff_minutes:
            location.customer_cancellation_cutoff_minutes,
        });
      })
      .catch((reason) => active && setNotice(messageFor(reason)));
    return () => {
      active = false;
    };
  }, [locationId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setNotice("");
    try {
      await apiClient.request(`/staff/locations/${locationId}/reservation-policy`, {
        method: "PUT",
        body: policy,
      });
      setNotice("Reservation policy saved and audited.");
    } catch (reason) {
      setNotice(messageFor(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="panel" onSubmit={(event) => void save(event)}>
      <p className="eyebrow">Guest self-service</p>
      <h2>Reservation policy</h2>
      <p>
        Decide whether guests can change or cancel from their private reservation
        link. A changed confirmed reservation returns to the request queue for review.
      </p>

      <label>
        <input
          type="checkbox"
          checked={policy.customer_edits_enabled}
          onChange={(event) =>
            setPolicy({ ...policy, customer_edits_enabled: event.target.checked })
          }
        />{" "}
        Allow guests to edit date, time, or party size
      </label>
      <FieldInput
        label="Edit cutoff (minutes before reservation)"
        type="number"
        min="0"
        max="10080"
        disabled={!policy.customer_edits_enabled}
        value={policy.customer_edit_cutoff_minutes}
        onChange={(event) =>
          setPolicy({
            ...policy,
            customer_edit_cutoff_minutes: Number(event.target.value),
          })
        }
      />

      <label>
        <input
          type="checkbox"
          checked={policy.customer_cancellations_enabled}
          onChange={(event) =>
            setPolicy({
              ...policy,
              customer_cancellations_enabled: event.target.checked,
            })
          }
        />{" "}
        Allow guests to cancel their reservation
      </label>
      <FieldInput
        label="Cancellation cutoff (minutes before reservation)"
        type="number"
        min="0"
        max="10080"
        disabled={!policy.customer_cancellations_enabled}
        value={policy.customer_cancellation_cutoff_minutes}
        onChange={(event) =>
          setPolicy({
            ...policy,
            customer_cancellation_cutoff_minutes: Number(event.target.value),
          })
        }
      />
      <small>Use 0 to allow the action until the reservation time.</small>
      <ActionButton type="submit" disabled={saving}>
        {saving ? "Saving policy…" : "Save reservation policy"}
      </ActionButton>
      {notice && <Notice tone="info" title="Reservation policy">{notice}</Notice>}
    </form>
  );
}

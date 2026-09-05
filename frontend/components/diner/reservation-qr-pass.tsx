"use client";

import { useEffect, useState } from "react";

type Props = { passUrl: string; reservationReference: string };

/**
 * Renders the opaque check-in pass locally.  Keeping encoding in the browser
 * means the capability never has to be sent to a third-party QR image host.
 */
export function ReservationQrPass({ passUrl, reservationReference }: Props) {
  const [imageUrl, setImageUrl] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    void import("qrcode").then(({ toDataURL }) => toDataURL(passUrl, {
      errorCorrectionLevel: "M",
      margin: 2,
      width: 720,
      color: { dark: "#17271f", light: "#fffdf8" },
    })).then((url) => {
      if (active) setImageUrl(url);
    }).catch(() => {
      if (active) setMessage("The check-in pass could not be rendered. Please try again.");
    });
    return () => { active = false; };
  }, [passUrl]);

  function download() {
    if (!imageUrl) return;
    const link = document.createElement("a");
    link.href = imageUrl;
    link.download = `chowly-reservation-${reservationReference}.png`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setMessage("QR image downloaded. Show it only to restaurant staff at arrival.");
  }

  return <section className="reservation-qr-card" aria-label="Your private check-in QR pass">
    <p className="eyebrow">Arrival pass</p>
    <h2>Ready when you are.</h2>
    <p>Show this QR to a waiter on arrival. It is a private check-in key, not a receipt or a table-order QR.</p>
    {imageUrl ? <>
      {/* This is an in-memory data URL generated locally, not a remotely hosted content image. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageUrl} alt="Private reservation check-in QR code" />
    </> : <p className="field-hint">Preparing your QR pass…</p>}
    <button className="button primary" type="button" disabled={!imageUrl} onClick={download}>Download QR image</button>
    <p className="field-hint">Do not post or share this code. Ask the restaurant to reissue it if it is exposed.</p>
    {message && <p className="field-hint" role="status">{message}</p>}
  </section>;
}

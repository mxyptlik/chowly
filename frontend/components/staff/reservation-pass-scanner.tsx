"use client";

import { useEffect, useRef, useState } from "react";
import { BrowserQRCodeReader } from "@zxing/browser";

function passFrom(raw: string) {
  const text = raw.trim();
  try {
    const url = new URL(text);
    return url.searchParams.get("pass") ?? text;
  } catch { return text.includes("pass=") ? text.split("pass=")[1]?.split("&")[0] ?? "" : text; }
}

declare global {
  interface Window {
    BarcodeDetector?: {
      new (options?: { formats?: string[] }): {
        detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>;
      };
    };
  }
}

export function ReservationPassScanner({ onPass }: { onPass: (pass: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanningRef = useRef(false);
  const [state, setState] = useState<"idle" | "scanning" | "denied">("idle");
  const [message, setMessage] = useState("");

  function stopCamera() {
    scanningRef.current = false;
    if (streamRef.current) streamRef.current.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setState("idle");
  }

  useEffect(() => () => stopCamera(), []);

  async function startCamera() {
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    } catch {
      setState("denied");
      setMessage("Camera access was not granted. Paste the pass or link below instead.");
      return;
    }

    scanningRef.current = true;
    setState("scanning");
    setMessage("Starting camera…");
    streamRef.current = stream;

    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const video = videoRef.current;
    if (!video) { stopCamera(); return; }
    if (!scanningRef.current) { stopCamera(); return; }

    video.srcObject = stream;
    await video.play();
    setMessage("Point the camera at the guest’s QR pass.");

    const detector = window.BarcodeDetector;
    if (detector) {
      const nativeDetector = new detector({ formats: ["qr_code"] });
      const scan = async () => {
        if (!scanningRef.current || !videoRef.current || !streamRef.current) return;
        try {
          const found = await nativeDetector.detect(videoRef.current);
          const token = found[0] && passFrom(found[0].rawValue);
          if (token) { stopCamera(); onPass(token); return; }
        } catch { /* continue scanning */ }
        setTimeout(() => { void scan(); }, 100);
      };
      void scan();
    } else {
      const reader = new BrowserQRCodeReader();
      const scan = async () => {
        if (!scanningRef.current || !videoRef.current) return;
        try {
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
await reader.decodeFromVideoElement(videoRef.current, (result, _err, _controls) => {
            if (result && result.getText) {
              const token = passFrom(result.getText());
              if (token) { stopCamera(); onPass(token); }
            }
          });
          if (scanningRef.current) { setTimeout(() => { void scan(); }, 100); }
        } catch {
          if (scanningRef.current) { setTimeout(() => { void scan(); }, 100); }
        }
      };
      void scan();
    }
  }

  return <div className="reservation-scanner">
    <div className="reservation-scanner-head"><div><p className="eyebrow">Camera scan</p><h2>Scan guest QR</h2></div>{state === "scanning" ? <button className="button" type="button" onClick={stopCamera}>Stop camera</button> : <button className="button primary" type="button" onClick={() => void startCamera()}>Use camera</button>}</div>
    {state === "scanning" && <video className="reservation-camera" ref={videoRef} muted playsInline aria-label="Camera view for reservation QR scanning" />}
    {state === "denied" && <p className="field-hint">Camera access was not granted. Paste the pass or link below instead.</p>}
    {message && <p className="field-hint" role="status">{message}</p>}
  </div>;
}
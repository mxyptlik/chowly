"use client";

import { useEffect, useRef, useState } from "react";

type BarcodeResult = { rawValue: string };
type BarcodeDetectorLike = { detect(source: ImageBitmapSource): Promise<BarcodeResult[]> };
type BarcodeDetectorConstructor = new (options?: { formats?: string[] }) => BarcodeDetectorLike;

declare global { interface Window { BarcodeDetector?: BarcodeDetectorConstructor; } }

function passFrom(raw: string) {
  const text = raw.trim();
  try {
    const url = new URL(text);
    return url.searchParams.get("pass") ?? text;
  } catch { return text.includes("pass=") ? text.split("pass=")[1]?.split("&")[0] ?? "" : text; }
}

export function ReservationPassScanner({ onPass }: { onPass: (pass: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanningRef = useRef(false);
  const [state, setState] = useState<"idle" | "scanning" | "unsupported" | "denied">("idle");
  const [message, setMessage] = useState("");

  function stopCamera() {
    scanningRef.current = false;
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setState("idle");
  }

  useEffect(() => () => stopCamera(), []);

  async function startCamera() {
    const Detector = window.BarcodeDetector;
    if (!Detector || !navigator.mediaDevices?.getUserMedia) { setState("unsupported"); return; }
    scanningRef.current = true;
    setState("scanning");
    setMessage("Starting camera…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      if (!scanningRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const video = videoRef.current;
      if (!video) { stopCamera(); setMessage("Camera view could not start. Paste the pass or link below instead."); return; }
      if (!scanningRef.current) { stopCamera(); return; }
      video.srcObject = stream;
      await video.play();
      setMessage("Point the camera at the guest’s QR pass.");
      const detector = new Detector({ formats: ["qr_code"] });
      const scan = async () => {
        if (!scanningRef.current || !videoRef.current || !streamRef.current) return;
        try {
          const found = await detector.detect(videoRef.current);
          const token = found[0] && passFrom(found[0].rawValue);
          if (token) { stopCamera(); onPass(token); return; }
        } catch { /* A frame may be unavailable while the camera starts; continue scanning. */ }
        frameRef.current = requestAnimationFrame(() => { void scan(); });
      };
      void scan();
    } catch {
      if (!scanningRef.current) return;
      stopCamera();
      setState("denied");
      setMessage("Camera access was not granted. Paste the pass or link below instead.");
    }
  }

  return <div className="reservation-scanner">
    <div className="reservation-scanner-head"><div><p className="eyebrow">Camera scan</p><h2>Scan guest QR</h2></div>{state === "scanning" ? <button className="button" type="button" onClick={stopCamera}>Stop camera</button> : <button className="button primary" type="button" onClick={() => void startCamera()}>Use camera</button>}</div>
    {state === "scanning" && <video className="reservation-camera" ref={videoRef} muted playsInline aria-label="Camera view for reservation QR scanning" />}
    {state === "unsupported" && <p className="field-hint">This browser does not support QR camera scanning. Use the paste fallback below.</p>}
    {message && <p className="field-hint" role="status">{message}</p>}
  </div>;
}

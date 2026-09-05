import Link from "next/link";

export default function OfflinePage() {
  return (
    <main className="offline-page">
      <Link href="/" className="wordmark" aria-label="Chowly home">CHOWLY<span aria-hidden="true">°</span></Link>
      <div className="offline-mark" aria-hidden="true"><span /><span /><span /></div>
      <p className="eyebrow">Connection paused</p>
      <h1>The room is still here.</h1>
      <p>Reconnect to confirm live orders, payments, acceptance, QR changes, and other time-sensitive service actions.</p>
      <p className="action action-sun" role="status">Your browser will retry automatically</p>
    </main>
  );
}

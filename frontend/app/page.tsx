import Link from "next/link";

export default function Home() {
  return (
    <main className="landing">
      <header className="site-header">
        <Link href="/" className="wordmark">CHOWLY<span>°</span></Link>
        <nav>
          <Link href="/restaurants">Find a restaurant</Link>
          <Link href="/login">Staff sign in</Link>
        </nav>
      </header>
      <section className="hero">
        <p className="eyebrow">Restaurant experiences, unhurried</p>
        <h1>Meet somewhere<br /><em>worth remembering.</em></h1>
        <p className="hero-copy">Find a Chowly restaurant, make a reservation, or scan the QR at your table to order—no diner account needed.</p>
        <div className="hero-actions">
          <Link className="button primary" href="/restaurants">Find a restaurant</Link>
          <Link className="button quiet" href="/join">List your restaurant <span>↗</span></Link>
        </div>
      </section>
      <section className="feature-strip">
        <div><b>01</b><span>Discover a<br />table</span></div>
        <div><b>02</b><span>Reserve without<br />an account</span></div>
        <div><b>03</b><span>Scan, order,<br />settle</span></div>
      </section>
      <p className="corner-note">Built for Lagos, designed for hospitality.</p>
    </main>
  );
}

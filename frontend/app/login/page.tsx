"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ActionButton, FieldInput, Notice } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { useStaffAuth } from "../../lib/auth";

function LoginForm() {
  const { login } = useStaffAuth(); const router = useRouter(); const params = useSearchParams();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setPending(true); setError(""); try { const session = await login(email, password); const administration = session.roles.some((role) => role === "TENANT_OWNER" || role === "PLATFORM_ADMIN"); router.replace(administration ? "/admin" : session.roles.some((role) => role === "CHEF" || role === "BARTENDER") ? "/prep" : "/ops"); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Unable to sign in."); } finally { setPending(false); } }
  return <main className="auth-page"><section className="auth-story"><Link href="/" className="wordmark">CHOWLY<span aria-hidden="true">°</span></Link><div className="auth-story-copy"><p className="eyebrow">Restaurant operations, in rhythm</p><h1>Make every<br /><em>service moment</em><br />count.</h1><p>One calm workspace for the floor, kitchen, bar, and the decisions that keep a restaurant moving.</p><div className="auth-proof"><span>QR-first dining</span><span>Live order flow</span><span>Privacy by role</span></div></div><p className="auth-footnote">Built for the pace of a real dining room.</p></section><section className="auth-panel"><div className="auth-card"><p className="eyebrow">Staff access</p><h2>Welcome back.</h2><p className="auth-intro">Sign in with the work account assigned by your restaurant.</p>{params.get("expired") && <Notice tone="warning" title="Your session ended">Sign in again to continue safely.</Notice>}<form onSubmit={submit}><FieldInput label="Work email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /><FieldInput label="Password" type="password" autoComplete="current-password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />{error && <Notice tone="danger" title="Sign-in failed">{error}</Notice>}<ActionButton type="submit" pending={pending}>Sign in to Chowly</ActionButton></form></div></section></main>;
}

export default function LoginPage() {
  return <Suspense fallback={<main className="auth-page" aria-busy="true" />}> <LoginForm /> </Suspense>;
}

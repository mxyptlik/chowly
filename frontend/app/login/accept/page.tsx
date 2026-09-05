"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ActionButton, FieldInput, Notice } from "../../../components/ui";
import { apiClient, ApiError } from "../../../lib/api";
import { useStaffAuth } from "../../../lib/auth";

function AcceptInvitationForm() {
  const token = useSearchParams().get("token") ?? ""; const router = useRouter(); const { refresh } = useStaffAuth(); const [password, setPassword] = useState(""); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setPending(true); setError(""); try { await apiClient.post("/staff/auth/invitations/accept", { token, password }); const session = await refresh(); const administration = session?.roles.includes("TENANT_OWNER") || session?.roles.includes("PLATFORM_ADMIN"); router.replace(administration ? "/admin" : session?.roles.includes("CHEF") || session?.roles.includes("BARTENDER") ? "/prep" : "/ops"); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "This invitation could not be accepted."); } finally { setPending(false); } }
  return <main className="auth-page"><section className="auth-story"><Link href="/" className="wordmark">CHOWLY<span aria-hidden="true">°</span></Link><div className="auth-story-copy"><p className="eyebrow">Your restaurant invited you</p><h1>Join the<br /><em>service rhythm.</em></h1><p>Your account gives you only the tools and restaurant locations your role requires.</p></div><p className="auth-footnote">Clear service. Clear responsibility.</p></section><section className="auth-panel"><div className="auth-card"><p className="eyebrow">Invitation acceptance</p><h2>Set your password.</h2><p className="auth-intro">Use a strong password to activate your staff account.</p>{!token ? <Notice tone="danger" title="Missing invitation">Open the complete invitation link supplied by your manager.</Notice> : <form onSubmit={submit}><FieldInput label="Choose a password" type="password" autoComplete="new-password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} hint="At least 10 characters." required />{error && <Notice tone="danger" title="Invitation unavailable">{error}</Notice>}<ActionButton type="submit" pending={pending}>Activate staff account</ActionButton></form>}</div></section></main>;
}

export default function AcceptInvitationPage() {
  return <Suspense fallback={<main className="auth-page" aria-busy="true" />}> <AcceptInvitationForm /> </Suspense>;
}

"use client";

import {
  FormEvent,
  Suspense,
  useState,
} from "react";
import Link from "next/link";
import {
  useRouter,
  useSearchParams,
} from "next/navigation";

import {
  ActionButton,
  FieldInput,
  Notice,
} from "../../components/ui";

import { ApiError } from "../../lib/api";
import { useStaffAuth } from "../../lib/auth";

import {
  DEMO_MODE_ENABLED,
  DEMO_PERSONAS,
  defaultStaffHome,
  demoPersonaHome,
  type DemoPersona,
} from "../../lib/demo-personas";


function LoginForm() {
  const { login, demoLogin } = useStaffAuth();

  const router = useRouter();
  const params = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [error, setError] = useState("");

  const [pending, setPending] = useState(false);

  const [demoPending, setDemoPending] =
    useState<DemoPersona | null>(null);


  async function submit(event: FormEvent) {
    event.preventDefault();

    setPending(true);
    setError("");

    try {
      const session = await login(
        email,
        password,
      );

      router.replace(
        defaultStaffHome(session),
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Unable to sign in.",
      );
    } finally {
      setPending(false);
    }
  }


  async function enterDemo(
    persona: DemoPersona,
  ) {
    setDemoPending(persona);
    setError("");

    try {
      await demoLogin(persona);

      router.replace(
        demoPersonaHome(persona),
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Unable to open the demo workspace.",
      );
    } finally {
      setDemoPending(null);
    }
  }


  return (
    <main className="auth-page">

      <section className="auth-story">

        <Link
          href="/"
          className="wordmark"
        >
          CHOWLY
          <span aria-hidden="true">
            °
          </span>
        </Link>

        <div className="auth-story-copy">

          <p className="eyebrow">
            Restaurant operations, in rhythm
          </p>

          <h1>
            Make every
            <br />

            <em>
              service moment
            </em>

            <br />
            count.
          </h1>

          <p>
            One calm workspace for the floor,
            kitchen, bar, and the decisions
            that keep a restaurant moving.
          </p>

          <div className="auth-proof">
            <span>QR-first dining</span>
            <span>Live order flow</span>
            <span>Privacy by role</span>
          </div>

        </div>

        <p className="auth-footnote">
          Built for the pace of a real dining room.
        </p>

      </section>


      <section className="auth-panel">

        <div className="auth-card">

          <p className="eyebrow">
            Staff access
          </p>

          <h2>
            {DEMO_MODE_ENABLED
              ? "Choose a workspace."
              : "Welcome back."}
          </h2>

          <p className="auth-intro">
            {DEMO_MODE_ENABLED
              ? "Assessors can enter a predefined staff persona with one click. Chowly still creates a real server-side staff session underneath."
              : "Sign in with the work account assigned by your restaurant."}
          </p>


          {params.get("expired") && (
            <Notice
              tone="warning"
              title="Your session ended"
            >
              Sign in again to continue safely.
            </Notice>
          )}


          {error && (
            <Notice
              tone="danger"
              title="Sign-in failed"
            >
              {error}
            </Notice>
          )}


          {DEMO_MODE_ENABLED && (
            <>

              <section
                className="demo-access"
                aria-labelledby="demo-access-title"
              >

                <div className="demo-access-heading">

                  <div>

                    <p className="eyebrow">
                      Assessor demo
                    </p>

                    <h3 id="demo-access-title">
                      Explore by role
                    </h3>

                  </div>

                  <span className="demo-access-badge">
                    No password required
                  </span>

                </div>


                <Link
                  className="demo-diner-link"
                  href="/restaurants"
                >
                  <span>
                    <small>
                      Public experience
                    </small>

                    <strong>
                      Explore as diner
                    </strong>
                  </span>

                  <b aria-hidden="true">
                    →
                  </b>
                </Link>


                <div className="demo-persona-grid">

                  {DEMO_PERSONAS.map(
                    (persona) => (

                      <button
                        key={persona.id}
                        type="button"
                        className="demo-persona-card"
                        disabled={
                          demoPending !== null
                        }
                        aria-busy={
                          demoPending === persona.id ||
                          undefined
                        }
                        onClick={() =>
                          void enterDemo(
                            persona.id,
                          )
                        }
                      >

                        <span className="demo-persona-copy">

                          <small>
                            {persona.eyebrow}
                          </small>

                          <strong>
                            {persona.label}
                          </strong>

                          <span>
                            {persona.description}
                          </span>

                        </span>

                        <b aria-hidden="true">
                          {demoPending ===
                          persona.id
                            ? "…"
                            : "→"}
                        </b>

                      </button>

                    ),
                  )}

                </div>

              </section>


              <div className="auth-divider">
                <span>
                  or use a staff account
                </span>
              </div>

            </>
          )}


          <form onSubmit={submit}>

            <FieldInput
              label="Work email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) =>
                setEmail(
                  event.target.value,
                )
              }
              required
            />

            <FieldInput
              label="Password"
              type="password"
              autoComplete="current-password"
              minLength={10}
              value={password}
              onChange={(event) =>
                setPassword(
                  event.target.value,
                )
              }
              required
            />

            <ActionButton
              type="submit"
              pending={pending}
            >
              Sign in to Chowly
            </ActionButton>

          </form>

        </div>

      </section>

    </main>
  );
}


export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main
          className="auth-page"
          aria-busy="true"
        />
      }
    >
      <LoginForm />
    </Suspense>
  );
}
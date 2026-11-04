"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, destinationForRole, getToken, getUser, LoginResult, setSession } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<MessageState>(null);
  const [submitting, setSubmitting] = useState(false);

  // If already logged in, skip straight to the right dashboard.
  useEffect(() => {
    const user = getUser();
    if (getToken() && user) {
      router.replace(destinationForRole(user.role));
    }
  }, [router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    setSubmitting(true);
    try {
      const result = await apiFetch<LoginResult>("/auth/login", { method: "POST", json: { email, password } });
      setSession(result.token, result.user);
      router.push(destinationForRole(result.user.role));
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : "Login failed", kind: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      {/* Branding: navy panel with the gold rule; on small screens a band above the form. */}
      <aside className="flex flex-col justify-between border-b-2 border-accent bg-brand-700 px-6 py-8 text-white sm:px-10 lg:border-r-2 lg:border-b-0 lg:py-12">
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="flex h-11 w-11 items-center justify-center rounded-md border border-white/40 bg-white/10 text-sm font-semibold tracking-wide"
          >
            AE
          </span>
          <span className="text-lg font-semibold leading-tight">Assignment Evaluation Platform</span>
        </div>
        <div className="mt-8 max-w-md lg:mt-0">
          <h2 className="text-2xl font-semibold leading-snug sm:text-3xl">
            Submit, evaluate and review coursework in one place.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-brand-100">
            For students, instructors and administrators: assignment submission, rubric grading with automated
            evaluation as a second opinion, and similarity checks that support academic integrity. Instructors always
            have the final say.
          </p>
        </div>
        <p className="mt-8 hidden text-xs text-brand-100 lg:block">
          Accounts are issued by your administrator.
        </p>
      </aside>

      <main className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold">Log in</h1>
          <p className="mt-1 text-sm text-gray-600">
            Use the email and password your administrator gave you. Don&apos;t have an account? Ask them to create one.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <label htmlFor="email" className="block text-sm font-semibold">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1 mb-4 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm"
            />

            <label htmlFor="password" className="block text-sm font-semibold">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="********"
              className="mt-1 mb-5 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm"
            />

            <button type="submit" disabled={submitting} className="btn-primary w-full px-4 py-2.5 text-sm">
              {submitting ? "Logging in..." : "Log in"}
            </button>

            <Message state={message} />
          </form>
        </div>
      </main>
    </div>
  );
}

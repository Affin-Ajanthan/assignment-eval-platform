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
    <div className="mx-auto max-w-sm px-4 py-12">
      <h1 className="text-2xl font-bold">Log in</h1>
      <p className="mt-1 text-sm text-gray-600">
        Accounts are created by an administrator -- ask them for your email and password if you don&apos;t have one yet.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <label htmlFor="email" className="block text-sm font-semibold">
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="mt-1 mb-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />

        <label htmlFor="password" className="block text-sm font-semibold">
          Password
        </label>
        <input
          id="password"
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="********"
          className="mt-1 mb-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {submitting ? "Logging in..." : "Log in"}
        </button>

        <Message state={message} />
      </form>
    </div>
  );
}

"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  apiFetch,
  destinationForRole,
  getToken,
  getUser,
  logout,
  passwordProblems,
  setSession,
  UserInfo,
} from "@/lib/api";
import Message, { MessageState } from "@/components/Message";

// The rule, in the order it is shown; each line is met when passwordProblems no longer names it.
const RULES: { label: string; problem: string }[] = [
  { label: "At least 8 characters", problem: "at least 8 characters" },
  { label: "An uppercase letter (A-Z)", problem: "an uppercase letter" },
  { label: "A lowercase letter (a-z)", problem: "a lowercase letter" },
  { label: "A number (0-9)", problem: "a number" },
  { label: "A special character, such as ! @ # $ %", problem: "a special character (such as ! @ # $ %)" },
];

/** Choose your own password. A student or instructor is sent here at their first login, while their account still
 * has the password the administrator gave it (must_change_password); nothing else works until it is changed. */
export default function ChangePasswordPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<MessageState>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!getToken() || !u) {
      router.replace("/login");
      return;
    }
    setUser(u);
  }, [router]);

  const problems = passwordProblems(next);
  const mismatch = confirm !== "" && confirm !== next;
  const canSave = !saving && current !== "" && problems.length === 0 && confirm === next;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setMessage(null);
    setSaving(true);
    try {
      const updated = await apiFetch<UserInfo>("/auth/change-password", {
        method: "POST",
        json: { current_password: current, new_password: next },
      });
      setSession(getToken() ?? "", updated);
      router.replace(destinationForRole(updated.role));
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : "Could not change the password", kind: "error" });
      setSaving(false);
    }
  }

  async function handleLogout() {
    await logout();
    router.replace("/login?reason=signed-out");
  }

  if (!user) return null;
  const forced = !!user.must_change_password;

  return (
    <main className="flex min-h-screen items-center justify-center bg-page px-4 py-10">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold">{forced ? "Choose your own password" : "Change your password"}</h1>
        <p className="mt-1 text-sm text-gray-600">
          {forced
            ? "Your administrator set your first password. Before you continue, replace it with a password only you know."
            : "Enter your current password, then the new one."}
        </p>

        <form onSubmit={handleSubmit} noValidate className="card mt-6">
          <p className="text-sm text-gray-600">
            Signed in as <span className="font-semibold text-gray-900">{user.email}</span>
          </p>

          <label htmlFor="current-password" className="mt-4 block text-sm font-semibold">
            {forced ? "Password from your administrator" : "Current password"}
          </label>
          <input
            id="current-password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm"
          />

          <label htmlFor="new-password" className="mt-4 block text-sm font-semibold">
            New password
          </label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            required
            aria-describedby="password-rules"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm"
          />
          <ul id="password-rules" className="mt-2 space-y-1 text-sm" aria-live="polite">
            {RULES.map((r) => {
              const met = next !== "" && !problems.includes(r.problem);
              return (
                <li key={r.label} className={met ? "text-green-800" : "text-gray-600"}>
                  <span aria-hidden="true" className="inline-block w-5 font-semibold">
                    {met ? "✓" : "•"}
                  </span>
                  {r.label}
                  <span className="sr-only">{met ? " (done)" : " (still needed)"}</span>
                </li>
              );
            })}
          </ul>

          <label htmlFor="confirm-password" className="mt-4 block text-sm font-semibold">
            Type the new password again
          </label>
          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            required
            aria-invalid={mismatch}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm"
          />
          {mismatch && <p className="mt-1 text-sm text-red-700">The two new passwords are not the same.</p>}

          <button type="submit" disabled={!canSave} className="btn-primary mt-5 w-full px-4 py-2.5 text-sm">
            {saving ? "Saving..." : "Save new password"}
          </button>
          <Message state={message} />
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Not you?{" "}
          <button type="button" onClick={handleLogout} className="font-semibold text-blue-700 hover:underline">
            Log out
          </button>
        </p>
      </div>
    </main>
  );
}

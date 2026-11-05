"use client";

import Link from "next/link";

/** Shown when a page fails while rendering: what happened, a retry, and a way back. Nothing is lost on the server. */
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div role="alert" className="card w-full max-w-lg text-center">
        <span
          aria-hidden="true"
          className="mx-auto flex h-11 w-11 items-center justify-center rounded-md bg-brand-700 text-sm font-semibold text-white"
        >
          AE
        </span>
        <h1 className="mt-4 text-2xl font-semibold">Something went wrong</h1>
        <p className="mt-2 text-sm text-gray-600">
          This page could not be shown. Your saved work is safe on the server. Try again, or go back to your
          dashboard; if it keeps happening, tell your administrator.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <button type="button" onClick={reset} className="btn-primary px-4 py-2 text-sm">
            Try again
          </button>
          <Link href="/" className="btn-secondary px-4 py-2 text-sm">
            Go to my dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}

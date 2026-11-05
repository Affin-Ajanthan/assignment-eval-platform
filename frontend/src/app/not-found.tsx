import Link from "next/link";

/** Shown for any address the app does not have: the platform's look, and a way back. */
export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="card w-full max-w-lg text-center">
        <span
          aria-hidden="true"
          className="mx-auto flex h-11 w-11 items-center justify-center rounded-md bg-brand-700 text-sm font-semibold text-white"
        >
          AE
        </span>
        <p className="mt-4 text-sm font-semibold text-gray-500">Error 404</p>
        <h1 className="mt-1 text-2xl font-semibold">Page not found</h1>
        <p className="mt-2 text-sm text-gray-600">
          The page you asked for does not exist or has moved. Check the address, or go back to your dashboard.
        </p>
        <Link href="/" className="btn-primary mt-6 px-4 py-2 text-sm">
          Go to my dashboard
        </Link>
      </div>
    </main>
  );
}

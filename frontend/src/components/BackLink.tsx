import Link from "next/link";

/**
 * The way back to the page above this one: a light outlined button, the same on every portal. It is a real link, so
 * it can still be opened in a new tab. A long label (a subject's full name) is cut short rather than widening the page.
 */
export default function BackLink({ href, label, testId }: { href: string; label: string; testId?: string }) {
  return (
    <Link
      href={href}
      className="group flex min-h-11 w-fit max-w-full items-center gap-2 rounded-md border border-gray-300 bg-white px-3 text-sm font-semibold text-blue-700 hover:border-gray-400 hover:bg-gray-50 md:min-h-9"
      data-testid={testId}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-4 w-4 shrink-0 transition-transform group-hover:-translate-x-0.5 motion-reduce:transition-none"
      >
        <path d="M13 8H3M7 4 3 8l4 4" />
      </svg>
      <span className="min-w-0 truncate">{label}</span>
    </Link>
  );
}

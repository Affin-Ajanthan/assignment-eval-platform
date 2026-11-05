import Link from "next/link";
import { ReactNode } from "react";

/**
 * The heading of every page: an optional way back, the title, a line or two about the page, and on the right
 * the page's own controls (a subject picker, a filter). One look on every portal.
 */
export default function PageHeader({
  title,
  description,
  back,
  divider = true,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  back?: { href: string; label: string };
  /** False when tabs follow, which draw their own line. */
  divider?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={divider ? "mb-6 border-b border-gray-200 pb-5" : "mb-2"}>
      {back && (
        <Link href={back.href} className="inline-block text-sm font-semibold text-blue-700 hover:underline">
          ← {back.label}
        </Link>
      )}
      <div className={`flex flex-wrap items-end justify-between gap-x-6 gap-y-4 ${back ? "mt-3" : ""}`}>
        <div className="min-w-0 max-w-3xl">
          <h1 className="text-2xl font-semibold">{title}</h1>
          {description && <div className="mt-1.5 text-sm text-gray-600">{description}</div>}
        </div>
        {children && <div className="flex flex-wrap items-end gap-3">{children}</div>}
      </div>
    </div>
  );
}

/** One figure in an overview strip: a count with its label, optionally a link to the part of the page it counts. */
export function StatTile({
  label,
  value,
  tone = "neutral",
  href,
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "attention" | "good";
  href?: string;
}) {
  const accent =
    tone === "attention" ? "border-l-amber-500" : tone === "good" ? "border-l-green-700" : "border-l-brand-700";
  const body = (
    <>
      <span className="block text-2xl font-semibold text-gray-900">{value}</span>
      <span className="block text-sm text-gray-600">{label}</span>
    </>
  );
  const cls = `card block border-l-4 ${accent} p-4 sm:p-4`;
  return href ? (
    <a href={href} className={`${cls} hover:bg-gray-50`}>
      {body}
    </a>
  ) : (
    <div className={cls}>{body}</div>
  );
}

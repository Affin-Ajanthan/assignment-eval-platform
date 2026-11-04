import Link from "next/link";
import { ReactNode } from "react";
import AccountBar from "@/components/AccountBar";
import { UserInfo } from "@/lib/api";

/** The frame of the assignment pages (new and edit): account bar, a way back to the dashboard, a heading. */
export default function AssignmentPageLayout({
  user,
  backHref,
  title,
  subtitle,
  children,
}: {
  user: UserInfo;
  backHref: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <>
      <AccountBar user={user} width="max-w-4xl" />
      <main className="mx-auto max-w-4xl px-4 py-8">
      <Link href={backHref} className="text-sm font-semibold text-blue-700 hover:underline">
        ← Back to the instructor dashboard
      </Link>
      <h1 className="mt-4 text-2xl font-semibold">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-gray-600">{subtitle}</p>}
      <section className="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm sm:p-6">{children}</section>
      </main>
    </>
  );
}

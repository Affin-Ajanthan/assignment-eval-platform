import { ReactNode } from "react";
import AccountBar from "@/components/AccountBar";
import PageHeader from "@/components/PageHeader";
import { UserInfo } from "@/lib/api";

/** The frame of the assignment pages (new and edit): account bar, a way back to the dashboard, a heading. */
export default function AssignmentPageLayout({
  user,
  backHref,
  backLabel = "Back to the subject",
  title,
  subtitle,
  children,
}: {
  user: UserInfo;
  backHref: string;
  backLabel?: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <>
      <AccountBar user={user} width="max-w-4xl" />
      <main className="mx-auto max-w-4xl px-4 py-8">
      <PageHeader title={title} description={subtitle} back={{ href: backHref, label: backLabel }} />
      <section className="card">{children}</section>
      </main>
    </>
  );
}

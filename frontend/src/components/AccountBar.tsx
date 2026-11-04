"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { destinationForRole, logout, UserInfo } from "@/lib/api";

const ROLE_LABEL: Record<UserInfo["role"], string> = {
  admin: "Administrator",
  instructor: "Instructor",
  student: "Student",
};

/** The header of every signed-in page: a full-width navy bar with the platform's name (back to the user's
 * dashboard), who is signed in, and Log out. `width` lines its content up with the page below it. */
export default function AccountBar({
  user,
  width = "max-w-6xl",
}: {
  user: UserInfo;
  width?: string;
}) {
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace("/login?reason=signed-out");
  }

  return (
    <header className="border-b-2 border-accent bg-brand-700 text-white">
      <div className={`mx-auto flex ${width} flex-wrap items-center justify-between gap-3 px-4 py-3`}>
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href={destinationForRole(user.role)}
            className="flex items-center gap-2.5 rounded-md font-semibold text-white"
            aria-label="Assignment Evaluation Platform: go to your dashboard"
          >
            <span
              aria-hidden="true"
              className="flex h-9 w-9 items-center justify-center rounded-md border border-white/40 bg-white/10 text-xs font-semibold tracking-wide"
            >
              AE
            </span>
            <span className="hidden leading-tight sm:block">
              <span className="block text-base">Assignment Evaluation Platform</span>
              <span className="block text-xs font-normal text-brand-100">{ROLE_LABEL[user.role]} portal</span>
            </span>
          </Link>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-right text-sm leading-tight">
            <span className="block font-semibold">{user.full_name}</span>
            <span className="block text-xs text-brand-100">{ROLE_LABEL[user.role]}</span>
          </span>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-md border border-white/60 px-3 py-1.5 text-sm font-semibold text-white hover:bg-white/10"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  );
}

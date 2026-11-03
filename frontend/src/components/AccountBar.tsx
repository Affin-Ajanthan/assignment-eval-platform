"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { destinationForRole, logout, UserInfo } from "@/lib/api";

const ROLE_LABEL: Record<UserInfo["role"], string> = {
  admin: "Admin",
  instructor: "Instructor",
  student: "Student",
};

/** The header of every signed-in page: the platform's name (back to the user's dashboard), what the page is
 * about (`context`, e.g. the subject open on the dashboard), who is signed in, and Log out. */
export default function AccountBar({ user, context }: { user: UserInfo; context?: string }) {
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <header className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 pb-4">
      <div className="flex min-w-0 items-center gap-3">
        <Link
          href={destinationForRole(user.role)}
          className="flex items-center gap-2 font-bold text-gray-900 hover:text-blue-700"
          aria-label="Assignment Evaluation Platform: go to your dashboard"
        >
          <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600 text-xs text-white">
            AE
          </span>
          <span className="hidden sm:inline">Assignment Evaluation Platform</span>
        </Link>
        {context && (
          <span className="truncate rounded-md bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-700" title={context}>
            {context}
          </span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="text-right text-sm leading-tight">
          <span className="block font-semibold text-gray-900">{user.full_name}</span>
          <span className="block text-xs text-gray-500">{ROLE_LABEL[user.role]}</span>
        </span>
        <button
          type="button"
          onClick={handleLogout}
          className="rounded-md bg-gray-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
        >
          Log out
        </button>
      </div>
    </header>
  );
}

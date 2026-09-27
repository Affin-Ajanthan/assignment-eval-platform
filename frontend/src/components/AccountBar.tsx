"use client";

import { useRouter } from "next/navigation";
import { logout, UserInfo } from "@/lib/api";

export default function AccountBar({ user }: { user: UserInfo }) {
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="mb-6 flex items-center justify-between">
      <span className="text-sm text-gray-500">
        Signed in as {user.full_name} ({user.role})
      </span>
      <button
        type="button"
        onClick={handleLogout}
        className="rounded-md bg-gray-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
      >
        Log out
      </button>
    </div>
  );
}

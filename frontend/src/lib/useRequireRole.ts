"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken, getUser, Role, UserInfo } from "./api";

/** Call at the top of a role-specific page. Sends the reader to the
 * login page if they aren't logged in, or are logged in as the wrong
 * role for this page. Returns { user, ready } -- render nothing (or a
 * loading state) until `ready` is true, since the check only runs
 * after mount (localStorage isn't available during server rendering). */
export function useRequireRole(role: Role): { user: UserInfo | null; ready: boolean } {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!getToken() || !u || u.role !== role) {
      router.replace("/login");
      return;
    }
    setUser(u);
    setReady(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  return { user, ready };
}

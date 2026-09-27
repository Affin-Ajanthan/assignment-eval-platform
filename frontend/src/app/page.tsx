"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { destinationForRole, getToken, getUser } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const user = getUser();
    if (getToken() && user) {
      router.replace(destinationForRole(user.role));
    } else {
      router.replace("/login");
    }
  }, [router]);

  return null;
}

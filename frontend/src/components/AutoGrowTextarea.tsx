"use client";

import { TextareaHTMLAttributes, useRef } from "react";
import { useAutoHeight } from "@/lib/useAutoHeight";

/** A textarea that grows with its text up to 15 lines, then scrolls (see useAutoHeight). */
export default function AutoGrowTextarea({
  value,
  className = "",
  ...props
}: { value: string } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value">) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoHeight(ref, value);
  return <textarea ref={ref} value={value} className={`block resize-none leading-5 ${className}`} {...props} />;
}

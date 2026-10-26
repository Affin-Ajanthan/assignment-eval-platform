import { ReactNode } from "react";

/** A small coloured pill: statuses, bands. `tone` carries the colour classes. */
export default function Badge({
  tone,
  bold = true,
  children,
}: {
  tone: string;
  bold?: boolean;
  children: ReactNode;
}) {
  return <span className={`rounded px-2 py-0.5 text-xs ${bold ? "font-semibold" : ""} ${tone}`}>{children}</span>;
}

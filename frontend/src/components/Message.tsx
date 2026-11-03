// "warning": a result that needs a look (flagged pairs), not a failure.
export type MessageState = { text: string; kind: "success" | "error" | "warning" | "info" } | null;

const STYLE: Record<NonNullable<MessageState>["kind"], string> = {
  success: "bg-green-50 text-green-800",
  error: "bg-red-50 text-red-700",
  warning: "bg-amber-50 text-amber-900",
  info: "bg-blue-50 text-blue-800",
};

/** Announced by screen readers: errors at once (alert), the others when the reader is idle (status). */
export default function Message({ state }: { state: MessageState }) {
  if (!state) return null;
  return (
    <div
      role={state.kind === "error" ? "alert" : "status"}
      className={`mt-3 rounded-md px-3 py-2 text-sm ${STYLE[state.kind]}`}
    >
      {state.text}
    </div>
  );
}

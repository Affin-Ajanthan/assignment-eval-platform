export type MessageState = { text: string; kind: "success" | "error" } | null;

export default function Message({ state }: { state: MessageState }) {
  if (!state) return null;
  const cls =
    state.kind === "success"
      ? "bg-green-50 text-green-800"
      : "bg-red-50 text-red-700";
  return <div className={`mt-3 rounded-md px-3 py-2 text-sm ${cls}`}>{state.text}</div>;
}

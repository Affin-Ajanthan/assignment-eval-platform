import { AISignal, AutoEvaluation } from "@/lib/api";

const BADGE: Record<AISignal["signal"], { text: string; cls: string }> = {
  low: { text: "Low", cls: "bg-green-50 text-green-800" },
  medium: { text: "Medium", cls: "bg-yellow-50 text-yellow-800" },
  high: { text: "High", cls: "bg-red-50 text-red-700" },
};

function methodLabel(method: string): string {
  if (method.startsWith("fast-detectgpt:")) return `Fast-DetectGPT (${method.split(":")[1]})`;
  return "Style heuristic";
}

function Row({ label, signal, missing }: { label: string; signal: AISignal | null; missing: string }) {
  return (
    <tr>
      <td className="border border-gray-200 px-3 py-1.5 align-top font-semibold">{label}</td>
      <td className="border border-gray-200 px-3 py-1.5 align-top">
        {signal ? (
          <span className={`rounded px-2 py-0.5 text-xs font-semibold ${BADGE[signal.signal].cls}`}>
            {BADGE[signal.signal].text}
          </span>
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </td>
      <td className="border border-gray-200 px-3 py-1.5 align-top text-xs text-gray-700">
        {signal ? (
          <>
            <div className="text-gray-500">{methodLabel(signal.method)}</div>
            <ul className="ml-4 list-disc">
              {signal.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </>
        ) : (
          missing
        )}
      </td>
    </tr>
  );
}

/** Always shows the report and code AI-content estimates, whatever their level. */
export default function AISignalsPanel({ result }: { result: AutoEvaluation }) {
  const signals = result.ai_signals;
  return (
    <div className="mt-4 rounded-md border border-gray-200 p-4">
      <h4 className="font-bold">AI-content signals</h4>
      <p className="mt-1 text-xs text-gray-600">
        Statistical estimates of whether the report or code looks machine-generated. These are review signals, not
        proof: they misfire on formal or non-native English writing and on tidy code, and they never change the
        suggested score.
      </p>
      {!signals ? (
        <p className="mt-2 text-sm text-gray-600">
          Not available for this evaluation (it predates this section) — run the auto-evaluation again.
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left">
                <th className="border border-gray-200 px-3 py-1.5">Part</th>
                <th className="border border-gray-200 px-3 py-1.5">Signal</th>
                <th className="border border-gray-200 px-3 py-1.5">Details</th>
              </tr>
            </thead>
            <tbody>
              <Row label="Report" signal={signals.report} missing="No readable report submitted" />
              <Row label="Code" signal={signals.code} missing="No code submitted" />
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

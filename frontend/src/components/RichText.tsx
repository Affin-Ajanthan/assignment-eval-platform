import { ReactNode } from "react";

// Descriptions are written with a small Markdown-like syntax (the instructor's RichTextEditor inserts it):
//   **bold**   *italic*   `code`   ``` fenced code block ```
//   - bullet   1. numbered   # / ## / ### bigger text   -# smaller text
// It is turned into React elements, never into HTML, so nothing a user types can run as a script. Text written
// before this existed has none of it and shows as it always did (line breaks kept).

type Block =
  | { kind: "text"; size: TextSize; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string };

export type TextSize = "small" | "normal" | "large" | "larger" | "largest";

/** The line prefix that sets each size ("" = normal). */
export const SIZE_PREFIX: Record<TextSize, string> = { small: "-# ", normal: "", large: "### ", larger: "## ", largest: "# " };

const SIZE_CLASS: Record<TextSize, string> = {
  small: "text-xs",
  normal: "",
  large: "text-base font-semibold",
  larger: "text-lg font-bold",
  largest: "text-2xl font-bold",
};

const FENCE = /^```/;
const HEADING = /^(#{1,3}) (.*)$/;
const SMALL = /^-# (.*)$/;
const BULLET = /^\s*[-*] (.*)$/;
const NUMBERED = /^\s*\d+[.)] (.*)$/;

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];
  const endParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: "text", size: "normal", text: paragraph.join("\n") });
    paragraph = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (FENCE.test(line)) {
      endParagraph();
      const code: string[] = [];
      for (i++; i < lines.length && !FENCE.test(lines[i]); i++) code.push(lines[i]);
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    const small = SMALL.exec(line);
    if (heading || small) {
      endParagraph();
      if (small) blocks.push({ kind: "text", size: "small", text: small[1] });
      else blocks.push({ kind: "text", size: (["largest", "larger", "large"] as const)[heading![1].length - 1], text: heading![2] });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      endParagraph();
      const ordered = numbered !== null;
      const last = blocks[blocks.length - 1];
      const item = (bullet ?? numbered)![1];
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(item);
      else blocks.push({ kind: "list", ordered, items: [item] });
      continue;
    }
    if (line.trim() === "") endParagraph();
    else paragraph.push(line);
  }
  endParagraph();
  return blocks;
}

const INLINE = /`([^`\n]+)`|\*\*(.+?)\*\*|\*([^*\s](?:[^*\n]*[^*\s])?)\*/g;

/** Bold, italic and inline code inside one block of text. */
function inline(text: string, keyPrefix = ""): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyPrefix}${at}`;
    if (m[1] !== undefined) {
      out.push(
        <code key={key} className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[0.9em] text-gray-900">
          {m[1]}
        </code>,
      );
    } else if (m[2] !== undefined) {
      out.push(<strong key={key}>{inline(m[2], `${key}-`)}</strong>);
    } else {
      out.push(<em key={key}>{inline(m[3], `${key}-`)}</em>);
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** A description (or any text written with the editor's syntax) as formatted text. */
export default function RichText({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`break-words ${className}`}>
      {parseBlocks(text).map((b, i) => {
        if (b.kind === "code") {
          return (
            <pre
              key={i}
              className="mt-2 overflow-auto rounded-md bg-gray-900 p-3 font-mono text-xs leading-5 text-gray-100"
            >
              {b.text}
            </pre>
          );
        }
        if (b.kind === "list") {
          const List = b.ordered ? "ol" : "ul";
          return (
            <List key={i} className={`mt-2 space-y-0.5 pl-6 ${b.ordered ? "list-decimal" : "list-disc"}`}>
              {b.items.map((item, j) => (
                <li key={j}>{inline(item)}</li>
              ))}
            </List>
          );
        }
        return (
          <p key={i} className={`mt-2 whitespace-pre-wrap first:mt-0 ${SIZE_CLASS[b.size]}`}>
            {inline(b.text)}
          </p>
        );
      })}
    </div>
  );
}

import { RefObject, useLayoutEffect } from "react";

/** The most lines a text box grows to as someone types in it; longer text scrolls inside the box. */
export const MAX_BOX_LINES = 15;

/**
 * Make a textarea as tall as its text, up to `maxLines` lines (then it scrolls up and down), and back to its
 * `rows` when text is deleted. Give the textarea a fixed line height (e.g. Tailwind's leading-5) and
 * `resize-none`. `again` is anything else that should re-measure it, such as the box being shown again.
 */
export function useAutoHeight(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  maxLines: number = MAX_BOX_LINES,
  again?: unknown,
): void {
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) return;
    const fit = () => {
      box.style.height = "auto"; // back to `rows`, so the box can shrink again
      const style = getComputedStyle(box);
      const px = (v: string) => parseFloat(v) || 0;
      const borders = px(style.borderTopWidth) + px(style.borderBottomWidth);
      const padding = px(style.paddingTop) + px(style.paddingBottom);
      const max = (px(style.lineHeight) || 20) * maxLines + padding + borders;
      const wanted = box.scrollHeight + borders;
      box.style.height = `${Math.min(wanted, max)}px`;
      box.style.overflowY = wanted > max ? "auto" : "hidden";
    };
    fit();
    window.addEventListener("resize", fit); // a narrower box wraps the text onto more lines
    return () => window.removeEventListener("resize", fit);
  }, [ref, value, maxLines, again]);
}

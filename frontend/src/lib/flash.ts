// A one-time message handed from one page to the next (e.g. "Assignment saved." after the assignment page
// sends the instructor back to the dashboard). sessionStorage can be unavailable: then there is just no message.
const KEY = "flash-message";

export function setFlash(text: string): void {
  try {
    sessionStorage.setItem(KEY, text);
  } catch {
    /* no message */
  }
}

/** The message left by the last page, once: reading it removes it. */
export function takeFlash(): string | null {
  try {
    const text = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return text;
  } catch {
    return null;
  }
}

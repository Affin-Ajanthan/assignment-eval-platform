import type { Metadata } from "next";
import { Source_Sans_3 } from "next/font/google";
import "./globals.css";

// The one typeface of the app. next/font downloads it at build time and serves it from the app itself, so no
// request goes to Google when a page is opened; "swap" shows the fallback font until it has loaded.
const sans = Source_Sans_3({ subsets: ["latin"], display: "swap", variable: "--font-source-sans" });

export const metadata: Metadata = {
  title: "AI-Assisted Assignment Evaluation Platform",
  description: "Submission portal, rubric grading, similarity checks, and automated evaluation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}

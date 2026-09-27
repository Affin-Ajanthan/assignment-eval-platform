import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI-Assisted Assignment Evaluation Platform",
  description: "Submission portal, rubric grading, similarity checks, and automated evaluation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}

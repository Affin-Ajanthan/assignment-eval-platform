import type { NextConfig } from "next";

// Security headers for every page. The login token is kept in browser storage, so if a script ever got into a page
// it could read it. The Content-Security-Policy limits the damage: scripts, styles and fonts load only from this
// site, and the page may send data only to this site and the API. A stolen token can't be sent to another server
// with fetch, an image or a form. The page also can't be framed by another site (clickjacking).
//
// Inline scripts stay allowed ('unsafe-inline'): Next.js puts its page data in inline <script> tags. Allowing only
// scripts with a per-request nonce would be stronger, but it needs a proxy (middleware) and makes every page dynamic.

/** The API's origin (scheme, host and port), from the same setting the frontend uses (src/lib/api.ts). */
function apiOrigin(): string {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").origin;
  } catch {
    return "";
  }
}

const dev = process.env.NODE_ENV !== "production";

function contentSecurityPolicy(): string {
  const api = apiOrigin();
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    // 'unsafe-eval' only for `next dev` (React Refresh needs it); a production build doesn't use eval.
    "script-src": ["'self'", "'unsafe-inline'", ...(dev ? ["'unsafe-eval'"] : [])],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],
    // The API, plus the dev server's hot-reload websocket in `next dev`.
    "connect-src": ["'self'", api, ...(dev ? ["ws:", "wss:"] : [])],
    "media-src": ["'self'", "blob:", api],
    "worker-src": ["'self'", "blob:"],
    "frame-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => [name, ...values.filter(Boolean)].join(" "))
    .join("; ");
}

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy() },
          // Older browsers that don't know frame-ancestors.
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
        ],
      },
    ];
  },
};

export default nextConfig;

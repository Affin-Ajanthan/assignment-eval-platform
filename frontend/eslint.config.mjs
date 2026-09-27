import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // This app is a client-rendered dashboard talking to an external,
      // token-authenticated FastAPI backend -- "fetch on mount, setState
      // with the result" in a useEffect is the correct, standard pattern
      // here (there's no server-side data source to prefer instead,
      // since every request needs the browser-held bearer token). This
      // rule flags that pattern as if it were always avoidable, which
      // isn't true for this architecture.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;

import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // This codebase intentionally passes around loosely-typed JSON payloads
    // from the LLM agent (dashboard data, tool results, etc.), so `any` is
    // used deliberately in several places. Keep it visible as a warning
    // instead of letting it fail `next build`.
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
      // This app fetches on mount / on tab change all over (Journal, Ratings,
      // the bankroll curve, etc.) with plain useEffect + fetch -- a completely
      // standard pattern. This Next 16 rule flags it as "setState in an
      // effect" regardless of whether the dependency array is correct; keep
      // it visible without letting it fail `next build`.
      "react-hooks/set-state-in-effect": "warn",
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

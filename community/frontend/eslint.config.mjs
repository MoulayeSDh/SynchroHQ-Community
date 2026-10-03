import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  ...nextVitals,
  { files: ["src/app/collect/page.tsx", "src/app/forms/page.tsx", "src/app/page.tsx"],
    rules: { "@next/next/no-html-link-for-pages": "off" } },
  globalIgnores([".next/**", "out/**", "next-env.d.ts"]),
]);

import type { NextConfig } from "next";
const nextConfig: NextConfig = { output: "standalone",
  async headers() { return [{ source: "/sw.js", headers: [
    { key: "Cache-Control", value: "no-cache" }, { key: "Service-Worker-Allowed", value: "/" },
  ] }]; },
};
export default nextConfig;

import type { NextConfig } from "next";

const apiOrigin = process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8018";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  env: { STUDIO_API_ORIGIN: apiOrigin },
};

export default config;

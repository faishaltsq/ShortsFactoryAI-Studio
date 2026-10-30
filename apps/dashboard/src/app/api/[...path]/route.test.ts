// @vitest-environment node
import { afterEach, expect, test, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

test("reads origin and server-held token at request time without forwarding browser credentials", async () => {
  const upstream = vi.fn().mockImplementation(async () => Response.json({ ok: true }));
  vi.stubGlobal("fetch", upstream);
  const request = () => new NextRequest("http://127.0.0.1:41000/api/jobs?limit=2", {
    headers: { authorization: "Bearer browser", cookie: "operator=private" },
  });
  const context = { params: Promise.resolve({ path: ["jobs"] }) };

  for (const [port, token] of [[41001, "first-private-value"], [41002, "second-private-value"]] as const) {
    vi.stubEnv("STUDIO_API_ORIGIN", `http://127.0.0.1:${port}`);
    vi.stubEnv("STUDIO_API_TOKEN", token);
    const response = await GET(request(), context);
    expect(await response.json()).toEqual({ ok: true });
    const [url, options] = upstream.mock.calls.at(-1)!;
    expect(url.toString()).toBe(`http://127.0.0.1:${port}/api/jobs?limit=2`);
    const headers = options.headers as Headers;
    expect(headers.get("authorization")).toBe(`Bearer ${token}`);
    expect(headers.has("cookie")).toBe(false);
    expect(response.headers.get("authorization")).toBeNull();
  }
});

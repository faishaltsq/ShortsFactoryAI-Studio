import { expect, type APIRequestContext } from "@playwright/test";

/** Canonical workflow membership, independent of the page/mirror under test. */
export async function workflowAgentIds(request: APIRequestContext): Promise<string[]> {
  const response = await request.get(`${process.env.STUDIO_E2E_API!}/api/agents`);
  expect(response.ok()).toBe(true);
  const body: unknown = await response.json();
  if (typeof body !== "object" || body === null || !("agents" in body) || !Array.isArray(body.agents)) {
    throw new Error("agent inventory must contain an agents array");
  }
  const ids = body.agents.map((agent: unknown) => {
    if (typeof agent !== "object" || agent === null || !("id" in agent) || typeof agent.id !== "string" || !agent.id) {
      throw new Error("agent inventory contains an invalid id");
    }
    return agent.id;
  });
  expect(new Set(ids).size).toBe(ids.length);
  expect(ids).toEqual(expect.arrayContaining(["ResearchAgent", "AudioAgent", "MotionCoderAgent"]));
  return ids.sort();
}

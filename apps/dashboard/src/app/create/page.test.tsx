import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import CreatePage from "./page";

describe("CreatePage Form Controls", () => {
  beforeEach(() => {
    vi.spyOn(api, "discoverTopics").mockResolvedValue({
      discovery_id: "disc-1",
      status: "completed",
      provider_mode: "mock",
      candidates: [],
      avoid: [],
    });
    vi.spyOn(api, "getVoices").mockResolvedValue({
      voices: [
        {
          id: "id-ID-ArdiNeural",
          name: "Microsoft Ardi",
          locale: "id-ID",
          gender: "Male",
          provider: "edge-tts",
          description: "Microsoft Ardi",
        },
      ],
    });
    vi.spyOn(api, "createJob").mockResolvedValue({
      id: "job-new-123",
      title: "Video Causal Motion",
      state: "CREATED",
      attempts: 0,
      provider_mode: "mock",
      is_mock: true,
      created_at: "2026-11-02T00:00:00Z",
      updated_at: "2026-11-02T00:00:00Z",
      last_error: null,
      priority: 5,
      scheduled_for: null,
      running: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders renderer, tts_provider, and fallback_policy selects", async () => {
    render(<CreatePage />);

    expect(screen.getByLabelText(/Renderer/i)).toBeDefined();
    expect(screen.getByLabelText(/TTS Provider|Penyedia TTS/i)).toBeDefined();
    expect(screen.getByLabelText(/Kebijakan fallback|Fallback Policy/i)).toBeDefined();
  });

  it("submits selected renderer, tts_provider, and fallback_policy in createJob payload", async () => {
    render(<CreatePage />);

    const titleInput = screen.getByLabelText(/Judul/i);
    fireEvent.change(titleInput, { target: { value: "Video Causal Motion" } });

    const rendererSelect = screen.getByLabelText(/Renderer/i);
    fireEvent.change(rendererSelect, { target: { value: "custom-motion" } });

    const ttsSelect = screen.getByLabelText(/TTS Provider|Penyedia TTS/i);
    fireEvent.change(ttsSelect, { target: { value: "voicestudio" } });

    const fallbackSelect = screen.getByLabelText(/Kebijakan fallback|Fallback Policy/i);
    fireEvent.change(fallbackSelect, { target: { value: "strict" } });

    const submitBtn = screen.getByRole("button", { name: /Buat job/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.createJob).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Video Causal Motion",
          renderer: "custom-motion",
          tts_provider: "voicestudio",
          fallback_policy: "strict",
        })
      );
    });
  });
});

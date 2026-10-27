import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { VideoSurface } from "./VideoSurface";

/**
 * The four states the job-detail video surface must be able to show.
 *
 * A bare `<video src controls>` looks identical while it is loading, after a failed range
 * request, and when the job never rendered — which is exactly the ambiguity these tests exist to
 * remove. Each test drives one real DOM event the browser would fire; none of them asserts on a
 * state the component cannot actually reach.
 */

const load = vi.fn();

beforeEach(() => {
  load.mockClear();
  // jsdom does not implement media loading. Stubbing it keeps the retry assertion honest:
  // without the stub the button would "work" by throwing into the virtual console.
  Object.defineProperty(HTMLMediaElement.prototype, "load", {
    configurable: true,
    writable: true,
    value: load,
  });
});

afterEach(cleanup);

const base = { jobId: "job-1", title: "Phase 2 proof", hasVideo: true, isMock: true };

describe("no video", () => {
  test("shows the empty state and renders no player", () => {
    render(<VideoSurface {...base} hasVideo={false} />);
    expect(screen.getByRole("region", { name: "Video hasil render" })).toBeTruthy();
    expect(screen.getByText(/Belum ada video untuk job ini/)).toBeTruthy();
    expect(document.querySelector("video")).toBeNull();
    expect(document.querySelector("[data-video-state]")?.getAttribute("data-video-state")).toBe(
      "empty",
    );
  });

  test("still carries the mock note, because the note is about the job, not the file", () => {
    render(<VideoSurface {...base} hasVideo={false} />);
    expect(screen.getByRole("note").textContent).toContain("tidak dapat dipublikasikan");
  });
});

describe("loading", () => {
  test("renders the player with controls, metadata preload, an accessible name and no autoplay", () => {
    render(<VideoSurface {...base} />);
    const video = document.querySelector("video");
    expect(video).not.toBeNull();
    const element = video as HTMLVideoElement;
    expect(element.getAttribute("src")).toBe("/api/jobs/job-1/video#t=0.1");
    expect(element.hasAttribute("controls")).toBe(true);
    expect(element.getAttribute("preload")).toBe("metadata");
    expect(element.getAttribute("aria-label")).toBe("Video job Phase 2 proof");
    // No autoplay at all, and nothing muted: the narration is the point.
    expect(element.hasAttribute("autoplay")).toBe(false);
    expect(element.muted).toBe(false);
    expect(document.querySelector("[data-video-state]")?.getAttribute("data-video-state")).toBe(
      "loading",
    );
    expect(screen.getByRole("status").textContent).toContain("Memuat metadata video");
  });
});

describe("ready", () => {
  test("loadedmetadata moves the surface to ready and drops the loading notice", () => {
    render(<VideoSurface {...base} />);
    fireEvent.loadedMetadata(document.querySelector("video") as HTMLVideoElement);
    expect(document.querySelector("[data-video-state]")?.getAttribute("data-video-state")).toBe(
      "ready",
    );
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("siap diputar")).toBeTruthy();
  });
});

describe("error", () => {
  test("a media error surfaces an alert and a retry that reloads the same element", () => {
    render(<VideoSurface {...base} />);
    const video = document.querySelector("video") as HTMLVideoElement;
    fireEvent.error(video);

    expect(document.querySelector("[data-video-state]")?.getAttribute("data-video-state")).toBe(
      "error",
    );
    expect(screen.getByRole("alert").textContent).toContain("Video gagal dimuat");
    // The player stays mounted: replacing it would discard the element `load()` must re-run on.
    expect(document.querySelector("video")).toBe(video);

    fireEvent.click(screen.getByRole("button", { name: "Muat ulang video" }));
    expect(load).toHaveBeenCalledTimes(1);
    expect(document.querySelector("[data-video-state]")?.getAttribute("data-video-state")).toBe(
      "loading",
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("a missing media source is reported without inventing a reason", () => {
    render(<VideoSurface {...base} />);
    // jsdom leaves `error` null, which is the case where the browser gave us no code.
    fireEvent.error(document.querySelector("video") as HTMLVideoElement);
    expect(screen.getByRole("alert").textContent).toContain("sumber video tidak dapat dibaca");
  });
});

describe("mock note", () => {
  test("is visible for a mock job", () => {
    render(<VideoSurface {...base} isMock />);
    expect(screen.getByRole("note").textContent).toContain(
      "Job mock: video ini bukti lokal dan tidak dapat dipublikasikan.",
    );
  });

  test("is absent for a live job", () => {
    render(<VideoSurface {...base} isMock={false} />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});

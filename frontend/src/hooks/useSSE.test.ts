import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSSE } from "./useSSE";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emitOpen() {
    this.onopen?.();
  }

  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  emitError() {
    this.onerror?.();
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSSE", () => {
  it("does not open a connection while url is null", () => {
    const { result } = renderHook(() => useSSE<{ x: number }>(null));
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.data).toBeNull();
    expect(result.current.connected).toBe(false);
  });

  it("opens a connection, tracks connected state, and parses incoming events", () => {
    const { result } = renderHook(() => useSSE<{ x: number }>("/api/fake/stream"));
    expect(FakeEventSource.instances).toHaveLength(1);
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/api/fake/stream");

    act(() => source.emitOpen());
    expect(result.current.connected).toBe(true);

    act(() => source.emitMessage({ x: 42 }));
    expect(result.current.data).toEqual({ x: 42 });
  });

  it("keeps the last valid snapshot when a malformed event arrives", () => {
    const { result } = renderHook(() => useSSE<{ x: number }>("/api/fake/stream"));
    const source = FakeEventSource.instances[0];

    act(() => source.emitMessage({ x: 1 }));
    expect(result.current.data).toEqual({ x: 1 });

    act(() => source.onmessage?.({ data: "{ nao e json valido" }));
    expect(result.current.data).toEqual({ x: 1 }); // nao quebrou, manteve o ultimo valido
  });

  it("reflects connected=false on error", () => {
    const { result } = renderHook(() => useSSE<{ x: number }>("/api/fake/stream"));
    const source = FakeEventSource.instances[0];
    act(() => source.emitOpen());
    expect(result.current.connected).toBe(true);

    act(() => source.emitError());
    expect(result.current.connected).toBe(false);
  });

  it("closes the previous connection when the url changes, and opens a new one", () => {
    const { rerender } = renderHook(({ url }: { url: string | null }) => useSSE(url), {
      initialProps: { url: "/a" },
    });
    expect(FakeEventSource.instances).toHaveLength(1);
    const first = FakeEventSource.instances[0];

    rerender({ url: "/b" });

    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toBe("/b");
  });

  it("closes the connection on unmount", () => {
    const { unmount } = renderHook(() => useSSE("/api/fake/stream"));
    const source = FakeEventSource.instances[0];
    unmount();
    expect(source.closed).toBe(true);
  });
});

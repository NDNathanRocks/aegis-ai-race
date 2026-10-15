import { describe, expect, it } from "vitest";
import { SSEParser, toRaceEvent } from "@/lib/sse";

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe("SSEParser", () => {
  it("parses complete frames", () => {
    const p = new SSEParser();
    const frames = p.push(frame("meta", { a: 1 }) + frame("done", { b: 2 }));
    expect(frames.map((f) => f.event)).toEqual(["meta", "done"]);
    expect(JSON.parse(frames[1]?.data ?? "")).toEqual({ b: 2 });
  });

  it("reassembles frames split across arbitrary chunk boundaries", () => {
    const whole = frame("token", { text: "héllo wörld" }) + frame("done", { ok: true });
    for (let cut = 1; cut < whole.length; cut += 7) {
      const p = new SSEParser();
      const out = [...p.push(whole.slice(0, cut)), ...p.push(whole.slice(cut))];
      expect(out.map((f) => f.event)).toEqual(["token", "done"]);
    }
  });

  it("ignores heartbeat comments and handles CRLF", () => {
    const p = new SSEParser();
    const out = p.push(": ping\n\nevent: meta\r\ndata: {\"x\":1}\r\n\r\n");
    expect(out).toHaveLength(1);
    expect(out[0]?.event).toBe("meta");
  });

  it("joins multi-line data and keeps partial frames buffered", () => {
    const p = new SSEParser();
    expect(p.push("event: card\ndata: line1\ndata: line2")).toEqual([]);
    expect(p.push("\n\n")).toEqual([{ event: "card", data: "line1\nline2" }]);
  });
});

describe("toRaceEvent", () => {
  it("accepts known events and rejects unknown names or bad JSON", () => {
    expect(toRaceEvent({ event: "done", data: '{"total_ms":1}' })?.event).toBe("done");
    expect(toRaceEvent({ event: "mystery", data: "{}" })).toBeNull();
    expect(toRaceEvent({ event: "done", data: "{not json" })).toBeNull();
  });
});

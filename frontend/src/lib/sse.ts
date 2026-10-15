import { EVENT_NAMES, type RaceEvent, type RaceRequest, type Side } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface RawFrame {
  event: string;
  data: string;
}

/**
 * Incremental SSE frame parser. Feed it decoded text chunks as they arrive; it returns the frames that
 * completed in that chunk and keeps the partial remainder. Handles CRLF, multi-line data, comments
 * (heartbeats) and frames split across chunk boundaries.
 */
export class SSEParser {
  private buffer = "";

  push(chunk: string): RawFrame[] {
    this.buffer += chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const frames: RawFrame[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      const frame = parseBlock(block);
      if (frame) frames.push(frame);
    }
    return frames;
  }
}

function parseBlock(block: string): RawFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue; // comment / heartbeat
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

/** Turn a raw frame into a typed event, or null for unknown events / malformed JSON. */
export function toRaceEvent(frame: RawFrame): RaceEvent | null {
  if (!EVENT_NAMES.has(frame.event)) return null;
  try {
    return { event: frame.event, data: JSON.parse(frame.data) } as RaceEvent;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfterS?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** POST a race request and invoke `onEvent` for every SSE event as it arrives. Resolves when the stream ends. */
export async function streamRace(
  side: Side,
  body: RaceRequest,
  onEvent: (e: RaceEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/api/race/${side}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
      cache: "no-store",
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(`Cannot reach the backend at ${API_URL}. Is it running?`, 0);
  }
  if (!resp.ok) {
    const retry = Number(resp.headers.get("Retry-After") ?? "") || undefined;
    throw new ApiError(
      resp.status === 429 ? "Rate limit reached: please wait a moment and try again." : `Backend returned HTTP ${resp.status}`,
      resp.status,
      retry,
    );
  }
  if (!resp.body) throw new ApiError("Streaming is not supported by this browser.", 0);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        const evt = toRaceEvent(frame);
        if (evt) onEvent(evt);
      }
    }
    for (const frame of parser.push(decoder.decode() + "\n\n")) {
      const evt = toRaceEvent(frame);
      if (evt) onEvent(evt);
    }
  } finally {
    reader.releaseLock();
  }
}

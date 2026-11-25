// Live run events over the API's server-sent-events endpoint.
//
// The browser's EventSource cannot send an Authorization header, so the
// stream is read with fetch and parsed here.

import { buildUrl, loadConnection } from "./api.ts";

export interface SseMessage {
  event: string;
  data: string;
}

/** Incremental parser for a text/event-stream body. */
export class SseParser {
  private buffer = "";

  /** Feed decoded text; returns the messages completed by it. */
  push(text: string): SseMessage[] {
    this.buffer += text;
    const messages: SseMessage[] = [];
    for (;;) {
      const match = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer);
      if (!match) break;
      const block = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split(/\r\n|\n|\r/)) {
        if (line === "" || line.startsWith(":")) continue; // comment / keep-alive
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let value = colon === -1 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length > 0) messages.push({ event, data: data.join("\n") });
    }
    return messages;
  }
}

/** A run event as the API sends it (`RunEvent`). */
export interface RunEvent {
  run_id: string;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

/** Text the model is producing right now, before the step is recorded. */
export interface LiveOutput {
  step: number | null;
  text: string;
}

export const EMPTY_LIVE: LiveOutput = { step: null, text: "" };

/** Most text kept for display; older text is dropped from the front. */
export const LIVE_TEXT_LIMIT = 20_000;

/**
 * Fold one event into the live output.
 *
 * Deltas are a preview only: once the step is recorded (`step.finished`) the
 * trace shows the stored text, so the preview is cleared. A retry discards
 * the failed attempt's partial text.
 */
export function reduceLive(state: LiveOutput, event: RunEvent): LiveOutput {
  switch (event.type) {
    case "llm.delta": {
      const step = typeof event.data.step === "number" ? event.data.step : null;
      const chunk = typeof event.data.text === "string" ? event.data.text : "";
      const text = (step === state.step ? state.text : "") + chunk;
      return { step, text: text.length > LIVE_TEXT_LIMIT ? text.slice(-LIVE_TEXT_LIMIT) : text };
    }
    case "llm.retry":
    case "step.finished":
    case "run.finished":
      return state.text === "" && state.step === null ? state : EMPTY_LIVE;
    default:
      return state;
  }
}

/** Events after which the stored run record has changed. */
const RECORD_CHANGED = new Set([
  "plan.created",
  "step.finished",
  "tool.awaiting_approval",
  "tool.approved",
  "tool.denied",
  "evaluation.finished",
  "run.finished",
]);

export function changesRecord(event: RunEvent): boolean {
  return RECORD_CHANGED.has(event.type);
}

/**
 * Read a run's event stream until it ends or `signal` aborts.
 *
 * Resolves when the server closes the stream (the run finished); rejects if
 * the stream cannot be opened or breaks. Callers keep polling as a fallback.
 */
export async function streamRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const { baseUrl, apiKey } = loadConnection();
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const response = await fetch(buildUrl(baseUrl, `/runs/${encodeURIComponent(runId)}/events`), {
    headers,
    cache: "no-store",
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`event stream failed with status ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    for (const message of parser.push(decoder.decode(value, { stream: true }))) {
      if (message.event === "snapshot") continue;
      let event: RunEvent;
      try {
        event = JSON.parse(message.data) as RunEvent;
      } catch {
        continue; // a malformed message must not end the stream
      }
      if (event && typeof event.type === "string" && event.data && typeof event.data === "object") {
        onEvent(event);
      }
    }
  }
}

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  changesRecord,
  EMPTY_LIVE,
  LIVE_TEXT_LIMIT,
  reduceLive,
  type RunEvent,
  SseParser,
  streamRunEvents,
} from "./live.ts";

function ev(type: string, data: Record<string, unknown> = {}): RunEvent {
  return { run_id: "run_1", type, timestamp: "2026-01-01T00:00:00Z", data };
}

test("SseParser yields complete messages and keeps partial ones", () => {
  const parser = new SseParser();
  assert.deepEqual(parser.push('event: llm.delta\ndata: {"a"'), []);
  assert.deepEqual(parser.push(":1}\n\nevent: step.finished\ndata: {}\n"), [
    { event: "llm.delta", data: '{"a":1}' },
  ]);
  assert.deepEqual(parser.push("\n"), [{ event: "step.finished", data: "{}" }]);
});

test("SseParser skips keep-alive comments and handles CRLF and multi-line data", () => {
  const parser = new SseParser();
  assert.deepEqual(parser.push(": keep-alive\n\n"), []);
  assert.deepEqual(parser.push("event: x\r\ndata: one\r\ndata: two\r\n\r\n"), [
    { event: "x", data: "one\ntwo" },
  ]);
  assert.deepEqual(parser.push("data:no-space\n\n"), [{ event: "message", data: "no-space" }]);
});

test("reduceLive appends deltas of the same step", () => {
  let state = EMPTY_LIVE;
  state = reduceLive(state, ev("llm.delta", { step: 2, text: "Hel" }));
  state = reduceLive(state, ev("llm.delta", { step: 2, text: "lo" }));
  assert.deepEqual(state, { step: 2, text: "Hello" });
  // other events leave the preview alone (tools run before step.finished)
  assert.equal(reduceLive(state, ev("llm.finished", { step: 2 })), state);
});

test("reduceLive starts over for a new step, a retry and a recorded step", () => {
  const shown = reduceLive(EMPTY_LIVE, ev("llm.delta", { step: 0, text: "partial" }));
  assert.deepEqual(reduceLive(shown, ev("llm.delta", { step: 1, text: "next" })), {
    step: 1,
    text: "next",
  });
  assert.deepEqual(reduceLive(shown, ev("llm.retry", { step: 0 })), EMPTY_LIVE);
  assert.deepEqual(reduceLive(shown, ev("step.finished", { step: 0 })), EMPTY_LIVE);
  assert.deepEqual(reduceLive(shown, ev("run.finished")), EMPTY_LIVE);
});

test("reduceLive bounds the preview and ignores malformed deltas", () => {
  let state = reduceLive(EMPTY_LIVE, ev("llm.delta", { step: 0, text: "a".repeat(LIVE_TEXT_LIMIT) }));
  state = reduceLive(state, ev("llm.delta", { step: 0, text: "END" }));
  assert.equal(state.text.length, LIVE_TEXT_LIMIT);
  assert.ok(state.text.endsWith("END"));
  assert.deepEqual(reduceLive(EMPTY_LIVE, ev("llm.delta", { step: 0, text: 42 })), {
    step: 0,
    text: "",
  });
});

test("changesRecord marks the events that update the stored run", () => {
  assert.equal(changesRecord(ev("step.finished")), true);
  assert.equal(changesRecord(ev("run.finished")), true);
  assert.equal(changesRecord(ev("tool.awaiting_approval")), true);
  assert.equal(changesRecord(ev("llm.delta")), false);
  assert.equal(changesRecord(ev("llm.finished")), false);
});

function sseResponse(parts: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

test("streamRunEvents delivers events split across network chunks", async () => {
  const delta = JSON.stringify(ev("llm.delta", { step: 0, text: "héllo" }));
  const finished = JSON.stringify(ev("run.finished"));
  const wire =
    'event: snapshot\ndata: {"status":"running","steps":0}\n\n' +
    `event: llm.delta\ndata: ${delta}\n\n` +
    ": keep-alive\n\n" +
    "event: broken\ndata: {not json\n\n" +
    `event: run.finished\ndata: ${finished}\n\n`;
  const cut = wire.indexOf("héllo") + 2; // inside an event (and next to a multi-byte character)
  const calls: { url: string; headers: Record<string, string> }[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: { headers: Record<string, string> }) => {
    calls.push({ url, headers: init.headers });
    return sseResponse([wire.slice(0, cut), wire.slice(cut)]);
  }) as unknown as typeof fetch;
  try {
    const seen: RunEvent[] = [];
    await streamRunEvents("run 1", (e) => seen.push(e), new AbortController().signal);
    assert.deepEqual(
      seen.map((e) => e.type),
      ["llm.delta", "run.finished"],
    );
    assert.equal(seen[0]?.data.text, "héllo");
    assert.equal(calls[0]?.url, "http://localhost:8000/api/v1/runs/run%201/events");
    assert.equal(calls[0]?.headers.Accept, "text/event-stream");
  } finally {
    globalThis.fetch = original;
  }
});

test("streamRunEvents rejects when the stream cannot be opened", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => sseResponse([], 401)) as unknown as typeof fetch;
  try {
    await assert.rejects(
      streamRunEvents("run_1", () => {}, new AbortController().signal),
      /status 401/,
    );
  } finally {
    globalThis.fetch = original;
  }
});

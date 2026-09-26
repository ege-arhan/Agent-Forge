import assert from "node:assert/strict";
import { test } from "node:test";

import { buildUrl, errorMessage } from "./api.ts";

test("buildUrl joins base, prefix and query", () => {
  assert.equal(buildUrl("http://localhost:8000", "/runs"), "http://localhost:8000/api/v1/runs");
  assert.equal(
    buildUrl("http://h:1/", "/runs", { status: "failed", limit: 5, empty: "", none: undefined }),
    "http://h:1/api/v1/runs?status=failed&limit=5",
  );
  assert.equal(
    buildUrl("http://h", "/x", { labels: ["a", "b"] }),
    "http://h/api/v1/x?labels=a&labels=b",
  );
});

test("errorMessage understands FastAPI error shapes", () => {
  assert.equal(errorMessage({ detail: "agent not found" }, 404), "agent not found");
  assert.equal(
    errorMessage({ detail: [{ loc: ["body", "goal"], msg: "Field required" }] }, 422),
    "goal: Field required",
  );
  assert.equal(errorMessage(null, 500), "request failed with status 500");
});

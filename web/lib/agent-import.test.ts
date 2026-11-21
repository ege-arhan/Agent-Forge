import assert from "node:assert/strict";
import { test } from "node:test";

import { draftFormat, importProblem, MAX_IMPORT_BYTES, readDraft } from "./agent-import.ts";

test("empty and whitespace-only text is empty", () => {
  assert.deepEqual(readDraft(""), { kind: "empty" });
  assert.deepEqual(readDraft("  \n\t"), { kind: "empty" });
  assert.equal(draftFormat(" "), "");
});

test("a JSON object is parsed in the browser", () => {
  const draft = readDraft('  {"name": "a", "tools": ["filesystem"]}\n');
  assert.equal(draft.kind, "json");
  if (draft.kind === "json") assert.equal(draft.config.name, "a");
  assert.equal(draftFormat('{"name": "a"}'), "JSON");
});

test("broken JSON is reported as JSON, not sent as YAML", () => {
  const draft = readDraft('{"name": "a",}');
  assert.equal(draft.kind, "json-error");
  if (draft.kind === "json-error") assert.match(draft.message, /not valid JSON/);
  assert.equal(draftFormat('{"name": '), "JSON");
});

test("YAML is passed on untouched, comments and indentation included", () => {
  const text = "# demo\nname: a\nmodel:\n  provider: scripted\n";
  assert.deepEqual(readDraft(text), { kind: "yaml", content: text });
  assert.equal(draftFormat(text), "YAML");
});

test("text that is neither is left for the server to judge", () => {
  assert.equal(readDraft("[1, 2]").kind, "yaml");
  assert.equal(readDraft("just words").kind, "yaml");
});

test("import accepts YAML and JSON files by extension, any case", () => {
  for (const name of ["agent.yaml", "agent.yml", "agent.json", "AGENT.YAML"]) {
    assert.equal(importProblem({ name, size: 10 }), undefined);
  }
});

test("import refuses other types, empty files and oversized files", () => {
  assert.match(importProblem({ name: "agent.txt", size: 10 }) ?? "", /\.yaml, \.yml or \.json/);
  assert.match(importProblem({ name: "yaml", size: 10 }) ?? "", /choose/);
  assert.match(importProblem({ name: "a.yaml", size: 0 }) ?? "", /empty/);
  assert.match(importProblem({ name: "a.yaml", size: MAX_IMPORT_BYTES + 1 }) ?? "", /larger than 512 KB/);
  assert.equal(importProblem({ name: "a.yaml", size: MAX_IMPORT_BYTES }), undefined);
});

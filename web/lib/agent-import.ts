// Helpers for the agent form: deciding how a pasted or imported configuration
// is read. JSON is parsed in the browser; anything else is sent to the API,
// which reads YAML with the same parser the CLI uses.

import type { AgentConfig } from "./types.ts";

/** Largest file the form reads; the API's default request limit is 1 MB. */
export const MAX_IMPORT_BYTES = 512 * 1024;

const EXTENSIONS = [".yaml", ".yml", ".json"];

export type Draft =
  | { kind: "empty" }
  | { kind: "json"; config: AgentConfig }
  | { kind: "json-error"; message: string }
  | { kind: "yaml"; content: string };

/**
 * Classify the text of the form. Text that starts with `{` is JSON and is
 * reported as broken JSON when it does not parse, so a typo in a JSON draft
 * gets a JSON error instead of a confusing YAML one. Everything else is YAML.
 */
export function readDraft(text: string): Draft {
  const trimmed = text.trim();
  if (!trimmed) return { kind: "empty" };
  if (!trimmed.startsWith("{")) return { kind: "yaml", content: text };
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { kind: "json-error", message: "The configuration must be a JSON object." };
    }
    return { kind: "json", config: parsed as AgentConfig };
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    return { kind: "json-error", message: `The configuration is not valid JSON: ${reason}` };
  }
}

/** Why a chosen file cannot be imported, or `undefined` when it can. */
export function importProblem(file: { name: string; size: number }): string | undefined {
  const name = file.name.toLowerCase();
  if (!EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `${file.name}: choose a .yaml, .yml or .json file.`;
  }
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > MAX_IMPORT_BYTES) {
    return `${file.name} is larger than ${MAX_IMPORT_BYTES / 1024} KB.`;
  }
  return undefined;
}

/** The label shown next to the editor for the current text. */
export function draftFormat(text: string): "JSON" | "YAML" | "" {
  const draft = readDraft(text);
  if (draft.kind === "empty") return "";
  return draft.kind === "yaml" ? "YAML" : "JSON";
}

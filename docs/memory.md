# Memory

An agent has two kinds of memory.

- **Short-term**: the conversation of the current run. Beyond
  `memory.keep_recent_messages` (default 40), large old tool outputs are
  replaced with a short placeholder so long runs stay within the context
  window.
- **Persistent**: notes stored per agent in the database (`memories` table).
  They come from two places: with `memory.persist: true` the runtime stores a
  summary of every finished run (goal, outcome, result, error), and an agent
  with the `memory` toolset can call `remember` itself. At the start of a run,
  up to `memory.recall_limit` memories relevant to the goal are put into the
  system prompt; the agent can also call `recall` with its own query.

Everything stored passes through the redactor first.

## Search modes

`memory.search` chooses how "relevant" is decided, per agent:

| Mode | Ranking | Needs |
|---|---|---|
| `lexical` (default) | BM25-style score over the words of the note and its tags | nothing |
| `vector` | cosine similarity between the embedding of the query and of each note | an embedder on the server |
| `hybrid` | both rankings combined by reciprocal rank fusion (a note scores `1 / (60 + rank)` in each ranking it appears in) | an embedder on the server |

```yaml
memory:
  persist: true
  recall_limit: 5
  search: hybrid          # lexical | vector | hybrid
  min_similarity: 0.2     # vector ranking: ignore notes at or below this cosine similarity
```

Lexical search only finds notes that share a whole word with the query:
"configuring databases" does not find "Database configuration lives in
settings.py". Vector search can, depending on the embedder (below).

`min_similarity` (default `0.0`, range −1 to 1) applies to the vector ranking
only. Without it, vector search returns the `recall_limit` nearest notes
however far away they are, because every note has *some* similarity to every
query. The useful value depends on the embedding model, and the default has
not been calibrated against one: look at the scores `agentforge memory search`
prints for your own notes and set it from those. In `hybrid` mode a note that
matches lexically is kept even when it is below the threshold.

The score reported with a memory means something different in each mode (a
BM25 score, a cosine similarity, a fusion score); scores from different modes
cannot be compared.

Because the mode is part of the agent configuration, it can be compared like
any other setting: as an [experiment](benchmarks.md) variant
(`overrides: {memory: {search: hybrid}}`) or as a manual
[improvement proposal](improvement.md) (`memory.search` and
`memory.min_similarity` are on the allowlist).

## Embedders

The embedder is a **server setting**, chosen by the operator. An agent
configuration cannot name an embedding endpoint or credential, so a config
submitted through the API cannot send memories or a key anywhere.

| `AGENTFORGE_MEMORY_EMBEDDER` | What it is |
|---|---|
| `none` (default) | No embedder. `vector` and `hybrid` fall back to lexical search (one warning in the log). |
| `hashing` | Built in, offline, deterministic. Hashes each word (stopwords dropped) and its character trigrams into `AGENTFORGE_EMBEDDING_DIMENSIONS` buckets (default 256, 64–4096). |
| `openai-compatible` | Calls `POST {base_url}/embeddings` on an OpenAI-compatible server (OpenAI, OpenRouter, Ollama, vLLM, LM Studio, …). |

Settings for `openai-compatible`:

| Variable | Default | Meaning |
|---|---|---|
| `AGENTFORGE_EMBEDDING_MODEL` | — (required) | Model name sent in the request |
| `AGENTFORGE_EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | Base URL; `/embeddings` is appended |
| `AGENTFORGE_EMBEDDING_API_KEY_ENV` | `OPENAI_API_KEY` | Variable holding the key; set it to an empty value for a keyless local server |

```bash
# offline
AGENTFORGE_MEMORY_EMBEDDER=hashing uv run agentforge serve

# a local model through Ollama
AGENTFORGE_MEMORY_EMBEDDER=openai-compatible \
AGENTFORGE_EMBEDDING_MODEL=nomic-embed-text \
AGENTFORGE_EMBEDDING_BASE_URL=http://localhost:11434/v1 \
AGENTFORGE_EMBEDDING_API_KEY_ENV= \
  uv run agentforge serve
```

A misconfigured embedder (no model, missing key) stops the server or the CLI
command at start-up with a message, rather than silently searching lexically.

### What the hashing embedder is and is not

It is **not a semantic model**. It matches on word forms: "configuring
databases" is close to "database configuration" because the words share
trigrams, but "car" and "automobile" are as unrelated to it as any two words.
It exists so vector search works with no model, no network and no cost (tests,
demos, air-gapped use), and it is somewhat more forgiving than lexical search
about inflections and typos. For recall by meaning, use an embedding model.

### Status of the `openai-compatible` embedder

It is tested against a mocked HTTP transport only. **No session has run it
against a live embeddings endpoint**, so behaviour with a real server (limits,
error bodies, latency) is unverified.

With a remote embedder, the text of every memory in the searched namespace and
every query (run goals, `recall` queries) is sent to that endpoint. They are
redacted like everything else that is stored, but they do leave the server.

## How vectors are stored and searched

- Vectors live in the `memory_embeddings` table (migration `0004`), one row
  per memory and embedder, as little-endian float32.
- A memory is embedded the first time a vector search looks at it, not when
  it is written. So memories written before an embedder was configured are
  searchable without a backfill step, and writing a memory never depends on
  the embedding endpoint. The first vector search of an agent with many
  memories embeds them all (in batches of 64); later searches embed only the
  query and any new memories.
- Vectors are kept per embedder name (`hashing-v1:256`,
  `openai-compatible:<model>@<host/path>`). Changing the model, the endpoint
  or the dimensions makes the old vectors unused, not wrong: they are never
  compared with the new ones. (The endpoint is part of the name because two
  servers can serve different models under one model name; the cost is that
  moving the same model to another host embeds the memories again.)
  Old rows are not cleaned up automatically; they go when the memory is
  deleted.
- Search is **brute force**: the 1 000 most recent memories of the agent are
  scored in Python. There is no approximate-nearest-neighbour index and no
  pgvector. That is adequate for per-agent memories of this size, and not a
  design for millions of vectors. Memories older than the most recent 1 000
  are not searched in any mode (this was already true of lexical search).
- If the embedder fails during a search (network error, bad response), the
  search logs a warning and returns the lexical ranking; the run continues.

## CLI

```bash
agentforge memory add    AGENT "Database configuration lives in settings.py" --tag config
agentforge memory list   AGENT [--limit 20] [--json]
agentforge memory search AGENT "configuring databases" [--mode vector] [--min-similarity 0.2] [--json]
```

`AGENT` is a stored agent's name. `search` uses the agent's own `memory.search`
and `memory.min_similarity` unless overridden, and prints the mode, the
embedder and each hit's score:

```text
$ export AGENTFORGE_MEMORY_EMBEDDER=hashing
$ agentforge memory search scripted-demo "configuring databases" --mode vector
mode: vector  embedder: hashing-v1:256
  0.5486  mem_01a20732ed695ab64f8868b9  2026-11-23T06:58:27  Database configuration lives in settings.py  [config]
  0.0317  mem_01a20732f025d90fc8749675  2026-11-23T06:58:28  The weather service caches forecasts for an hour
$ agentforge memory search scripted-demo "configuring databases" --mode vector --min-similarity 0.15
mode: vector  embedder: hashing-v1:256
  0.5486  mem_01a20732ed695ab64f8868b9  2026-11-23T06:58:27  Database configuration lives in settings.py  [config]
$ agentforge memory search scripted-demo "configuring databases" --mode lexical
mode: lexical  embedder: -
no memories
```

(A real transcript with the hashing embedder, OFFLINE. The second hit of the
first command is the reason `min_similarity` exists: an unrelated note still
has a small similarity. The scores show how the command behaves, not how an
embedding model ranks.)

Asking for `--mode vector` or `hybrid` without an embedder is an error (exit
code 2) rather than a silent lexical search.

There is no HTTP endpoint or dashboard page for browsing memories yet.

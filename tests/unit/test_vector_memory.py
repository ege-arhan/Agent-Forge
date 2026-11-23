"""Vector and hybrid memory search (embedders, ranking, fallbacks)."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from agentforge.core.config import AgentConfig, MemoryConfig, MemorySearchMode
from agentforge.core.errors import ConfigurationError
from agentforge.llm.base import LLMProvider
from agentforge.llm.embeddings import BATCH_SIZE, MAX_TEXT_CHARS, HttpEmbedder
from agentforge.llm.types import CompletionRequest, CompletionResponse, Message, StopReason
from agentforge.memory.base import (
    InMemoryMemoryStore,
    MemoryRecord,
    MemoryScope,
    ScoredMemory,
    reciprocal_rank_fusion,
    vector_rank,
)
from agentforge.memory.embeddings import (
    Embedder,
    EmbeddingError,
    HashingEmbedder,
    build_embedder,
    cosine,
    pack_vector,
    unpack_vector,
)
from agentforge.runtime.factory import prepare_run
from agentforge.settings import Settings
from agentforge.tools.base import ToolContext
from agentforge.tools.builtin.memory import Recall, RecallInput
from tests.conftest import scripted_config

AGENT = MemoryScope.AGENT


def rec(content: str, ns: str = "a", tags: list[str] | None = None) -> MemoryRecord:
    return MemoryRecord(scope=AGENT, namespace=ns, content=content, tags=tags or [])


class CountingEmbedder(Embedder):
    """Hashing vectors, recording every text it is asked to embed."""

    def __init__(self, name: str = "counting", dimensions: int = 64) -> None:
        self.name = name
        self.inner = HashingEmbedder(dimensions)
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return await self.inner.embed(texts)


class FailingEmbedder(Embedder):
    name = "failing"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("endpoint unreachable")


class TableEmbedder(Embedder):
    """Vectors looked up from a table: stands in for a model that knows meaning."""

    name = "table"

    def __init__(self, table: dict[str, list[float]]) -> None:
        self.table = table

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.table[text] for text in texts]


# ------------------------------------------------------------------ embedders
async def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(128)
    first, second = await embedder.embed(["Deploy with make deploy", "Deploy with make deploy"])
    assert first == second
    assert len(first) == 128
    assert math.isclose(math.sqrt(sum(x * x for x in first)), 1.0, rel_tol=1e-9)
    assert embedder.name == "hashing-v1:128"
    # Python's per-process hash randomisation must not leak in: fixed buckets.
    # (Changing the feature scheme changes these buckets: bump HashingEmbedder.SCHEME.)
    buckets = [i for i, x in enumerate(HashingEmbedder(256).embed_one("abc")) if x]
    assert buckets == [7, 133, 160, 197]
    assert embedder.embed_one("") == [0.0] * 128
    assert embedder.embed_one("?!…") == [0.0] * 128


def test_hashing_embedder_matches_word_forms_not_meaning() -> None:
    embedder = HashingEmbedder(256)
    query = embedder.embed_one("configuring the database")
    related = cosine(query, embedder.embed_one("database configuration lives in settings.py"))
    unrelated = cosine(query, embedder.embed_one("the weather in Lisbon is sunny"))
    assert related > 0.4 and abs(unrelated) < 0.15
    # No shared word forms: a hashing embedder cannot see that these mean the same.
    synonyms = cosine(embedder.embed_one("automobile"), embedder.embed_one("car"))
    assert abs(synonyms) < 0.15


@pytest.mark.parametrize("dimensions", [0, 63, 4097])
def test_hashing_embedder_rejects_bad_dimensions(dimensions: int) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        HashingEmbedder(dimensions)


def test_cosine_edge_cases() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine([1.0], [1.0, 0.0]) == 0.0
    assert cosine([], []) == 0.0


def test_vector_blob_round_trip() -> None:
    vector = [0.5, -0.25, 0.0, 1.0]
    assert unpack_vector(pack_vector(vector)) == vector  # exactly representable in float32
    assert len(pack_vector(HashingEmbedder(64).embed_one("x y z"))) == 64 * 4
    with pytest.raises(ValueError, match="multiple of 4"):
        unpack_vector(b"\x00\x00\x00")


# -------------------------------------------------------------------- ranking
def test_vector_rank_orders_and_applies_threshold() -> None:
    a, b, c = rec("a"), rec("b"), rec("c")
    candidates = [(a, [1.0, 0.0]), (b, [0.6, 0.8]), (c, [-1.0, 0.0])]
    ranked = vector_rank([1.0, 0.0], candidates, 10)
    assert [hit.record.id for hit in ranked] == [a.id, b.id]  # c is not above 0.0
    assert ranked[0].score == pytest.approx(1.0) and ranked[1].score == pytest.approx(0.6)
    assert [h.record.id for h in vector_rank([1.0, 0.0], candidates, 10, min_similarity=0.6)] == [
        a.id
    ]
    assert len(vector_rank([1.0, 0.0], candidates, 10, min_similarity=-1.0)) == 2  # -1 is not > -1
    assert len(vector_rank([1.0, 0.0], candidates, 1)) == 1


def test_reciprocal_rank_fusion_prefers_records_in_both_rankings() -> None:
    a, b, c = rec("a"), rec("b"), rec("c")

    def ranking(*records: MemoryRecord) -> list[ScoredMemory]:
        return [ScoredMemory(record=r, score=1.0) for r in records]

    fused = reciprocal_rank_fusion([ranking(a, b), ranking(b, c)], 10)
    assert [hit.record.id for hit in fused] == [b.id, a.id, c.id]
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 62, abs=1e-6)
    assert len(reciprocal_rank_fusion([ranking(a, b), ranking(b, c)], 2)) == 2
    assert reciprocal_rank_fusion([[], []], 5) == []


# ---------------------------------------------------------------------- store
async def test_lexical_stays_the_default_and_never_embeds() -> None:
    embedder = CountingEmbedder()
    store = InMemoryMemoryStore(embedder)
    await store.add(rec("use make test to run the suite"))
    hits = await store.search(AGENT, "a", "make test")
    assert len(hits) == 1 and embedder.calls == []


async def test_vector_search_finds_what_lexical_search_misses() -> None:
    store = InMemoryMemoryStore(HashingEmbedder(256))
    target = await store.add(rec("Database configuration lives in settings.py"))
    await store.add(rec("The weather service caches forecasts for an hour"))
    query = "configuring databases"  # shares no whole word with the target
    assert await store.search(AGENT, "a", query) == []
    hits = await store.search(AGENT, "a", query, mode="vector", min_similarity=0.15)
    assert [hit.record.id for hit in hits] == [target.id]
    assert 0.15 < hits[0].score <= 1.0


async def test_vector_search_uses_meaning_when_the_embedder_has_it() -> None:
    table = {
        "car": [1.0, 0.0],
        "The automobile needs new tyres": [0.9, 0.1],
        "Bananas are yellow": [0.0, 1.0],
    }
    store = InMemoryMemoryStore(TableEmbedder(table))
    target = await store.add(rec("The automobile needs new tyres"))
    await store.add(rec("Bananas are yellow"))
    hits = await store.search(AGENT, "a", "car", mode=MemorySearchMode.VECTOR, min_similarity=0.5)
    assert [hit.record.id for hit in hits] == [target.id]


async def test_tags_are_part_of_the_embedded_text() -> None:
    embedder = CountingEmbedder()
    store = InMemoryMemoryStore(embedder)
    await store.add(rec("run the linter first", tags=["ci", "ruff"]))
    await store.search(AGENT, "a", "q", mode="vector")
    assert embedder.calls == [["q"], ["run the linter first ci ruff"]]


async def test_vectors_are_cached_and_backfilled_per_embedder() -> None:
    embedder = CountingEmbedder("first")
    store = InMemoryMemoryStore(embedder)
    await store.add(rec("alpha note"))
    await store.add(rec("beta note"))
    await store.search(AGENT, "a", "alpha", mode="vector")
    assert [len(call) for call in embedder.calls] == [1, 2]  # the query, then both records
    await store.search(AGENT, "a", "beta", mode="vector")
    assert [len(call) for call in embedder.calls] == [1, 2, 1]  # only the query
    await store.add(rec("gamma note"))
    await store.search(AGENT, "a", "gamma", mode="vector")
    assert embedder.calls[-1] == ["gamma note"]  # only the new record

    # Another embedder is another vector space: nothing is reused.
    other = CountingEmbedder("second", dimensions=128)
    store.embedder = other
    hits = await store.search(AGENT, "a", "gamma note", mode="vector")
    assert [len(call) for call in other.calls] == [1, 3]
    assert hits[0].record.content == "gamma note"


async def test_stored_vector_of_another_length_is_embedded_again() -> None:
    embedder = CountingEmbedder("same-name", dimensions=64)
    store = InMemoryMemoryStore(embedder)
    record = await store.add(rec("alpha note"))
    await store.search(AGENT, "a", "alpha", mode="vector")
    embedder.inner = HashingEmbedder(128)  # same name, new size (a misconfigured model swap)
    hits = await store.search(AGENT, "a", "alpha note", mode="vector")
    assert hits and hits[0].score == pytest.approx(1.0)
    assert len(store._vectors[record.id, "same-name"]) == 128


async def test_delete_removes_the_vector() -> None:
    store = InMemoryMemoryStore(HashingEmbedder(128))
    record = await store.add(rec("alpha note"))
    await store.search(AGENT, "a", "alpha", mode="vector")
    assert store._vectors
    assert await store.delete(record.id)
    assert store._vectors == {}
    assert await store.search(AGENT, "a", "alpha", mode="vector") == []


async def test_hybrid_fuses_both_rankings() -> None:
    store = InMemoryMemoryStore(HashingEmbedder(256))
    both = await store.add(rec("database configuration is read from settings.py"))
    vector_only = await store.add(rec("configuring databases needs the admin role"))
    await store.add(rec("the weather service caches forecasts"))
    hits = await store.search(
        AGENT, "a", "database configuration", mode="hybrid", min_similarity=0.2
    )
    ids = [hit.record.id for hit in hits]
    assert ids == [both.id, vector_only.id]  # in both rankings first; the unrelated one in neither
    # A lexical hit survives a threshold that removes it from the vector ranking.
    strict = await store.search(
        AGENT, "a", "database configuration", mode="hybrid", min_similarity=0.999
    )
    assert [hit.record.id for hit in strict] == [both.id]


async def test_search_respects_scope_namespace_and_limit() -> None:
    store = InMemoryMemoryStore(HashingEmbedder(64))
    for i in range(4):
        await store.add(rec(f"deploy step {i}"))
    await store.add(rec("deploy step other", ns="b"))
    hits = await store.search(AGENT, "a", "deploy step", mode="vector", limit=3)
    assert len(hits) == 3 and all(hit.record.namespace == "a" for hit in hits)
    assert await store.search(AGENT, "a", "deploy step", mode="vector", limit=0) == []
    assert await store.search(AGENT, "empty", "deploy step", mode="vector") == []


async def test_missing_embedder_falls_back_to_lexical_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryMemoryStore()
    await store.add(rec("use make test"))
    with caplog.at_level(logging.WARNING, logger="agentforge.memory"):
        first = await store.search(AGENT, "a", "make test", mode="vector")
        second = await store.search(AGENT, "a", "make test", mode="hybrid")
    assert len(first) == 1 and len(second) == 1
    warnings = [r for r in caplog.records if "no embedder is configured" in r.getMessage()]
    assert len(warnings) == 1


async def test_failing_embedder_falls_back_to_lexical(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryMemoryStore(FailingEmbedder())
    await store.add(rec("use make test"))
    with caplog.at_level(logging.WARNING, logger="agentforge.memory"):
        hits = await store.search(AGENT, "a", "make test", mode="vector")
    assert [hit.record.content for hit in hits] == ["use make test"]
    assert "endpoint unreachable" in caplog.text


async def test_failure_to_store_vectors_does_not_fail_the_search() -> None:
    class BrokenCache(InMemoryMemoryStore):
        async def _save_vectors(self, vectors: dict[str, list[float]], embedder: str) -> None:
            raise RuntimeError("disk full")

    store = BrokenCache(HashingEmbedder(64))
    await store.add(rec("alpha note"))
    hits = await store.search(AGENT, "a", "alpha note", mode="vector")
    assert len(hits) == 1


async def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="semantic"):
        await InMemoryMemoryStore().search(AGENT, "a", "q", mode="semantic")


# --------------------------------------------------------------------- config
def test_memory_config_defaults_and_validation() -> None:
    config = MemoryConfig()
    assert config.search is MemorySearchMode.LEXICAL and config.min_similarity == 0.0
    assert MemoryConfig(search="hybrid", min_similarity=0.3).search is MemorySearchMode.HYBRID
    with pytest.raises(ValidationError):
        MemoryConfig(search="semantic")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        MemoryConfig(min_similarity=1.5)


def test_build_embedder_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    def settings(**values: Any) -> Settings:
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    assert build_embedder(settings()) is None
    hashing = build_embedder(settings(memory_embedder="hashing", embedding_dimensions=64))
    assert isinstance(hashing, HashingEmbedder) and hashing.name == "hashing-v1:64"

    with pytest.raises(ConfigurationError, match="AGENTFORGE_EMBEDDING_MODEL"):
        build_embedder(settings(memory_embedder="openai-compatible"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY is not set"):
        build_embedder(settings(memory_embedder="openai-compatible", embedding_model="m"))
    with pytest.raises(ValidationError):
        settings(memory_embedder="word2vec")


# -------------------------------------------------------------- HTTP embedder
def embedding_server(seen: list[httpx.Request], *, shuffle: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        texts = json.loads(request.content)["input"]
        data = [{"index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(texts)]
        if shuffle:
            data.reverse()
        return httpx.Response(200, json={"data": data, "model": "m"})

    return httpx.MockTransport(handler)


async def test_http_embedder_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_KEY", "sk-embed-secret")
    seen: list[httpx.Request] = []
    embedder = build_embedder(
        Settings(
            memory_embedder="openai-compatible",
            embedding_model="text-embed-test",
            embedding_base_url="https://embeddings.example/v1/",
            embedding_api_key_env="EMBED_KEY",
            _env_file=None,  # type: ignore[call-arg]
        ),
        transport=embedding_server(seen, shuffle=True),
    )
    assert isinstance(embedder, HttpEmbedder)
    assert embedder.name == "openai-compatible:text-embed-test"
    vectors = await embedder.embed(["a", "abc", ""])
    await embedder.aclose()
    assert vectors == [[1.0, 1.0], [3.0, 1.0], [1.0, 1.0]]  # by index, not arrival order
    (request,) = seen
    assert str(request.url) == "https://embeddings.example/v1/embeddings"
    assert request.headers["authorization"] == "Bearer sk-embed-secret"
    assert json.loads(request.content) == {"model": "text-embed-test", "input": ["a", "abc", " "]}


async def test_http_embedder_without_a_key_sends_no_authorization() -> None:
    seen: list[httpx.Request] = []
    embedder = build_embedder(
        Settings(
            memory_embedder="openai-compatible",
            embedding_model="local-model",
            embedding_base_url="http://localhost:11434/v1",
            embedding_api_key_env="",
            _env_file=None,  # type: ignore[call-arg]
        ),
        transport=embedding_server(seen),
    )
    assert embedder is not None
    await embedder.embed(["x"])
    assert "authorization" not in seen[0].headers


async def test_http_embedder_batches_and_truncates() -> None:
    seen: list[httpx.Request] = []
    embedder = HttpEmbedder("m", transport=embedding_server(seen))
    texts = ["x" * (MAX_TEXT_CHARS + 50)] + ["y"] * BATCH_SIZE
    vectors = await embedder.embed(texts)
    assert len(vectors) == BATCH_SIZE + 1 and len(seen) == 2
    assert vectors[0][0] == float(MAX_TEXT_CHARS)
    assert await embedder.embed([]) == [] and len(seen) == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"error": {"message": "bad key"}}), "HTTP 401: bad key"),
        (httpx.Response(500, text="<html>oops</html>"), "HTTP 500"),
        (httpx.Response(200, text="not json"), "invalid response"),
        (httpx.Response(200, json={"data": []}), "expected 1 embeddings"),
        (httpx.Response(200, json={"data": [{"index": 0, "embedding": []}]}), "list of numbers"),
        (httpx.Response(200, json={"data": [{"index": 0, "embedding": ["a"]}]}), "list of numbers"),
        (httpx.Response(200, json={"data": [{"index": 3, "embedding": [1.0]}]}), "out of range"),
        (httpx.Response(200, json={"data": ["x"]}), "not an object"),
        (httpx.Response(200, json=[1]), "expected 1 embeddings"),
    ],
)
async def test_http_embedder_errors(response: httpx.Response, message: str) -> None:
    embedder = HttpEmbedder(
        "m", api_key="sk-embed-secret", transport=httpx.MockTransport(lambda request: response)
    )
    with pytest.raises(EmbeddingError) as excinfo:
        await embedder.embed(["the text"])
    assert message in excinfo.value.message
    assert "sk-embed-secret" not in excinfo.value.message
    assert "the text" not in excinfo.value.message


async def test_http_embedder_rejects_inconsistent_and_non_finite_vectors() -> None:
    def respond(data: list[dict[str, Any]]) -> httpx.MockTransport:
        body = json.dumps({"data": data}).replace('"NaN"', "NaN")
        return httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=body, headers={"content-type": "application/json"}
            )
        )

    ragged = [{"index": 0, "embedding": [1.0, 2.0]}, {"index": 1, "embedding": [1.0]}]
    with pytest.raises(EmbeddingError, match="different dimensions"):
        await HttpEmbedder("m", transport=respond(ragged)).embed(["a", "b"])
    repeated = [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [1.0]}]
    with pytest.raises(EmbeddingError, match="repeated"):
        await HttpEmbedder("m", transport=respond(repeated)).embed(["a", "b"])
    with pytest.raises(EmbeddingError, match="non-finite"):
        await HttpEmbedder("m", transport=respond([{"index": 0, "embedding": ["NaN"]}])).embed(
            ["a"]
        )


async def test_http_embedder_wraps_connection_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host sk-embed-secret")

    embedder = HttpEmbedder("m", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingError) as excinfo:
        await embedder.embed(["x"])
    assert excinfo.value.message == "embedding request failed: ConnectError"


def test_http_embedder_validates_the_model_name() -> None:
    with pytest.raises(ConfigurationError, match="required"):
        HttpEmbedder(" ")
    with pytest.raises(ConfigurationError, match="too long"):
        HttpEmbedder("m" * 200)


# ------------------------------------------------------------ runtime + tools
class CapturingProvider(LLMProvider):
    name = "capture"

    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        return CompletionResponse(
            message=Message.assistant("done"), stop_reason=StopReason.END_TURN, model="m"
        )


async def test_runtime_recall_uses_the_agents_search_mode(settings: Settings) -> None:
    store = InMemoryMemoryStore(HashingEmbedder(256))
    await store.add(rec("Database configuration lives in settings.py", ns="agt_1"))
    await store.add(rec("The weather service caches forecasts", ns="agt_1"))

    async def system_prompt(memory: dict[str, Any]) -> str:
        provider = CapturingProvider()
        prepared = prepare_run(
            scripted_config([], memory=memory),
            "configuring databases",
            agent_id="agt_1",
            settings=settings,
            memory=store,
            provider=provider,
        )
        await prepared.execute()
        return provider.requests[0].system or ""

    assert "settings.py" not in await system_prompt({})  # lexical: no shared word
    recalled = await system_prompt({"search": "vector", "min_similarity": 0.15})
    assert "settings.py" in recalled and "weather" not in recalled


async def test_recall_tool_uses_the_agents_search_mode(tool_ctx: ToolContext) -> None:
    assert isinstance(tool_ctx.memory, InMemoryMemoryStore)
    tool_ctx.memory.embedder = HashingEmbedder(256)
    await tool_ctx.memory.add(rec("Database configuration lives in settings.py", ns="agt_test"))
    args = RecallInput(query="configuring databases")
    assert (await Recall().run(args, tool_ctx)).content == "no relevant memories"
    tool_ctx.memory_search = "vector"
    tool_ctx.memory_min_similarity = 0.15
    assert "settings.py" in (await Recall().run(args, tool_ctx)).content


def test_agent_config_accepts_the_new_memory_fields() -> None:
    config = AgentConfig.model_validate(
        {
            "name": "a",
            "model": {"provider": "scripted"},
            "memory": {"search": "hybrid", "min_similarity": 0.25},
        }
    )
    assert config.memory.search is MemorySearchMode.HYBRID
    assert config.model_dump(mode="json")["memory"]["search"] == "hybrid"

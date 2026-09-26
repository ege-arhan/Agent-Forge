"""Token pricing used for *estimated* cost reporting.

Cost is reported only when the model's pricing is known; otherwise it is
``None`` - AgentForge never invents a price. The built-in table covers
first-party Anthropic list prices (USD per million tokens) as published at the
time of writing, and zero cost for providers with no API billing (scripted,
local). Additional or corrected prices can be supplied with a YAML/JSON file
referenced by ``AGENTFORGE_PRICING_FILE``::

    openai:
      some-model: {input: 1.0, output: 4.0, cache_read: 0.1}

Prices change; treat reported costs as estimates and verify against your bill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from agentforge.core.models import TokenUsage


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None

    def cost(self, usage: TokenUsage) -> float | None:
        total = usage.input_tokens * self.input + usage.output_tokens * self.output
        if usage.cache_read_tokens:
            if self.cache_read is None:
                return None
            total += usage.cache_read_tokens * self.cache_read
        if usage.cache_write_tokens:
            if self.cache_write is None:
                return None
            total += usage.cache_write_tokens * self.cache_write
        return total / 1_000_000


def _anthropic(inp: float, out: float, cache_read: float | None = None) -> ModelPrice:
    return ModelPrice(
        input=inp,
        output=out,
        cache_read=cache_read if cache_read is not None else inp * 0.1,
        cache_write=inp * 1.25,
    )


_BUILTIN: dict[str, dict[str, ModelPrice]] = {
    "anthropic": {
        "claude-fable-5-1": _anthropic(10.0, 50.0, 0.25),
        "claude-fable-5": _anthropic(10.0, 50.0),
        "claude-opus-5-5": _anthropic(4.0, 20.0, 0.20),
        "claude-opus-5": _anthropic(5.0, 25.0),
        "claude-opus-4-8": _anthropic(5.0, 25.0),
        "claude-opus-4-7": _anthropic(5.0, 25.0),
        "claude-opus-4-6": _anthropic(5.0, 25.0),
        "claude-sonnet-5": _anthropic(2.0, 10.0),
        "claude-sonnet-4-6": _anthropic(3.0, 15.0),
        "claude-haiku-4-5": _anthropic(1.0, 5.0),
    },
}

_FREE_PROVIDERS = frozenset({"scripted", "local"})


class PriceTable:
    def __init__(self, prices: dict[str, dict[str, ModelPrice]] | None = None) -> None:
        self._prices: dict[str, dict[str, ModelPrice]] = {
            provider: dict(models) for provider, models in _BUILTIN.items()
        }
        for provider, models in (prices or {}).items():
            self._prices.setdefault(provider, {}).update(models)

    @classmethod
    def from_file(cls, path: str | Path) -> PriceTable:
        text = Path(path).read_text(encoding="utf-8")
        raw = json.loads(text) if str(path).endswith(".json") else yaml.safe_load(text)
        prices = {
            provider: {model: ModelPrice(**spec) for model, spec in (models or {}).items()}
            for provider, models in (raw or {}).items()
        }
        return cls(prices)

    def lookup(self, provider: str, model: str) -> ModelPrice | None:
        if provider in _FREE_PROVIDERS:
            return ModelPrice(0.0, 0.0, 0.0, 0.0)
        return self._prices.get(provider, {}).get(model)

    def estimate(self, provider: str, model: str, usage: TokenUsage) -> float | None:
        price = self.lookup(provider, model)
        return None if price is None else price.cost(usage)

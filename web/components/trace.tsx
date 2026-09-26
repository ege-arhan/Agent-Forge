"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { EvalBadge, ToolStatusBadge } from "@/components/status";
import { formatCost, formatMs, formatNumber, formatTokens } from "@/lib/format";
import type { Step, ToolCallRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function Pre({ children, className }: { children: string; className?: string }) {
  return (
    <pre
      className={cn(
        "max-h-96 overflow-auto rounded-md border border-line bg-page p-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink [overflow-wrap:anywhere]",
        className,
      )}
    >
      {children}
    </pre>
  );
}

function ToolCall({ call }: { call: ToolCallRecord }) {
  const [open, setOpen] = useState(call.status !== "success");
  const args = JSON.stringify(call.arguments, null, 2);
  const preview = JSON.stringify(call.arguments);
  return (
    <div className="rounded-md border border-line">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-surface-2"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown aria-hidden className="size-3.5 shrink-0 text-muted" />
        ) : (
          <ChevronRight aria-hidden className="size-3.5 shrink-0 text-muted" />
        )}
        <span className="font-mono text-xs font-medium text-ink">{call.tool}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{preview}</span>
        <ToolStatusBadge status={call.status} />
        <span className="tabular w-16 shrink-0 text-right text-xs text-muted">{formatMs(call.duration_ms)}</span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-line p-2.5">
          <div>
            <div className="mb-1 text-[11px] font-medium tracking-wide text-muted uppercase">Arguments</div>
            <Pre>{args}</Pre>
          </div>
          <div>
            <div className="mb-1 text-[11px] font-medium tracking-wide text-muted uppercase">
              Output{call.truncated ? " (truncated)" : ""}
            </div>
            <Pre>{call.output || "(no output)"}</Pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StepMeta({ step }: { step: Step }) {
  const llm = step.llm_call;
  if (!llm) return null;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
      <span className="font-mono">{llm.model}</span>
      <span className="tabular">{formatMs(llm.latency_ms)}</span>
      <span className="tabular">
        {formatTokens(llm.usage.input_tokens)} in · {formatTokens(llm.usage.output_tokens)} out
      </span>
      {llm.attempts > 1 ? <span className="text-serious">{llm.attempts} attempts</span> : null}
      {llm.stop_reason ? <span>stop: {llm.stop_reason}</span> : null}
      <span>cost {formatCost(llm.cost_usd)}</span>
    </div>
  );
}

function StepCard({ step }: { step: Step }) {
  const kindLabel = step.kind === "plan" ? "Plan" : step.kind === "evaluation" ? "Evaluation" : "Step";
  return (
    <li className="relative min-w-0 pl-6">
      <span
        aria-hidden
        className={cn(
          "absolute top-1.5 left-0 size-2.5 rounded-full border-2 border-surface",
          step.error ? "bg-critical" : step.kind === "evaluation" ? "bg-ink-2" : "bg-series-1",
        )}
      />
      <div className="mb-1 flex flex-wrap items-center gap-x-3">
        <span className="text-[13px] font-semibold text-ink">
          {kindLabel} {step.index}
        </span>
        <StepMeta step={step} />
      </div>
      {step.thought ? <p className="mb-2 text-[13px] whitespace-pre-wrap text-ink-2 [overflow-wrap:anywhere]">{step.thought}</p> : null}
      {step.plan ? (
        <ol className="mb-2 list-decimal pl-5 text-[13px] text-ink-2">
          {step.plan.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ol>
      ) : null}
      {step.tool_calls.length > 0 ? (
        <div className="space-y-1.5">
          {step.tool_calls.map((call) => (
            <ToolCall key={`${step.index}-${call.id}`} call={call} />
          ))}
        </div>
      ) : null}
      {step.evaluation ? (
        <div className="mt-1 rounded-md border border-line p-2.5">
          <div className="mb-1.5 flex items-center gap-2">
            <EvalBadge passed={step.evaluation.passed} />
            <span className="tabular text-xs text-muted">score {formatNumber(step.evaluation.score)}</span>
          </div>
          <ul className="space-y-0.5 text-xs">
            {step.evaluation.results.map((r) => (
              <li key={r.name} className="flex gap-2">
                <EvalBadge passed={r.passed} />
                <span className="font-mono text-ink">{r.name}</span>
                <span className="truncate text-muted">{r.details.split("\n")[0]}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {step.error ? (
        <div className="mt-1.5 text-xs text-critical-text">
          {step.error.type}: {step.error.message}
        </div>
      ) : null}
    </li>
  );
}

export function Trace({ steps }: { steps: Step[] }) {
  if (steps.length === 0) return <p className="text-[13px] text-muted">No steps recorded yet.</p>;
  return (
    <ol className="relative space-y-5 before:absolute before:top-2 before:bottom-2 before:left-[4px] before:w-px before:bg-grid">
      {steps.map((step) => (
        <StepCard key={step.index} step={step} />
      ))}
    </ol>
  );
}

export { Pre };

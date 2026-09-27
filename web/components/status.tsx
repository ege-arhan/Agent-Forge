import {
  Ban,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  LoaderCircle,
  ShieldAlert,
  ShieldQuestion,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import type { RunStatus, ToolCallStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

// Status is always icon + label (never colour alone). The label uses text ink;
// only the icon carries the reserved status colour.
interface StatusSpec {
  label: string;
  icon: LucideIcon;
  iconClass: string;
  spin?: boolean;
}

const RUN_STATUS: Record<RunStatus, StatusSpec> = {
  pending: { label: "Pending", icon: CircleDashed, iconClass: "text-muted" },
  running: { label: "Running", icon: LoaderCircle, iconClass: "text-series-1", spin: true },
  awaiting_approval: { label: "Awaiting approval", icon: ShieldQuestion, iconClass: "text-warning" },
  succeeded: { label: "Succeeded", icon: CircleCheck, iconClass: "text-good" },
  failed: { label: "Failed", icon: CircleX, iconClass: "text-critical" },
  cancelled: { label: "Cancelled", icon: Ban, iconClass: "text-muted" },
  timed_out: { label: "Timed out", icon: Clock, iconClass: "text-serious" },
};

const TOOL_STATUS: Record<ToolCallStatus, StatusSpec> = {
  success: { label: "ok", icon: CircleCheck, iconClass: "text-good" },
  error: { label: "error", icon: CircleX, iconClass: "text-critical" },
  denied: { label: "denied", icon: ShieldAlert, iconClass: "text-serious" },
  timeout: { label: "timeout", icon: Clock, iconClass: "text-serious" },
  invalid_input: { label: "invalid input", icon: TriangleAlert, iconClass: "text-warning" },
};

function Pill({ spec, className }: { spec: StatusSpec; className?: string }) {
  const Icon = spec.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[13px] whitespace-nowrap text-ink-2", className)}>
      <Icon aria-hidden className={cn("size-3.5 shrink-0", spec.iconClass, spec.spin && "animate-spin")} />
      {spec.label}
    </span>
  );
}

export function RunStatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  return <Pill spec={RUN_STATUS[status] ?? RUN_STATUS.pending} className={className} />;
}

export function ToolStatusBadge({ status }: { status: ToolCallStatus }) {
  return <Pill spec={TOOL_STATUS[status] ?? TOOL_STATUS.error} />;
}

export function EvalBadge({ passed }: { passed: boolean | null | undefined }) {
  if (passed === null || passed === undefined) {
    return <span className="text-[13px] text-muted">not evaluated</span>;
  }
  return (
    <Pill
      spec={
        passed
          ? { label: "Passed", icon: CircleCheck, iconClass: "text-good" }
          : { label: "Failed", icon: CircleX, iconClass: "text-critical" }
      }
    />
  );
}

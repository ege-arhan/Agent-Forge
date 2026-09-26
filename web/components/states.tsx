import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="px-4 py-8 text-center text-[13px] text-muted">{label}</div>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-line bg-surface px-4 py-3 text-[13px]">
      <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-serious" />
      <div>
        <p className="font-medium text-ink">{message}</p>
        <p className="mt-0.5 text-muted">
          Check that the API is running and the connection in{" "}
          <Link href="/settings" className="underline">
            Settings
          </Link>{" "}
          is correct.
        </p>
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-8 text-center text-[13px] text-muted">{children}</div>;
}

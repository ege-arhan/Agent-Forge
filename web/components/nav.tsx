"use client";

import {
  Bot,
  FlaskConical,
  FolderGit2,
  Gauge,
  GitPullRequest,
  LayoutDashboard,
  Moon,
  Play,
  Settings,
  Sun,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/runs", label: "Runs", icon: Play },
  { href: "/benchmarks", label: "Benchmarks", icon: Gauge },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/improvement", label: "Improvement", icon: TrendingUp },
  { href: "/repositories", label: "Repositories", icon: FolderGit2 },
  { href: "/github", label: "GitHub tasks", icon: GitPullRequest },
  { href: "/settings", label: "Settings", icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function ApiIndicator() {
  const [state, setState] = useState<"checking" | "ok" | "down">("checking");
  const [version, setVersion] = useState("");
  useEffect(() => {
    let cancelled = false;
    const check = () =>
      api
        .health()
        .then((h) => {
          if (!cancelled) {
            setState(h.status === "ok" ? "ok" : "down");
            setVersion(h.version);
          }
        })
        .catch(() => !cancelled && setState("down"));
    void check();
    const timer = setInterval(check, 15_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span
        aria-hidden
        className={cn(
          "size-2 rounded-full",
          state === "ok" ? "bg-good" : state === "down" ? "bg-critical" : "bg-axis",
        )}
      />
      {state === "ok" ? `API connected · v${version}` : state === "down" ? "API unreachable" : "Checking API…"}
    </div>
  );
}

const THEME_EVENT = "agentforge:theme";

function subscribeTheme(callback: () => void): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", callback);
  window.addEventListener(THEME_EVENT, callback);
  return () => {
    media.removeEventListener("change", callback);
    window.removeEventListener(THEME_EVENT, callback);
  };
}

function currentTheme(): "light" | "dark" {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => null);
  const toggle = () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem("agentforge.theme", next);
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  };
  return (
    <button
      type="button"
      onClick={toggle}
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-surface-2"
      aria-label="Toggle colour theme"
    >
      {theme === "dark" ? <Sun className="size-3.5" aria-hidden /> : <Moon className="size-3.5" aria-hidden />}
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="border-b border-line bg-surface md:sticky md:top-0 md:flex md:h-screen md:w-52 md:shrink-0 md:flex-col md:border-r md:border-b-0">
      <div className="flex items-center justify-between px-4 py-3 md:block">
        <Link href="/" className="text-[15px] font-semibold tracking-tight text-ink">
          AgentForge
        </Link>
        <div className="md:hidden">
          <ThemeToggle />
        </div>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-1 md:flex-col md:overflow-visible md:pb-0">
        {LINKS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] whitespace-nowrap",
              isActive(pathname, href)
                ? "bg-surface-2 font-medium text-ink"
                : "text-ink-2 hover:bg-surface-2 hover:text-ink",
            )}
          >
            <Icon aria-hidden className="size-4" />
            {label}
          </Link>
        ))}
      </nav>
      <div className="hidden space-y-2 border-t border-line px-4 py-3 md:block">
        <ApiIndicator />
        <ThemeToggle />
      </div>
    </aside>
  );
}

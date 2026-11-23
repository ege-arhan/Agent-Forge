// Shared module mocks. Import this file first in a test: `vi.mock` calls are
// hoisted, so the pages under test get these instead of the real modules.

import type { AnchorHTMLAttributes } from "react";
import { vi } from "vitest";

export const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn() };
export const route: { params: Record<string, string>; search: string } = { params: {}, search: "" };

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useParams: () => route.params,
  useSearchParams: () => new URLSearchParams(route.search),
  usePathname: () => "/",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// Every API call is a mock; a test sets the ones its component uses. A call
// that was not set up rejects, so a forgotten mock fails loudly.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const api = Object.fromEntries(
    Object.keys(actual.api).map((name) => [
      name,
      vi.fn(() => Promise.reject(new Error(`api.${name} was not mocked`))),
    ]),
  );
  return { ...actual, api };
});

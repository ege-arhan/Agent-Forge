import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "AgentForge",
  description: "Engineer, run, observe, evaluate and benchmark LLM agents.",
};

// Apply a stored theme before first paint to avoid a flash.
const themeScript = `try{var t=localStorage.getItem("agentforge.theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen antialiased md:flex">
        <Sidebar />
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </body>
    </html>
  );
}

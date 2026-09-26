"use client";

import { useState, useSyncExternalStore } from "react";

import { PageHeader } from "@/components/page-header";
import { Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, loadConnection, saveConnection } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const noopSubscribe = () => () => {};

/** Rendered only in the browser: its initial state comes from localStorage. */
function ConnectionForm({ onSaved }: { onSaved: () => void }) {
  const [baseUrl, setBaseUrl] = useState(() => loadConnection().baseUrl);
  const [apiKey, setApiKey] = useState(() => loadConnection().apiKey);
  const [saved, setSaved] = useState(false);

  const save = () => {
    saveConnection({ baseUrl: baseUrl.trim(), apiKey: apiKey.trim() });
    setSaved(true);
    onSaved();
  };

  return (
    <Card>
      <CardHeader
          title="API connection"
          description="Stored in this browser only. The API key is sent as a bearer token when the server requires one."
        />
        <CardBody className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <div>
            <Label htmlFor="url">API URL</Label>
            <Input id="url" value={baseUrl} onChange={(e) => (setBaseUrl(e.target.value), setSaved(false))} />
          </div>
          <div>
            <Label htmlFor="key">API key</Label>
            <Input
              id="key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => (setApiKey(e.target.value), setSaved(false))}
              placeholder="optional"
            />
          </div>
          <Button onClick={save}>{saved ? "Saved" : "Save"}</Button>
        </CardBody>
      </Card>
  );
}

export default function SettingsPage() {
  const isClient = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const providers = useApi(() => api.providers(), []);
  const tools = useApi(() => api.tools(), []);
  const evaluators = useApi(() => api.evaluators(), []);
  const reloadAll = () => {
    providers.reload();
    tools.reload();
    evaluators.reload();
  };

  return (
    <>
      <PageHeader title="Settings" description="API connection and server capabilities." />
      {isClient ? <ConnectionForm onSaved={reloadAll} /> : <Loading />}

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="LLM providers" description="Keys are read from the server environment." />
          {!providers.data ? (
            <Loading />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Provider</TH>
                  <TH>Key variable</TH>
                  <TH>Description</TH>
                </TR>
              </THead>
              <TBody>
                {providers.data.map((p) => (
                  <TR key={p.name}>
                    <TD className="font-mono text-xs">{p.name}</TD>
                    <TD className="font-mono text-xs text-ink-2">{p.api_key_env ?? "—"}</TD>
                    <TD className="text-ink-2">{p.description}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="Evaluators" />
          {!evaluators.data ? (
            <Loading />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Type</TH>
                  <TH>Checks</TH>
                </TR>
              </THead>
              <TBody>
                {evaluators.data.map((e) => (
                  <TR key={e.type}>
                    <TD className="font-mono text-xs">{e.type}</TD>
                    <TD className="text-ink-2">{e.description}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Tools" description="Grouped into toolsets; agents list toolsets or tool names." />
        {!tools.data ? (
          <Loading />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Tool</TH>
                <TH>Toolset</TH>
                <TH>Permissions</TH>
                <TH className="text-right">Timeout</TH>
                <TH>Description</TH>
              </TR>
            </THead>
            <TBody>
              {tools.data.tools.map((t) => (
                <TR key={t.name}>
                  <TD className="font-mono text-xs">{t.name}</TD>
                  <TD className="text-ink-2">{t.toolset ?? "—"}</TD>
                  <TD className="font-mono text-xs text-ink-2">{t.permissions.join(", ") || "—"}</TD>
                  <TD className="tabular text-right">{t.timeout_seconds}s</TD>
                  <TD className="text-ink-2">{t.description}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}

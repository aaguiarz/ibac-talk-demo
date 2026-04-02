import { useState, useMemo, useCallback } from "react";
import {
  X,
  Zap,
  Brain,
  ShieldCheck,
  Plug,
  ArrowRight,
} from "lucide-react";
import type {
  ActivityEvent,
  ActivityEventType as ActivityEventTypeEnum,
  LaneId,
} from "../types";
import { getEventConfig } from "./ActivityEvent";

// ---------------------------------------------------------------------------
// Lane & group config
// ---------------------------------------------------------------------------

interface LaneConfig {
  id: LaneId;
  label: string;
  icon: React.ElementType;
  color: string;
  bg: string;
  border: string;
}

interface LaneGroup {
  label: string;
  lanes: LaneConfig[];
}

const LANE_GROUPS: LaneGroup[] = [
  {
    label: "Orchestrator",
    lanes: [
      { id: "agent", label: "Agent", icon: Zap, color: "text-blue-600", bg: "bg-blue-50", border: "border-blue-300" },
      { id: "intent", label: "Intent Engine + Trusted LLM", icon: Brain, color: "text-teal-600", bg: "bg-teal-50", border: "border-teal-300" },
    ],
  },
  {
    label: "MCP Server",
    lanes: [
      { id: "middleware", label: "FastMCP Middleware", icon: ShieldCheck, color: "text-emerald-600", bg: "bg-emerald-50", border: "border-emerald-300" },
      { id: "tools", label: "Tools", icon: Plug, color: "text-violet-600", bg: "bg-violet-50", border: "border-violet-300" },
    ],
  },
];

// ---------------------------------------------------------------------------
// Row data structure
// ---------------------------------------------------------------------------

interface FlowRow {
  timestamp: number;
  agent?: ActivityEvent;
  intent?: ActivityEvent;
  middleware?: ActivityEvent;
  tools?: ActivityEvent;
  isFullWidth?: boolean;
}

// ---------------------------------------------------------------------------
// Lane classification
// ---------------------------------------------------------------------------

function classifyLane(type: ActivityEventTypeEnum): LaneId {
  switch (type) {
    case "tool_call_start":
    case "tool_call_end":
      return "agent";
    case "fga_check":
    case "fga_write":
    case "fga_batch_check":
    case "fga_delete":
    case "elicitation":
    case "permission_requested":
      return "middleware";
    case "discovery_result":
    case "mcp_tools_listed":
      return "tools";
    case "namespaces_fetched":
      return "middleware";
    case "discovery_authorized":
    case "actions_authorized":
      return "intent";
    default:
      return "intent";
  }
}

// ---------------------------------------------------------------------------
// Row grouping algorithm
// ---------------------------------------------------------------------------

const GROUP_THRESHOLD_MS = 0.1; // 100ms in seconds (timestamps are epoch seconds)

function groupIntoRows(events: ActivityEvent[]): FlowRow[] {
  const rows: FlowRow[] = [];

  // Build a map of tool_call_end events keyed by tool call id for synthetic Tools entries
  const endByCallId = new Map<string, ActivityEvent>();
  for (const e of events) {
    if (e.type === "tool_call_end") {
      const callId = (e.data.id as string) || e.id;
      endByCallId.set(callId, e);
    }
  }

  for (const event of events) {
    // Skip tool_call_end — they're merged into tool_call_start rows
    if (event.type === "tool_call_end") continue;

    // Skip connection setup noise
    if (event.type === "mcp_connection") continue;

    // Full-width rows for section / status banners (skip connecting & cleanup noise)
    if (event.type === "flow_section" || event.type === "flow_status") {
      const label = ((event.data.section as string) || (event.data.phase as string) || "").toLowerCase();
      if (label === "connecting" || label === "cleanup") continue;
      rows.push({ timestamp: event.timestamp, intent: event, isFullWidth: true });
      continue;
    }

    const lane = classifyLane(event.type);

    // Orchestrator-initiated tool calls have known id prefixes
    const callId = (event.type === "tool_call_start" && typeof event.data.id === "string")
      ? (event.data.id as string) : "";
    const isDiscovery = callId.startsWith("discovery_") || callId === "fetch_namespaces";

    // Try to merge into last row if within threshold and lane is free
    const lastRow = rows.length > 0 ? rows[rows.length - 1] : null;
    const canMerge =
      lastRow &&
      !lastRow.isFullWidth &&
      Math.abs(event.timestamp - lastRow.timestamp) <= GROUP_THRESHOLD_MS &&
      !lastRow[lane];

    // For discovery calls, also need the tools lane free
    const canMergeDiscovery = canMerge && !lastRow!.tools;

    if (isDiscovery) {
      // Discovery calls go to intent lane; result goes to tools lane
      // (fetch_namespaces result goes to middleware via namespaces_fetched, no tools column)
      const toolsEvent = callId === "fetch_namespaces"
        ? null
        : buildToolsSyntheticEvent(event, endByCallId);
      if (canMergeDiscovery) {
        lastRow!.intent = event;
        if (toolsEvent) lastRow!.tools = toolsEvent;
      } else {
        const row: FlowRow = { timestamp: event.timestamp, intent: event };
        if (toolsEvent) row.tools = toolsEvent;
        rows.push(row);
      }
      continue;
    }

    // Regular tool_call_start: agent lane + tools lane for result
    if (event.type === "tool_call_start") {
      const toolsEvent = buildToolsSyntheticEvent(event, endByCallId);
      // Also check if there's an fga_check close in time — look ahead
      if (canMerge && (!toolsEvent || !lastRow!.tools)) {
        lastRow![lane] = event;
        if (toolsEvent && !lastRow!.tools) lastRow!.tools = toolsEvent;
      } else {
        const row: FlowRow = { timestamp: event.timestamp, [lane]: event };
        if (toolsEvent) row.tools = toolsEvent;
        rows.push(row);
      }
      continue;
    }

    // All other events
    if (canMerge) {
      lastRow![lane] = event;
    } else {
      rows.push({ timestamp: event.timestamp, [lane]: event });
    }
  }

  return rows;
}

/** Build a synthetic "tools" event from tool_call_start + its end result. */
function buildToolsSyntheticEvent(
  startEvent: ActivityEvent,
  endByCallId: Map<string, ActivityEvent>,
): ActivityEvent | null {
  const callId = (startEvent.data.id as string) || startEvent.id;
  const endEvent = endByCallId.get(callId);

  // If the start event already has merged result (done=true), use it
  if (startEvent.data.done) {
    return {
      ...startEvent,
      id: `${startEvent.id}_tools`,
      type: "tool_call_end",
      data: {
        ...startEvent.data,
        _synthetic: true,
      },
    };
  }

  if (endEvent) {
    return {
      ...endEvent,
      id: `${endEvent.id}_tools`,
      data: {
        ...endEvent.data,
        _synthetic: true,
      },
    };
  }

  return null;
}

// ---------------------------------------------------------------------------
// One-liner summary for event nodes
// ---------------------------------------------------------------------------

function oneLiner(event: ActivityEvent): string {
  switch (event.type) {
    case "task_created":
      return (event.data.task_id as string)?.slice(0, 8) || "";
    case "mcp_connection":
      return String(event.data.server ?? "").split("/").pop() || "";
    case "mcp_tools_listed":
      return `${event.data.count ?? 0} tools`;
    case "planning_call":
      return `${(event.data.tools_provided as string[])?.length || 0} tool defs`;
    case "plan_generated":
      return `${(event.data.actions as string[])?.length || 0} actions`;
    case "plan_validated":
      return `${(event.data.actions as string[])?.length || 0} validated`;
    case "discovery_result":
      return `${(event.data.resources as unknown[])?.length || 0} resources`;
    case "name_resolved":
      return `${event.data.input} -> ${event.data.resolved_id}`;
    case "fga_write":
      return `${(event.data.tuples as unknown[])?.length || 0} tuple(s)`;
    case "fga_check":
      return (event.data.allowed as boolean) ? "allowed" : "denied";
    case "fga_batch_check": {
      const checks = (event.data.checks as Array<{ allowed: boolean }>) || [];
      return `${checks.filter((c) => c.allowed).length}/${checks.length} allowed`;
    }
    case "fga_delete":
      return `${event.data.count ?? 0} deleted`;
    case "tool_call_start":
      return (event.data.tool as string) || "";
    case "tool_call_end": {
      const tool = (event.data.tool as string) || "";
      const hasError = !!event.data.error;
      return hasError ? `${tool} (error)` : tool;
    }
    case "namespaces_fetched": {
      const ns = (event.data.namespaces as unknown[]) || [];
      return `${ns.length} resource namespaces`;
    }
    case "discovery_authorized":
      return `${event.data.tuples_written ?? 0} tuple(s)`;
    case "actions_authorized":
      return `${event.data.tuples_written ?? 0} tuple(s)`;
    case "task_cleanup":
      return `${event.data.tuples_deleted ?? 0} tuples`;
    case "elicitation":
      return String(event.data.message ?? "").slice(0, 40);
    case "permission_requested":
      return (event.data.status as string) || "";
    default:
      return "";
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Compact one-line label for non-intent lanes. */
function compactLabel(event: ActivityEvent): string {
  switch (event.type) {
    case "tool_call_start":
      return `Call ${event.data.tool as string}`;
    case "tool_call_end":
      return event.data.error
        ? `Blocked ${event.data.tool as string}`
        : `Called ${event.data.tool as string}`;
    case "fga_check":
      return `Check ${(event.data.allowed as boolean) ? "\u2713" : "\u2717"}`;
    case "fga_batch_check": {
      const checks = (event.data.checks as Array<{ allowed: boolean }>) || [];
      const ok = checks.filter((c) => c.allowed).length;
      return `Batch Check ${ok}/${checks.length}`;
    }
    case "fga_write":
      return `Write ${(event.data.tuples as unknown[])?.length || 0} tuple(s)`;
    case "fga_delete":
      return `Delete ${event.data.count ?? 0} tuple(s)`;
    case "elicitation":
      return "Elicitation";
    case "permission_requested":
      return `Permission ${event.data.status as string}`;
    case "task_cleanup":
      return `Cleanup ${event.data.tuples_deleted ?? 0} tuples`;
    default:
      return oneLiner(event) || event.type;
  }
}

/** Full card for the Intent Engine lane. */
function IntentEventNode({ event, onSelect }: { event: ActivityEvent; onSelect: (e: ActivityEvent) => void }) {
  const config = getEventConfig(event);
  const Icon = config.icon;

  return (
    <button
      onClick={() => onSelect(event)}
      className={`w-full flex items-center gap-2.5 px-4 py-2.5 rounded-lg border ${config.borderColor} ${config.bgColor} text-left hover:brightness-95 transition-all cursor-pointer`}
    >
      <Icon className={`w-4 h-4 shrink-0 ${config.color}`} />
      <span className="text-sm font-semibold text-slate-800 truncate">
        {config.label}
      </span>
      <span className="text-xs text-slate-600 ml-auto truncate max-w-[200px]">
        {oneLiner(event)}
      </span>
    </button>
  );
}

/** Compact card for Agent / Middleware / Tools lanes. */
function CompactEventNode({ event, onSelect }: { event: ActivityEvent; onSelect: (e: ActivityEvent) => void }) {
  const config = getEventConfig(event);
  const Icon = config.icon;

  return (
    <button
      onClick={() => onSelect(event)}
      className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg border ${config.borderColor} ${config.bgColor} text-left hover:brightness-95 transition-all cursor-pointer`}
    >
      <Icon className={`w-4 h-4 shrink-0 ${config.color}`} />
      <span className={`text-sm font-semibold ${config.color} truncate`}>
        {compactLabel(event)}
      </span>
    </button>
  );
}

function PlanCard({ event, onSelect }: { event: ActivityEvent; onSelect: (e: ActivityEvent) => void }) {
  const actions = (event.data.actions as string[]) || [];
  const denied = (event.data.denied_implicit as Array<{ tool: string; reason: string }>) || [];
  const discovery = (event.data.derived_discovery as string[]) || [];

  return (
    <button
      onClick={() => onSelect(event)}
      className="w-full rounded-lg border-2 border-teal-400 bg-teal-50 p-4 space-y-3 text-left hover:brightness-95 transition-all cursor-pointer"
    >
      <div className="text-sm font-bold text-teal-800">Generated Plan</div>
      <div className="space-y-3">
        {discovery.length > 0 && (
          <div>
            <div className="text-xs font-bold text-slate-700 mb-1">Tools to discover Resource IDs</div>
            {discovery.map((d, i) => (
              <div key={`d-${i}`} className="flex items-center gap-2">
                <span className="text-cyan-700 text-sm">&#10003;</span>
                <span className="text-sm font-mono text-cyan-800">{d.endsWith(":*") ? d.slice(0, -2) : d}</span>
              </div>
            ))}
          </div>
        )}
        {actions.length > 0 && (
          <div>
            <div className="text-xs font-bold text-slate-700 mb-1">Intent-aligned actions identified by trusted LLM</div>
            {actions.map((a, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-green-700 text-sm">&#10003;</span>
                <span className="text-sm font-mono text-slate-800">{a}</span>
              </div>
            ))}
          </div>
        )}
        {denied.length > 0 && (
          <div>
            <div className="text-xs font-bold text-slate-700 mb-1">Actions not aligned with intent</div>
            {denied.map((d, i) => (
              <div key={`x-${i}`} className="flex items-center gap-2">
                <span className="text-red-600 text-sm">&#10007;</span>
                <span className="text-sm font-mono text-slate-800">{d.tool}</span>
                <span className="text-sm text-slate-600">- {d.reason}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

function EmptyCell() {
  return (
    <div className="min-h-[40px] flex justify-center">
      <div className="w-px bg-slate-100 h-full" />
    </div>
  );
}

const PHASE_DISPLAY_NAMES: Record<string, string> = {
  authorization: "Intent Authorization",
};

function FullWidthBanner({ event }: { event: ActivityEvent }) {
  const raw = (event.data.section as string) || (event.data.phase as string);
  const label = PHASE_DISPLAY_NAMES[raw] || raw;
  return (
    <div className="col-span-5 flex items-center gap-3 py-2 my-1">
      <div className="flex-1 h-0.5 bg-slate-300" />
      <span className="text-xs font-bold text-slate-600 uppercase tracking-wider">
        {label}
      </span>
      <div className="flex-1 h-0.5 bg-slate-300" />
    </div>
  );
}

function CellContent({ event, lane, onSelect }: { event: ActivityEvent | undefined; lane: LaneId; onSelect: (e: ActivityEvent) => void }) {
  if (!event) return <EmptyCell />;
  if (event.type === "plan_generated") return <PlanCard event={event} onSelect={onSelect} />;
  if (lane === "intent") return <IntentEventNode event={event} onSelect={onSelect} />;
  return <CompactEventNode event={event} onSelect={onSelect} />;
}

// ---------------------------------------------------------------------------
// Event detail modal
// ---------------------------------------------------------------------------

function FgaTupleDisplay({ tuple }: { tuple: { user: string; relation: string; object: string } }) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-mono py-0.5 flex-wrap">
      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
        {tuple.user}
      </span>
      <ArrowRight className="w-3 h-3 text-slate-400" />
      <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200 text-[10px]">
        {tuple.relation}
      </span>
      <ArrowRight className="w-3 h-3 text-slate-400" />
      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
        {tuple.object}
      </span>
    </div>
  );
}

function NamespaceList({ namespaces }: { namespaces: Array<{ name: string; list_tool: string; tool_resources: Record<string, string> }> | undefined }) {
  if (!namespaces?.length) return <div className="text-xs text-slate-400">No namespaces</div>;
  return (
    <div>
      <div className="text-sm font-bold text-slate-800 mb-2">Resource Namespaces</div>
      <div className="space-y-2">
        {namespaces.map((ns, i) => (
          <div key={i} className="rounded-lg border-2 border-slate-200 p-3 space-y-1.5">
            <div className="text-sm font-bold text-slate-800">{ns.name}</div>
            {ns.list_tool && (
              <div className="text-xs">
                <span className="text-slate-600 font-medium">Discovery: </span>
                <span className="font-mono text-slate-800">{ns.list_tool}</span>
              </div>
            )}
            {Object.entries(ns.tool_resources || {}).map(([tool, arg]) => (
              <div key={tool} className="text-xs space-y-0.5">
                <div>
                  <span className="text-slate-600 font-medium">Action: </span>
                  <span className="font-mono text-slate-800">{tool}</span>
                </div>
                <div>
                  <span className="text-slate-600 font-medium">Resource Parameter: </span>
                  <span className="font-mono text-slate-800">{arg}</span>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function EventDetailContent({ event }: { event: ActivityEvent }) {
  switch (event.type) {
    case "task_created":
      return (
        <div className="space-y-2">
          <div className="text-xs font-medium text-slate-500">Task ID</div>
          <div className="text-sm font-mono bg-slate-50 rounded p-2">{event.data.task_id as string}</div>
        </div>
      );
    case "planning_call":
      return (
        <div className="space-y-3">
          <div>
            <div className="text-sm font-semibold text-slate-800 mb-1">Model</div>
            <div className="text-sm font-mono">{event.data.model as string}</div>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-800 mb-1">User Prompt</div>
            <div className="text-sm bg-slate-50 rounded p-2">{String(event.data.prompt ?? "")}</div>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-800 mb-1">Tool Descriptions Sent</div>
            <div className="flex flex-wrap gap-1">
              {(event.data.tools_provided as string[])?.map((t, i) => (
                <span key={i} className="px-2 py-0.5 rounded bg-orange-100 text-orange-800 text-xs font-mono">{t}</span>
              ))}
            </div>
          </div>
        </div>
      );
    case "plan_generated":
      return (
        <div className="space-y-4">
          {(event.data.derived_discovery as string[])?.length > 0 && (
            <div>
              <div className="text-sm font-bold text-slate-800 mb-1.5">Tools to discover Resource IDs</div>
              <div className="flex flex-wrap gap-1">
                {(event.data.derived_discovery as string[])?.map((d, i) => (
                  <span key={i} className="px-2 py-0.5 rounded bg-cyan-100 text-cyan-800 text-xs font-mono">{d.endsWith(":*") ? d.slice(0, -2) : d}</span>
                ))}
              </div>
            </div>
          )}
          <div>
            <div className="text-sm font-bold text-slate-800 mb-1.5">Intent-aligned actions identified by trusted LLM</div>
            <div className="flex flex-wrap gap-1">
              {(event.data.actions as string[])?.map((a, i) => (
                <span key={i} className="px-2 py-0.5 rounded bg-green-100 text-green-800 text-xs font-mono">{a}</span>
              ))}
            </div>
          </div>
          {(event.data.denied_implicit as Array<{ tool: string; reason: string }>)?.length > 0 && (
            <div>
              <div className="text-sm font-bold text-slate-800 mb-1.5">Actions not aligned with intent</div>
              <div className="space-y-1">
                {(event.data.denied_implicit as Array<{ tool: string; reason: string }>).map((d, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="px-2 py-0.5 rounded bg-red-100 text-red-800 text-xs font-mono shrink-0">{d.tool}</span>
                    <span className="text-xs text-slate-500">{d.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      );
    case "plan_validated":
      return (
        <div>
          <div className="text-sm font-semibold text-slate-800 mb-1">Validated Actions</div>
          <div className="flex flex-wrap gap-1">
            {(event.data.actions as string[])?.map((a, i) => (
              <span key={i} className="px-2 py-0.5 rounded bg-purple-100 text-purple-800 text-xs font-mono">{a}</span>
            ))}
          </div>
        </div>
      );
    case "namespaces_fetched":
      return <NamespaceList namespaces={event.data.namespaces as Array<{ name: string; list_tool: string; tool_resources: Record<string, string> }>} />;
    case "discovery_authorized":
    case "actions_authorized": {
      const tuples = (event.data.tuples as Array<{ user: string; relation: string; object: string }>) || [];
      return (
        <div className="space-y-3">
          <div className="text-xs text-slate-500">
            Scope: <span className="font-medium">{(event.data.scope as string) || "task"}</span>
            {" \u2022 "}Tuples written: <span className="font-medium">{event.data.tuples_written as number}</span>
          </div>
          {tuples.length > 0 ? (
            <div className="space-y-1.5">
              {tuples.map((t, i) => (
                <FgaTupleDisplay key={i} tuple={t} />
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap gap-1">
              {(event.data.permissions as string[])?.map((p, i) => (
                <span key={i} className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-xs font-mono">{p}</span>
              ))}
            </div>
          )}
        </div>
      );
    }
    case "discovery_result":
      return (
        <div>
          <div className="text-sm font-semibold text-slate-800 mb-1">
            Resources from <span className="font-mono">{event.data.tool as string}</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {(event.data.resources as Array<{ id: string; name: string }>)?.map((r, i) => (
              <span key={i} className="px-2 py-0.5 rounded bg-cyan-100 text-cyan-800 text-xs">
                {r.name} <span className="text-cyan-500 font-mono text-[10px]">({r.id})</span>
              </span>
            ))}
          </div>
        </div>
      );
    case "name_resolved":
      return (
        <div className="flex items-center gap-2 text-sm font-mono">
          <span className="px-2 py-1 rounded bg-slate-100">{event.data.input as string}</span>
          <ArrowRight className="w-4 h-4 text-green-500" />
          <span className="px-2 py-1 rounded bg-green-100 text-green-800">{event.data.resolved_id as string}</span>
        </div>
      );
    case "fga_write":
    case "fga_delete":
      return (
        <div className="space-y-1.5">
          {(event.data.tuples as Array<{ user: string; relation: string; object: string }>)?.map((t, i) => (
            <FgaTupleDisplay key={i} tuple={t} />
          ))}
        </div>
      );
    case "fga_check": {
      const allowed = event.data.allowed as boolean;
      return (
        <div className="space-y-2">
          <div className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
            allowed ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
          }`}>
            {allowed ? "ALLOWED" : "DENIED"}
          </div>
          <div className="flex items-center gap-1.5 text-xs font-mono">
            <span className="px-1.5 py-0.5 rounded bg-slate-100">{String(event.data.user ?? "")}</span>
            <ArrowRight className="w-3 h-3 text-slate-400" />
            <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px]">can_call</span>
            <ArrowRight className="w-3 h-3 text-slate-400" />
            <span className="px-1.5 py-0.5 rounded bg-slate-100">{String(event.data.object ?? "")}</span>
          </div>
        </div>
      );
    }
    case "fga_batch_check":
      return (
        <div className="space-y-1.5">
          {(event.data.checks as Array<{ object: string; allowed: boolean }>)?.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-xs font-mono py-0.5">
              <span className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold ${
                c.allowed ? "bg-green-100 text-green-700 border-green-200" : "bg-red-100 text-red-700 border-red-200"
              }`}>
                {c.allowed ? "ALLOWED" : "DENIED"}
              </span>
              <span className="px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50">{String(event.data.user ?? "")}</span>
              <ArrowRight className="w-2.5 h-2.5 text-slate-300" />
              <span className="px-1.5 py-0.5 rounded border border-indigo-200 bg-indigo-50 text-indigo-700 text-[10px]">can_call</span>
              <ArrowRight className="w-2.5 h-2.5 text-slate-300" />
              <span className="px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50">{c.object}</span>
            </div>
          ))}
        </div>
      );
    case "tool_call_start":
    case "tool_call_end": {
      // Meta-tools get rich rendering instead of raw JSON
      if (event.data.tool === "get_resource_metadata" && event.data.result) {
        let namespaces: Array<{ name: string; list_tool: string; tool_resources: Record<string, string> }> = [];
        try { namespaces = JSON.parse(String(event.data.result)); } catch { /* use empty */ }
        return <NamespaceList namespaces={namespaces} />;
      }
      return (
        <div className="space-y-3">
          <div>
            <div className="text-sm font-semibold text-slate-800 mb-1">Tool</div>
            <span className="px-2 py-0.5 rounded bg-blue-100 text-blue-800 text-sm font-mono">{event.data.tool as string}</span>
          </div>
          {event.data.args != null && (
            <div>
              <div className="text-sm font-semibold text-slate-800 mb-1">Arguments</div>
              <pre className="text-xs bg-slate-50 rounded p-2 overflow-x-auto font-mono">
                {JSON.stringify(event.data.args as Record<string, unknown>, null, 2)}
              </pre>
            </div>
          )}
          {event.data.result != null && (
            <div>
              <div className="text-sm font-semibold text-slate-800 mb-1">Result</div>
              <pre className="text-xs bg-slate-50 rounded p-2 font-mono max-h-96 overflow-y-auto whitespace-pre-wrap break-words">
                {(() => { try { return JSON.stringify(JSON.parse(String(event.data.result)), null, 2); } catch { return String(event.data.result); } })()}
              </pre>
            </div>
          )}
          {event.data.error != null && (
            <div>
              <div className="text-xs font-medium text-red-500 mb-1">Error</div>
              <pre className="text-xs bg-red-50 rounded p-2 overflow-x-auto font-mono text-red-700">
                {String(event.data.error)}
              </pre>
            </div>
          )}
        </div>
      );
    }
    case "elicitation":
      return (
        <div className="space-y-2">
          <p className="text-sm text-slate-700">{event.data.message as string}</p>
          <div className="flex flex-wrap gap-1">
            {(event.data.options as string[])?.map((o, i) => (
              <span key={i} className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 text-xs">{o}</span>
            ))}
          </div>
        </div>
      );
    case "permission_requested":
      return (
        <div className="space-y-2">
          <div className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
            event.data.status === "granted" ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
          }`}>
            {event.data.status as string}
          </div>
          <div className="flex flex-wrap gap-1">
            {(event.data.permissions as string[])?.map((p, i) => (
              <span key={i} className="px-2 py-0.5 rounded bg-purple-100 text-purple-800 text-xs font-mono">{p}</span>
            ))}
          </div>
          <div className="text-xs text-slate-500">Scope: <span className="font-medium">{event.data.scope as string}</span></div>
        </div>
      );
    case "task_cleanup":
      return (
        <div className="text-sm text-slate-600">
          {(event.data.tuples_deleted as number) || 0} tuples cleaned up for task{" "}
          <span className="font-mono text-xs">{(event.data.task_id as string)?.slice(0, 8)}</span>
        </div>
      );
    default:
      return (
        <pre className="text-xs bg-slate-50 rounded p-2 overflow-auto font-mono">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      );
  }
}

function EventDetailModal({ event, onClose }: { event: ActivityEvent; onClose: () => void }) {
  const config = getEventConfig(event);
  const Icon = config.icon;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Modal header */}
        <div className={`flex items-center gap-3 px-5 py-3 border-b ${config.bgColor} rounded-t-xl`}>
          <Icon className={`w-5 h-5 ${config.color}`} />
          <div className="flex-1 min-w-0">
            <div className={`text-sm font-semibold ${config.color}`}>{config.label}</div>
            <div className="text-[10px] text-slate-400">
              {new Date(event.timestamp * 1000).toLocaleTimeString()}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-white/50 text-slate-400 hover:text-slate-600 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {/* Modal body */}
        <div className="p-5 overflow-y-auto">
          <EventDetailContent event={event} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface SessionFlowDiagramProps {
  events: ActivityEvent[];
  onClose: () => void;
}

export default function SessionFlowDiagram({ events, onClose }: SessionFlowDiagramProps) {
  const rows = useMemo(() => groupIntoRows(events), [events]);
  const [selectedEvent, setSelectedEvent] = useState<ActivityEvent | null>(null);
  const handleSelect = useCallback((e: ActivityEvent) => setSelectedEvent(e), []);

  // Extract prompt from first plan_generated or planning_call event
  const prompt = useMemo(() => {
    for (const e of events) {
      if (e.type === "plan_generated" && e.data.prompt) return e.data.prompt as string;
      if (e.type === "planning_call" && e.data.prompt) return e.data.prompt as string;
    }
    return null;
  }, [events]);

  return (
    <div className="fixed inset-0 z-50 bg-white flex flex-col">
      {/* Header */}
      <div className="flex items-center px-6 py-3 border-b border-slate-200">
        <h2 className="text-xl font-bold text-slate-900">Session Flow</h2>
        <span className="ml-2 text-sm text-slate-600">{events.length} events</span>
        <button
          onClick={onClose}
          className="ml-auto p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Group headers */}
      <div className="grid grid-cols-[0.7fr_2fr_2px_0.8fr_0.8fr] gap-0 px-6 border-b border-slate-200 bg-slate-50">
        <div className="col-span-2 px-4 py-2 text-sm font-bold text-slate-700 uppercase tracking-wider text-center">
          {LANE_GROUPS[0].label}
        </div>
        <div className="bg-slate-400" />
        <div className="col-span-2 px-4 py-2 text-sm font-bold text-slate-700 uppercase tracking-wider text-center">
          {LANE_GROUPS[1].label}
        </div>
      </div>

      {/* Lane headers */}
      <div className="grid grid-cols-[0.7fr_2fr_2px_0.8fr_0.8fr] gap-4 px-6 py-2.5 border-b border-slate-200 bg-white">
        {LANE_GROUPS.flatMap((group, gi) => {
          const items = group.lanes.map((lane) => {
            const Icon = lane.icon;
            return (
              <div key={lane.id} className="flex items-center gap-2 justify-center">
                <Icon className={`w-5 h-5 ${lane.color}`} />
                <span className={`text-sm font-bold ${lane.color}`}>{lane.label}</span>
              </div>
            );
          });
          if (gi === 0) {
            return [...items, <div key="divider" className="bg-slate-300" />];
          }
          return items;
        })}
      </div>

      {/* Scrollable rows */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {prompt && (
          <div className="grid grid-cols-[0.7fr_2fr_2px_0.8fr_0.8fr] gap-4 mb-2">
            <div className="rounded-lg border-2 border-blue-400 bg-blue-50 p-4 text-left">
              <div className="text-xs font-bold text-slate-600 mb-1">User Prompt</div>
              <div className="text-sm text-slate-900">{prompt}</div>
            </div>
            <EmptyCell />
            <div className="bg-slate-300 rounded" />
            <EmptyCell />
            <EmptyCell />
          </div>
        )}
        {rows.map((row, i) =>
          row.isFullWidth ? (
            <div key={i} className="grid grid-cols-[0.7fr_2fr_2px_0.8fr_0.8fr] gap-0 mb-2">
              <FullWidthBanner event={row.intent!} />
            </div>
          ) : (
            <div key={i} className="grid grid-cols-[0.7fr_2fr_2px_0.8fr_0.8fr] gap-4 mb-2">
              <CellContent event={row.agent} lane="agent" onSelect={handleSelect} />
              <CellContent event={row.intent} lane="intent" onSelect={handleSelect} />
              <div className="bg-slate-300 rounded" />
              <CellContent event={row.middleware} lane="middleware" onSelect={handleSelect} />
              <CellContent event={row.tools} lane="tools" onSelect={handleSelect} />
            </div>
          ),
        )}

        {rows.length === 0 && (
          <div className="flex items-center justify-center h-full text-slate-400 text-sm">
            No events yet...
          </div>
        )}
      </div>

      {/* Event detail modal */}
      {selectedEvent && (
        <EventDetailModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  );
}

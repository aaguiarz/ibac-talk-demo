import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  KeyRound,
  ShieldCheck,
  ShieldX,
  Trash2,
  Zap,
  CheckCircle,
  XCircle,
  HelpCircle,
  Ticket,
  ClipboardList,
  Search,
  Link,
  Rocket,
  Sparkles,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  Plug,
  List,
  Brain,
} from "lucide-react";
import type { ActivityEvent as ActivityEventType, FgaTuple } from "../types";

interface ActivityEventProps {
  event: ActivityEventType;
}

interface EventConfig {
  icon: React.ElementType;
  color: string;
  bgColor: string;
  borderColor: string;
  label: string;
}

export function getEventConfig(event: ActivityEventType): EventConfig {
  switch (event.type) {
    case "mcp_connection":
      return {
        icon: Plug,
        color: "text-violet-600",
        bgColor: "bg-violet-50",
        borderColor: "border-l-violet-500",
        label: "MCP Connected",
      };
    case "mcp_tools_listed":
      return {
        icon: List,
        color: "text-violet-600",
        bgColor: "bg-violet-50",
        borderColor: "border-l-violet-500",
        label: "Tools Listed",
      };
    case "planning_call":
      return {
        icon: Brain,
        color: "text-orange-600",
        bgColor: "bg-orange-50",
        borderColor: "border-l-orange-500",
        label: "Planning (Claude API)",
      };
    case "fga_write":
      return {
        icon: KeyRound,
        color: "text-emerald-600",
        bgColor: "bg-emerald-50",
        borderColor: "border-l-emerald-500",
        label: "FGA Write",
      };
    case "fga_check": {
      const allowed = event.data.allowed as boolean;
      return allowed
        ? {
            icon: ShieldCheck,
            color: "text-green-600",
            bgColor: "bg-green-50",
            borderColor: "border-l-green-500",
            label: "FGA Check — Allowed",
          }
        : {
            icon: ShieldX,
            color: "text-orange-600",
            bgColor: "bg-orange-50",
            borderColor: "border-l-orange-500",
            label: "FGA Check — Denied",
          };
    }
    case "fga_batch_check": {
      const checks = (event.data.checks as Array<{ object: string; allowed: boolean }>) || [];
      const allAllowed = checks.every((c) => c.allowed);
      return allAllowed
        ? {
            icon: ShieldCheck,
            color: "text-green-600",
            bgColor: "bg-green-50",
            borderColor: "border-l-green-500",
            label: `Batch Check (${checks.length})`,
          }
        : {
            icon: ShieldX,
            color: "text-orange-600",
            bgColor: "bg-orange-50",
            borderColor: "border-l-orange-500",
            label: `Batch Check (${checks.length})`,
          };
    }
    case "fga_delete":
      return {
        icon: Trash2,
        color: "text-slate-500",
        bgColor: "bg-slate-50",
        borderColor: "border-l-slate-400",
        label: "FGA Delete",
      };
    case "tool_call_end":
    case "tool_call_start": {
      const toolName = event.data.tool as string | undefined;
      // Meta-tools get their own styling
      if (toolName === "get_resource_metadata") {
        return {
          icon: Search,
          color: "text-teal-600",
          bgColor: "bg-teal-50",
          borderColor: "border-l-teal-500",
          label: "Get Resource Metadata",
        };
      }
      const isDone = event.type === "tool_call_end" || (event.data.done as boolean | undefined);
      const hasError = !!event.data.error;
      if (!isDone) {
        return {
          icon: Zap,
          color: "text-blue-600",
          bgColor: "bg-blue-50",
          borderColor: "border-l-blue-500",
          label: "Tool Call",
        };
      }
      return hasError
        ? {
            icon: XCircle,
            color: "text-red-600",
            bgColor: "bg-red-50",
            borderColor: "border-l-red-500",
            label: "Tool Blocked",
          }
        : {
            icon: CheckCircle,
            color: "text-blue-600",
            bgColor: "bg-blue-50",
            borderColor: "border-l-blue-500",
            label: "Tool Result",
          };
    }
    case "elicitation":
      return {
        icon: HelpCircle,
        color: "text-amber-600",
        bgColor: "bg-amber-50",
        borderColor: "border-l-amber-500",
        label: "Elicitation",
      };
    case "permission_requested":
      return {
        icon: Ticket,
        color: "text-purple-600",
        bgColor: "bg-purple-50",
        borderColor: "border-l-purple-500",
        label: "Permission Request",
      };
    case "plan_generated":
      return {
        icon: ClipboardList,
        color: "text-teal-600",
        bgColor: "bg-teal-50",
        borderColor: "border-l-teal-500",
        label: "Generated Plan",
      };
    case "plan_validated":
      return {
        icon: ClipboardList,
        color: "text-teal-600",
        bgColor: "bg-teal-50",
        borderColor: "border-l-teal-500",
        label: "Plan Validated",
      };
    case "discovery_result":
      return {
        icon: Search,
        color: "text-cyan-600",
        bgColor: "bg-cyan-50",
        borderColor: "border-l-cyan-500",
        label: "Discovery Result",
      };
    case "name_resolved":
      return {
        icon: Link,
        color: "text-green-600",
        bgColor: "bg-green-50",
        borderColor: "border-l-green-500",
        label: "Name Resolved",
      };
    case "task_created":
      return {
        icon: Rocket,
        color: "text-slate-600",
        bgColor: "bg-slate-50",
        borderColor: "border-l-slate-400",
        label: "Task Created",
      };
    case "namespaces_fetched":
      return {
        icon: Search,
        color: "text-teal-600",
        bgColor: "bg-teal-50",
        borderColor: "border-l-teal-500",
        label: "Get Resource Metadata",
      };
    case "discovery_authorized":
      return {
        icon: KeyRound,
        color: "text-emerald-600",
        bgColor: "bg-emerald-50",
        borderColor: "border-l-emerald-500",
        label: "FGA Write (Discovery)",
      };
    case "actions_authorized":
      return {
        icon: KeyRound,
        color: "text-emerald-600",
        bgColor: "bg-emerald-50",
        borderColor: "border-l-emerald-500",
        label: "FGA Write (Actions)",
      };
    case "task_cleanup":
      return {
        icon: Sparkles,
        color: "text-slate-500",
        bgColor: "bg-slate-50",
        borderColor: "border-l-slate-400",
        label: "Task Cleanup",
      };
    case "flow_section":
      return {
        icon: ArrowRight,
        color: "text-slate-800",
        bgColor: "bg-slate-100",
        borderColor: "border-l-slate-600",
        label: (event.data.section as string) || "Section",
      };
    case "flow_status":
      return {
        icon: ArrowRight,
        color: "text-indigo-600",
        bgColor: "bg-indigo-50",
        borderColor: "border-l-indigo-500",
        label: `${(event.data.phase as string) || "unknown"}`,
      };
    default:
      return {
        icon: Zap,
        color: "text-slate-500",
        bgColor: "bg-slate-50",
        borderColor: "border-l-slate-300",
        label: event.type,
      };
  }
}

function formatRelativeTime(timestamp: number): string {
  const diff = Math.floor(Date.now() / 1000 - timestamp);
  if (diff < 1) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return new Date(timestamp * 1000).toLocaleTimeString();
}

function FgaTupleRow({ tuple }: { tuple: FgaTuple }) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-mono py-0.5 flex-wrap">
      <span className="px-1.5 py-0.5 rounded bg-white/80 text-slate-700 border border-slate-200">
        {tuple.user}
      </span>
      <span className="text-slate-400">
        <ArrowRight className="w-3 h-3 inline" />
      </span>
      <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200 text-[10px]">
        {tuple.relation}
      </span>
      <span className="text-slate-400">
        <ArrowRight className="w-3 h-3 inline" />
      </span>
      <span className="px-1.5 py-0.5 rounded bg-white/80 text-slate-700 border border-slate-200">
        {tuple.object}
      </span>
    </div>
  );
}

export default function ActivityEventCard({ event }: ActivityEventProps) {
  const [expanded, setExpanded] = useState(false);
  const config = getEventConfig(event);
  const Icon = config.icon;

  const renderSummary = () => {
    switch (event.type) {
      case "mcp_connection":
        return (
          <span className="text-xs text-slate-500">
            {String(event.data.server ?? "").split("/").pop()}
          </span>
        );
      case "mcp_tools_listed":
        return (
          <span className="text-xs text-slate-500">
            {event.data.count as number} tools available
          </span>
        );
      case "planning_call":
        return (
          <span className="text-xs text-slate-500">
            Calling <span className="font-mono">{event.data.model as string}</span> with{" "}
            {(event.data.tools_provided as string[])?.length || 0} tool descriptions
          </span>
        );
      case "task_created":
        return (
          <span className="font-mono text-xs text-slate-500">
            {(event.data.task_id as string)?.slice(0, 8)}...
          </span>
        );
      case "flow_status":
        return (
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              event.data.phase === "complete"
                ? "bg-emerald-100 text-emerald-700"
                : event.data.phase === "error"
                  ? "bg-red-100 text-red-700"
                  : "bg-indigo-100 text-indigo-700"
            }`}
          >
            {event.data.phase as string}
          </span>
        );
      case "tool_call_start": {
        const tcDone = event.data.done as boolean | undefined;
        const tcError = event.data.error as string | undefined;
        return (
          <span className="flex items-center gap-1.5">
            <span className="font-mono text-xs text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded">
              {event.data.tool as string}
            </span>
            {tcDone && !tcError && (
              <CheckCircle className="w-3 h-3 text-green-500" />
            )}
            {tcError && (
              <XCircle className="w-3 h-3 text-red-500" />
            )}
            {!tcDone && (
              <span className="w-3 h-3 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
            )}
          </span>
        );
      }
      case "plan_generated":
        return (
          <span className="text-xs text-slate-500">
            {(event.data.actions as string[])?.length || 0} actions
            {(event.data.derived_discovery as string[])?.length
              ? `, ${(event.data.derived_discovery as string[]).length} discovery (derived)`
              : ""}
            {(event.data.denied_implicit as unknown[])?.length
              ? `, ${(event.data.denied_implicit as unknown[]).length} denied`
              : ""}
          </span>
        );
      case "discovery_result":
        return (
          <span className="text-xs text-slate-500">
            {(event.data.resources as unknown[])?.length || 0} resources from{" "}
            <span className="font-mono">{event.data.tool as string}</span>
          </span>
        );
      case "name_resolved":
        return (
          <span className="text-xs font-mono">
            {event.data.input as string}{" "}
            <ArrowRight className="w-3 h-3 inline text-green-500" />{" "}
            {event.data.resolved_id as string}
          </span>
        );
      case "fga_batch_check": {
        const batchChecks = (event.data.checks as Array<{ object: string; allowed: boolean }>) || [];
        const allowed = batchChecks.filter((c) => c.allowed).length;
        const denied = batchChecks.length - allowed;
        return (
          <span className="text-xs text-slate-500">
            {allowed} allowed{denied > 0 ? `, ${denied} denied` : ""}
          </span>
        );
      }
      case "fga_write":
        return (
          <span className="text-xs text-slate-500">
            {(event.data.tuples as FgaTuple[])?.length || 0} tuple(s)
          </span>
        );
      case "fga_delete":
        return (
          <span className="text-xs text-slate-500">
            {(event.data.count as number) || 0} tuple(s) deleted
          </span>
        );
      case "permission_requested":
        return (
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              event.data.status === "granted"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            {event.data.status as string}
          </span>
        );
      case "task_cleanup":
        return (
          <span className="text-xs text-slate-500">
            {(event.data.tuples_deleted as number) || 0} tuples cleaned up
          </span>
        );
      case "elicitation":
        return (
          <span className="text-xs text-slate-500 truncate max-w-[200px] inline-block align-bottom">
            {event.data.message as string}
          </span>
        );
      default:
        return null;
    }
  };

  const renderDetails = () => {
    switch (event.type) {
      case "mcp_connection":
        return (
          <div className="text-xs text-slate-600 font-mono">
            {String(event.data.server ?? "")}
          </div>
        );
      case "mcp_tools_listed":
        return (
          <div className="flex flex-wrap gap-1">
            {(event.data.tools as string[])?.map((t, i) => (
              <span key={i} className="px-2 py-0.5 rounded bg-violet-100 text-violet-800 text-xs font-mono">
                {t}
              </span>
            ))}
          </div>
        );
      case "planning_call":
        return (
          <div className="space-y-2">
            <div>
              <div className="text-xs font-medium text-slate-700 mb-1">User Prompt</div>
              <div className="text-xs bg-white/70 rounded p-2 font-mono">
                {String(event.data.prompt ?? "")}
              </div>
            </div>
            <div>
              <div className="text-xs font-medium text-slate-700 mb-1">Tool Descriptions Sent</div>
              <div className="flex flex-wrap gap-1">
                {(event.data.tools_provided as string[])?.map((t, i) => (
                  <span key={i} className="px-2 py-0.5 rounded bg-orange-100 text-orange-800 text-xs font-mono">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
        );
      case "fga_batch_check":
        return (
          <div className="space-y-1">
            {(event.data.checks as Array<{ object: string; allowed: boolean }>)?.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs font-mono py-0.5">
                <span className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold ${
                  c.allowed
                    ? "bg-green-100 text-green-700 border-green-200"
                    : "bg-red-100 text-red-700 border-red-200"
                }`}>
                  {c.allowed ? "ALLOWED" : "DENIED"}
                </span>
                <span className="px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-700">
                  {String(event.data.user ?? "")}
                </span>
                <ArrowRight className="w-2.5 h-2.5 text-slate-300" />
                <span className="px-1.5 py-0.5 rounded border border-indigo-200 bg-indigo-50 text-indigo-700 text-[10px]">
                  can_call
                </span>
                <ArrowRight className="w-2.5 h-2.5 text-slate-300" />
                <span className="px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-700">
                  {c.object}
                </span>
              </div>
            ))}
          </div>
        );
      case "fga_write":
      case "fga_delete":
        return (
          <div className="space-y-1">
            {(event.data.tuples as FgaTuple[])?.map((t, i) => (
              <FgaTupleRow key={i} tuple={t} />
            ))}
          </div>
        );
      case "plan_generated":
        return (
          <div className="space-y-3">
            {(event.data.derived_discovery as string[])?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-slate-700 mb-1">
                  Tools to discover Resource IDs
                </div>
                <div className="flex flex-wrap gap-1">
                  {(event.data.derived_discovery as string[])?.map((d, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 rounded bg-cyan-100 text-cyan-800 text-xs font-mono"
                    >
                      {d.endsWith(":*") ? d.slice(0, -2) : d}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div>
              <div className="text-xs font-medium text-slate-700 mb-1">
                Intent-aligned actions identified by trusted LLM
              </div>
              <div className="flex flex-wrap gap-1">
                {(event.data.actions as string[])?.map((a, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded bg-purple-100 text-purple-800 text-xs font-mono"
                  >
                    {a}
                  </span>
                ))}
              </div>
            </div>
            {(event.data.denied_implicit as Array<{tool: string; reason: string}>)?.length > 0 && (
              <div>
                <div className="text-xs font-medium text-slate-700 mb-1">
                  Actions not aligned with intent
                </div>
                <div className="space-y-1">
                  {(event.data.denied_implicit as Array<{tool: string; reason: string}>).map((d, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="px-2 py-0.5 rounded bg-red-100 text-red-800 text-xs font-mono shrink-0">
                        {d.tool}
                      </span>
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
          <div className="flex flex-wrap gap-1">
            {(event.data.actions as string[])?.map((a, i) => (
              <span
                key={i}
                className="px-2 py-0.5 rounded bg-purple-100 text-purple-800 text-xs font-mono"
              >
                {a}
              </span>
            ))}
          </div>
        );
      case "discovery_result":
        return (
          <div className="flex flex-wrap gap-1">
            {(
              event.data.resources as Array<{ id: string; name: string }>
            )?.map((r, i) => (
              <span
                key={i}
                className="px-2 py-0.5 rounded bg-cyan-100 text-cyan-800 text-xs"
              >
                {r.name}{" "}
                <span className="text-cyan-500 font-mono text-[10px]">
                  ({r.id})
                </span>
              </span>
            ))}
          </div>
        );
      case "tool_call_start":
        return (
          <div className="space-y-2">
            <div>
              <div className="text-xs font-medium text-slate-700 mb-1">
                Arguments
              </div>
              <pre className="text-xs bg-white/70 rounded p-2 overflow-x-auto font-mono">
                {JSON.stringify(event.data.args, null, 2)}
              </pre>
            </div>
            {event.data.result ? (
              <div>
                <div className="text-xs font-medium text-slate-700 mb-1">
                  Result
                </div>
                <pre className="text-xs bg-white/70 rounded p-2 font-mono max-h-96 overflow-y-auto whitespace-pre-wrap break-words">
                  {(() => { try { return JSON.stringify(JSON.parse(String(event.data.result)), null, 2); } catch { return String(event.data.result); } })()}
                </pre>
              </div>
            ) : null}
            {event.data.error ? (
              <div>
                <div className="text-xs font-medium text-red-500 mb-1">
                  Error
                </div>
                <pre className="text-xs bg-red-100/70 rounded p-2 overflow-x-auto font-mono text-red-700">
                  {String(event.data.error)}
                </pre>
              </div>
            ) : null}
          </div>
        );
      case "permission_requested":
        return (
          <div className="space-y-1">
            <div className="flex flex-wrap gap-1">
              {(event.data.permissions as string[])?.map((p, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded bg-purple-100 text-purple-800 text-xs font-mono"
                >
                  {p}
                </span>
              ))}
            </div>
            <div className="text-xs text-slate-500">
              Scope:{" "}
              <span className="font-medium">
                {event.data.scope as string}
              </span>
            </div>
          </div>
        );
      case "elicitation":
        return (
          <div className="space-y-2">
            <p className="text-xs text-slate-700">
              {event.data.message as string}
            </p>
            <div className="flex flex-wrap gap-1">
              {(event.data.options as string[])?.map((o, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 text-xs"
                >
                  {o}
                </span>
              ))}
            </div>
          </div>
        );
      default:
        return (
          <pre className="text-xs bg-white/70 rounded p-2 overflow-x-auto font-mono">
            {JSON.stringify(event.data, null, 2)}
          </pre>
        );
    }
  };

  // Flow section events render as prominent section headers
  if (event.type === "flow_section") {
    return (
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.2 }}
        className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-slate-800 text-white mt-1"
      >
        <Icon className="w-4 h-4" />
        <span className="text-sm font-bold tracking-wide">
          {event.data.section as string}
        </span>
        <div className="flex-1 h-px bg-slate-600" />
        <span className="text-[10px] text-slate-400" title={new Date(event.timestamp * 1000).toLocaleTimeString()}>
          {formatRelativeTime(event.timestamp)}
        </span>
      </motion.div>
    );
  }

  // Flow status events render as full-width phase banners
  if (event.type === "flow_status") {
    return (
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.2 }}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg ${config.bgColor}`}
      >
        <Icon className={`w-3.5 h-3.5 ${config.color}`} />
        <span className={`text-xs font-semibold uppercase tracking-wider ${config.color}`}>
          {event.data.phase as string}
        </span>
        <div className="flex-1 h-px bg-indigo-200/50" />
        <span className="text-[10px] text-slate-400" title={new Date(event.timestamp * 1000).toLocaleTimeString()}>
          {formatRelativeTime(event.timestamp)}
        </span>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
      className="relative pl-6"
    >
      {/* Timeline connector */}
      <div className="absolute left-2 top-0 bottom-0 w-px bg-slate-200" />
      <div
        className={`absolute left-0.5 top-3 w-3 h-3 rounded-full border-2 border-white ${config.bgColor}`}
      />

      <div
        className={`rounded-lg border border-l-4 ${config.borderColor} ${config.bgColor} overflow-hidden`}
      >
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/30 transition-colors"
        >
          <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${config.color}`} />
          <span className="text-xs font-medium text-slate-700">
            {config.label}
          </span>
          <span className="flex-1">{renderSummary()}</span>
          <span
            className="text-[10px] text-slate-400 flex-shrink-0"
            title={new Date(event.timestamp * 1000).toLocaleTimeString()}
          >
            {formatRelativeTime(event.timestamp)}
          </span>
          {expanded ? (
            <ChevronDown className="w-3 h-3 text-slate-400 flex-shrink-0" />
          ) : (
            <ChevronRight className="w-3 h-3 text-slate-400 flex-shrink-0" />
          )}
        </button>

        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden"
            >
              <div className="px-3 pb-2 border-t border-slate-100">
                <div className="pt-2">{renderDetails()}</div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

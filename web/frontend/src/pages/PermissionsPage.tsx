import React, { useCallback, useEffect, useState } from "react";
import {
  KeyRound,
  Trash2,
  RefreshCw,
  ArrowRight,
  X,
  FileCode,
} from "lucide-react";

interface FgaTuple {
  user: string;
  relation: string;
  object: string;
}

const RELATION_COLORS: Record<string, string> = {
  can_call_task: "bg-amber-100 text-amber-800 border-amber-200",
  can_call_session: "bg-blue-100 text-blue-800 border-blue-200",
  can_call_always: "bg-emerald-100 text-emerald-800 border-emerald-200",
  parent_tool: "bg-slate-100 text-slate-600 border-slate-200",
  member: "bg-slate-100 text-slate-600 border-slate-200",
  session: "bg-slate-100 text-slate-600 border-slate-200",
  user: "bg-purple-100 text-purple-600 border-purple-200",
  agent: "bg-purple-100 text-purple-600 border-purple-200",
};

// Simple syntax highlighting for .fga model files
function highlightFga(source: string): React.ReactNode[] {
  return source.split("\n").map((line, i) => {
    let highlighted: React.ReactNode;

    if (line.trimStart().startsWith("#")) {
      highlighted = <span className="text-slate-400 italic">{line}</span>;
    } else if (/^\s*(type|model|schema)\b/.test(line)) {
      const match = line.match(/^(\s*)(type|model|schema)(\s+)(\S+)?(.*)$/);
      if (match) {
        highlighted = (
          <>
            {match[1]}
            <span className="text-indigo-600 font-semibold">{match[2]}</span>
            {match[3]}
            {match[4] && (
              <span className="text-amber-700 font-semibold">{match[4]}</span>
            )}
            {match[5] && <span>{match[5]}</span>}
          </>
        );
      } else {
        highlighted = <span>{line}</span>;
      }
    } else if (/^\s*(define|relations)\b/.test(line)) {
      const match = line.match(
        /^(\s*)(define|relations)(\s*)(\S+)?(.*)$/,
      );
      if (match) {
        highlighted = (
          <>
            {match[1]}
            <span className="text-purple-600 font-semibold">{match[2]}</span>
            {match[3]}
            {match[4] && (
              <span className="text-teal-700 font-medium">{match[4]}</span>
            )}
            {match[5] && highlightKeywords(match[5])}
          </>
        );
      } else {
        highlighted = <span>{line}</span>;
      }
    } else {
      highlighted = <>{highlightKeywords(line)}</>;
    }

    return (
      <div key={i} className="leading-6">
        <span className="inline-block w-8 text-right text-slate-300 select-none mr-4 text-xs">
          {i + 1}
        </span>
        {highlighted}
      </div>
    );
  });
}

function highlightKeywords(text: string): React.ReactNode {
  const parts = text.split(
    /\b(or|and|from|task|session|agent_user|agent|user|tool|tool_resource|project|issue)\b/g,
  );
  return (
    <>
      {parts.map((part, i) => {
        if (
          [
            "task",
            "session",
            "agent_user",
            "agent",
            "user",
            "tool",
            "tool_resource",
            "project",
            "issue",
          ].includes(part)
        ) {
          return (
            <span key={i} className="text-amber-700">
              {part}
            </span>
          );
        }
        if (["or", "and", "from"].includes(part)) {
          return (
            <span key={i} className="text-rose-500 font-medium">
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

export default function PermissionsPage() {
  const [model, setModel] = useState("");
  const [tuples, setTuples] = useState<FgaTuple[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchModel = useCallback(async () => {
    try {
      const resp = await fetch("/api/permissions/model");
      if (resp.ok) setModel(await resp.text());
    } catch {
      /* ignore */
    }
  }, []);

  const fetchTuples = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch("/api/permissions");
      if (resp.ok) setTuples(await resp.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModel();
    fetchTuples();
    const interval = setInterval(fetchTuples, 5000);
    return () => clearInterval(interval);
  }, [fetchModel, fetchTuples]);

  const deleteTuple = useCallback(async (tuple: FgaTuple) => {
    try {
      await fetch("/api/permissions/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(tuple),
      });
      setTuples((prev) =>
        prev.filter(
          (t) =>
            t.user !== tuple.user ||
            t.relation !== tuple.relation ||
            t.object !== tuple.object,
        ),
      );
    } catch {
      /* ignore */
    }
  }, []);

  const resetAll = useCallback(async () => {
    try {
      await fetch("/api/permissions/reset", { method: "POST" });
      setTuples([]);
    } catch {
      /* ignore */
    }
  }, []);

  const grantTuples = tuples.filter((t) => t.relation.startsWith("can_call"));
  const structuralTuples = tuples.filter(
    (t) => !t.relation.startsWith("can_call"),
  );

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-6 py-3 border-b border-slate-200 bg-white">
        <h2 className="text-base font-semibold text-slate-900">
          Manage Permissions
        </h2>
        <p className="text-sm text-slate-500">
          Authorization model and live OpenFGA tuples
        </p>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left: Authorization Model */}
        <div className="w-[50%] border-r border-slate-200 flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 bg-white">
            <FileCode className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-700">
              authorization/model.fga
            </h3>
          </div>
          <div className="flex-1 overflow-y-auto bg-slate-50 p-4">
            <pre className="text-xs font-mono leading-relaxed">
              {model ? highlightFga(model) : (
                <span className="text-slate-400">Loading model...</span>
              )}
            </pre>
          </div>
        </div>

        {/* Right: Tuples */}
        <div className="w-[50%] flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 bg-white">
            <KeyRound className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-700">
              OpenFGA Tuples
            </h3>
            <span className="text-xs text-slate-400">({tuples.length})</span>
            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={fetchTuples}
                disabled={loading}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                title="Refresh"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}
                />
              </button>
              <button
                onClick={resetAll}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-red-600 hover:bg-red-50 border border-red-200 transition-colors"
              >
                <Trash2 className="w-3 h-3" />
                Reset All
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto bg-white">
            {tuples.length === 0 && (
              <div className="flex items-center justify-center h-full text-sm text-slate-400">
                {loading ? "Loading tuples..." : "No tuples found"}
              </div>
            )}

            {grantTuples.length > 0 && (
              <div className="px-3 pt-3 pb-1">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 px-1 mb-2">
                  Permission Grants ({grantTuples.length})
                </div>
                <div className="space-y-1">
                  {grantTuples.map((t, i) => (
                    <TupleRow
                      key={`grant-${i}`}
                      tuple={t}
                      onDelete={deleteTuple}
                    />
                  ))}
                </div>
              </div>
            )}

            {structuralTuples.length > 0 && (
              <div className="px-3 pt-3 pb-3">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 px-1 mb-2">
                  Structural Tuples ({structuralTuples.length})
                </div>
                <div className="space-y-1">
                  {structuralTuples.map((t, i) => (
                    <TupleRow
                      key={`struct-${i}`}
                      tuple={t}
                      onDelete={deleteTuple}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TupleRow({
  tuple,
  onDelete,
}: {
  tuple: FgaTuple;
  onDelete: (t: FgaTuple) => void;
}) {
  const relationColor =
    RELATION_COLORS[tuple.relation] ||
    "bg-slate-100 text-slate-600 border-slate-200";

  return (
    <div className="group flex items-center gap-1 px-2 py-1.5 rounded-lg hover:bg-slate-50 transition-colors text-[11px] font-mono">
      <span
        className="px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-700 truncate max-w-[130px]"
        title={tuple.user}
      >
        {tuple.user}
      </span>
      <ArrowRight className="w-2.5 h-2.5 text-slate-300 flex-shrink-0" />
      <span
        className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold flex-shrink-0 ${relationColor}`}
      >
        {tuple.relation}
      </span>
      <ArrowRight className="w-2.5 h-2.5 text-slate-300 flex-shrink-0" />
      <span
        className="px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-700 truncate flex-1 min-w-0"
        title={tuple.object}
      >
        {tuple.object}
      </span>
      <button
        onClick={() => onDelete(tuple)}
        className="p-1 rounded text-slate-300 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-50 transition-all flex-shrink-0"
        title="Delete tuple"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

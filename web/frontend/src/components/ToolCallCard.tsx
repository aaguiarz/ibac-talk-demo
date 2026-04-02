import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Zap,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  XCircle,
  Loader2,
} from "lucide-react";
import type { ToolCall } from "../types";

interface ToolCallCardProps {
  toolCall: ToolCall;
}

export default function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasError = !!toolCall.error;

  return (
    <div
      className={`mt-2 rounded-lg border text-sm overflow-hidden ${
        hasError
          ? "border-red-200 bg-red-50"
          : "border-blue-200 bg-blue-50"
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-blue-100/50 transition-colors"
      >
        {!toolCall.done ? (
          <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />
        ) : hasError ? (
          <XCircle className="w-3.5 h-3.5 text-red-500" />
        ) : (
          <CheckCircle className="w-3.5 h-3.5 text-blue-500" />
        )}

        <Zap className="w-3.5 h-3.5 text-blue-600" />
        <span className="font-mono font-medium text-blue-800">
          {toolCall.tool}
        </span>

        <span className="ml-auto">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
          )}
        </span>
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
            <div className="px-3 pb-2 space-y-2 border-t border-blue-100">
              <div>
                <div className="text-xs font-medium text-slate-500 mt-2 mb-1">
                  Arguments
                </div>
                <pre className="text-xs bg-white/70 rounded p-2 overflow-x-auto font-mono">
                  {JSON.stringify(toolCall.args, null, 2)}
                </pre>
              </div>

              {toolCall.result && (
                <div>
                  <div className="text-xs font-medium text-slate-500 mb-1">
                    Result
                  </div>
                  <pre className="text-xs bg-white/70 rounded p-2 font-mono max-h-96 overflow-y-auto whitespace-pre-wrap break-words">
                    {(() => { try { return JSON.stringify(JSON.parse(String(toolCall.result)), null, 2); } catch { return toolCall.result; } })()}
                  </pre>
                </div>
              )}

              {toolCall.error && (
                <div>
                  <div className="text-xs font-medium text-red-500 mb-1">
                    Error
                  </div>
                  <pre className="text-xs bg-red-100/70 rounded p-2 overflow-x-auto font-mono text-red-700">
                    {toolCall.error}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

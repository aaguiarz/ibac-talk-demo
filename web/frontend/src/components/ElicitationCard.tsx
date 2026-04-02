import { motion } from "framer-motion";
import { HelpCircle } from "lucide-react";
import type { ElicitationData } from "../types";

interface ElicitationCardProps {
  elicitation: ElicitationData;
  onRespond: (id: string, value: string) => void;
}

const SCOPE_COLORS: Record<string, string> = {
  "Allow once":
    "bg-amber-50 border-amber-200 text-amber-800 hover:bg-amber-100",
  "Allow for this session":
    "bg-blue-50 border-blue-200 text-blue-800 hover:bg-blue-100",
  "Always allow":
    "bg-emerald-50 border-emerald-200 text-emerald-800 hover:bg-emerald-100",
  "Do not allow": "bg-red-50 border-red-200 text-red-800 hover:bg-red-100",
};

export default function ElicitationCard({
  elicitation,
  onRespond,
}: ElicitationCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="rounded-xl border border-amber-200 bg-gradient-to-b from-amber-50 to-white p-4 shadow-sm"
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center">
          <HelpCircle className="w-4 h-4 text-amber-600" />
        </div>
        <div className="flex-1 space-y-3">
          <p className="text-sm text-slate-800 font-medium">
            {elicitation.message}
          </p>
          <div className="flex flex-wrap gap-2">
            {elicitation.options.map((option) => (
              <button
                key={option}
                onClick={() => onRespond(elicitation.id, option)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                  SCOPE_COLORS[option] ||
                  "bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

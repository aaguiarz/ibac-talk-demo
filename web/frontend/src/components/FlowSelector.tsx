import { Shield, Search, Zap, KeyRound } from "lucide-react";
import type { TabType } from "../types";

type TabDef = { id: TabType; label: string; description: string; icon: typeof Shield };

const flowTabs: TabDef[] = [
  {
    id: "regular",
    label: "Regular Agent",
    description: "Inline elicitation",
    icon: Shield,
  },
  {
    id: "intention_discovery",
    label: "Intention Discovery",
    description: "Plan, discover, authorize",
    icon: Search,
  },
  {
    id: "autonomous",
    label: "Autonomous",
    description: "Auto-grant permissions",
    icon: Zap,
  },
];

const permissionsTab: TabDef = {
  id: "permissions",
  label: "Manage Permissions",
  description: "Model & FGA tuples",
  icon: KeyRound,
};

interface FlowSelectorProps {
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
}

export default function FlowSelector({ activeTab, onSelectTab }: FlowSelectorProps) {
  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3">
      <div className="flex items-center gap-8">
        <div className="flex items-center gap-2 flex-shrink-0">
          <Shield className="w-5 h-5 text-indigo-600" />
          <h1 className="text-lg font-semibold text-slate-900">
            Agent Authorization Demo
          </h1>
        </div>

        <nav className="flex gap-1 flex-1">
          {flowTabs.map(({ id, label, description, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onSelectTab(id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === id
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`}
            >
              <Icon className="w-4 h-4" />
              <div className="text-left">
                <div>{label}</div>
                <div className="text-xs font-normal text-slate-500">
                  {description}
                </div>
              </div>
            </button>
          ))}

          <button
            onClick={() => onSelectTab(permissionsTab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ml-auto ${
              activeTab === permissionsTab.id
                ? "bg-indigo-50 text-indigo-700"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            <permissionsTab.icon className="w-4 h-4" />
            <div className="text-left">
              <div>{permissionsTab.label}</div>
              <div className="text-xs font-normal text-slate-500">
                {permissionsTab.description}
              </div>
            </div>
          </button>
        </nav>
      </div>
    </header>
  );
}

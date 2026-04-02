import { useState } from "react";
import FlowSelector from "./components/FlowSelector";
import FlowPage from "./pages/FlowPage";
import PermissionsPage from "./pages/PermissionsPage";
import { useFlowSession } from "./hooks/useFlowSession";
import type { FlowType, TabType } from "./types";

const FLOW_DESCRIPTIONS: Record<FlowType, { name: string; description: string }> = {
  regular: {
    name: "Regular Agent",
    description:
      "The agent runs freely. The middleware elicits permission inline when the agent tries to use a tool/resource that hasn't been authorized yet.",
  },
  intention_discovery: {
    name: "Intention Discovery",
    description:
      "Plan permissions from the prompt, discover available resources, resolve resource IDs, request authorization, then execute. Full visibility into each phase.",
  },
  autonomous: {
    name: "Autonomous Agent",
    description:
      "Plan permissions, discover resources, auto-grant task-scoped FGA tuples (no human prompt), then execute.",
  },
};

const FLOW_TYPES: FlowType[] = ["regular", "intention_discovery", "autonomous"];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabType>("regular");

  const regular = useFlowSession("regular");
  const intentionDiscovery = useFlowSession("intention_discovery");
  const autonomous = useFlowSession("autonomous");

  const sessions: Record<FlowType, ReturnType<typeof useFlowSession>> = {
    regular,
    intention_discovery: intentionDiscovery,
    autonomous,
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <FlowSelector activeTab={activeTab} onSelectTab={setActiveTab} />
      <main className="flex-1 flex flex-col relative">
        {/* Flow tabs */}
        {FLOW_TYPES.map((flowType) => {
          const session = sessions[flowType];
          const meta = FLOW_DESCRIPTIONS[flowType];
          return (
            <div
              key={flowType}
              className={`flex-1 flex flex-col ${activeTab === flowType ? "" : "hidden"}`}
            >
              <FlowPage
                flowName={meta.name}
                flowDescription={meta.description}
                session={session}
              />
            </div>
          );
        })}

        {/* Permissions tab */}
        <div className={`flex-1 flex flex-col ${activeTab === "permissions" ? "" : "hidden"}`}>
          <PermissionsPage />
        </div>
      </main>
    </div>
  );
}

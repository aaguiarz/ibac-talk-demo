import type { ReactNode } from "react";

interface DemoLayoutProps {
  flowName: string;
  flowDescription: string;
  chatPanel: ReactNode;
  activityPanel: ReactNode;
}

export default function DemoLayout({
  flowName,
  flowDescription,
  chatPanel,
  activityPanel,
}: DemoLayoutProps) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-6 py-3 border-b border-slate-200 bg-white">
        <h2 className="text-base font-semibold text-slate-900">{flowName}</h2>
        <p className="text-sm text-slate-500">{flowDescription}</p>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Chat Panel — 55% */}
        <div className="w-[55%] border-r border-slate-200 flex flex-col overflow-hidden">
          {chatPanel}
        </div>

        {/* Activity Panel — 45% */}
        <div className="w-[45%] flex flex-col overflow-hidden">
          {activityPanel}
        </div>
      </div>
    </div>
  );
}

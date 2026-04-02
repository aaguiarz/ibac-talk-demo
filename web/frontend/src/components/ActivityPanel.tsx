import { useEffect, useRef } from "react";
import { Activity, Maximize2 } from "lucide-react";
import type { ActivityEvent as ActivityEventType } from "../types";
import ActivityEventCard from "./ActivityEvent";

interface ActivityPanelProps {
  events: ActivityEventType[];
  onExpand?: () => void;
}

export default function ActivityPanel({ events, onExpand }: ActivityPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="flex-1 flex flex-col bg-white">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
        <Activity className="w-4 h-4 text-slate-500" />
        <h3 className="text-sm font-semibold text-slate-700">Activity Log</h3>
        <span className="ml-auto text-xs text-slate-400">
          {events.length} events
        </span>
        {onExpand && (
          <button
            onClick={onExpand}
            className="ml-2 p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
            title="Expand to flow diagram"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-2">
        {events.length === 0 && (
          <div className="flex items-center justify-center h-full text-slate-400 text-sm">
            Events will appear here...
          </div>
        )}

        {events.map((event) => (
          <ActivityEventCard key={event.id} event={event} />
        ))}
      </div>
    </div>
  );
}

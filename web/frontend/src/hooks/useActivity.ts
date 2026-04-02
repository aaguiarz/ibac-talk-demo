import { useCallback, useState } from "react";
import type { ActivityEvent, ActivityEventType, ServerEvent } from "../types";

let eventCounter = 0;

const ACTIVITY_EVENT_TYPES = new Set<string>([
  "task_created",
  "mcp_connection",
  "mcp_tools_listed",
  "planning_call",
  "plan_generated",
  "plan_validated",
  "discovery_result",
  "name_resolved",
  "fga_write",
  "fga_check",
  "fga_batch_check",
  "fga_delete",
  "tool_call_start",
  "tool_call_end",
  "elicitation",
  "permission_requested",
  "task_cleanup",
  "namespaces_fetched",
  "discovery_authorized",
  "actions_authorized",
  "flow_section",
  "flow_status",
]);

export function useActivity() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);

  const handleEvent = useCallback((event: ServerEvent) => {
    if (!ACTIVITY_EVENT_TYPES.has(event.type)) return;

    // Merge tool_call_end into the existing tool_call_start event
    if (event.type === "tool_call_end") {
      const endData = event.data as { id: string; result?: string; error?: string };
      setEvents((prev) =>
        prev.map((e) => {
          if (
            e.type === "tool_call_start" &&
            (e.data.id as string) === endData.id
          ) {
            return {
              ...e,
              data: {
                ...e.data,
                result: endData.result,
                error: endData.error,
                done: true,
              },
            };
          }
          return e;
        }),
      );
      return;
    }

    const activityEvent: ActivityEvent = {
      id: `evt_${++eventCounter}`,
      type: event.type as ActivityEventType,
      data: event.data,
      timestamp: event.timestamp,
    };

    setEvents((prev) => [...prev, activityEvent]);
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  return { events, handleEvent, clearEvents };
}

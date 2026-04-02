// Shared TypeScript types mirroring backend event protocol

export interface ServerEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

// Chat types
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCall[];
  elicitation?: ElicitationData;
}

export interface ToolCall {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: string;
  error?: string;
  done: boolean;
}

export interface ElicitationData {
  id: string;
  message: string;
  options: string[];
  responded?: boolean;
  selectedValue?: string;
}

// Activity types
export type ActivityEventType =
  | "task_created"
  | "mcp_connection"
  | "mcp_tools_listed"
  | "planning_call"
  | "plan_generated"
  | "plan_validated"
  | "discovery_result"
  | "name_resolved"
  | "fga_write"
  | "fga_check"
  | "fga_batch_check"
  | "fga_delete"
  | "tool_call_start"
  | "tool_call_end"
  | "elicitation"
  | "permission_requested"
  | "task_cleanup"
  | "namespaces_fetched"
  | "discovery_authorized"
  | "actions_authorized"
  | "flow_section"
  | "flow_status";

export interface ActivityEvent {
  id: string;
  type: ActivityEventType;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface FgaTuple {
  user: string;
  relation: string;
  object: string;
}

export type FlowType = "regular" | "intention_discovery" | "autonomous";

export type TabType = FlowType | "permissions";

export type LaneId = "agent" | "intent" | "middleware" | "tools";

export type FlowPhase =
  | "connecting"
  | "planning"
  | "discovery"
  | "authorization"
  | "executing"
  | "cleanup"
  | "complete"
  | "error";

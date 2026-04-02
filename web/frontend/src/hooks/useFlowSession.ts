import { useCallback, useRef } from "react";
import { useWebSocket } from "./useWebSocket";
import { useChat } from "./useChat";
import { useActivity } from "./useActivity";
import type { FlowType, ServerEvent } from "../types";

const SUGGESTED_PROMPT =
  "Summarize the MCP Dev Talk project and post it to #private-team-channel";

export function useFlowSession(flowType: FlowType) {
  const chat = useChat();
  const activity = useActivity();
  const handlersRef = useRef({ chat, activity });
  handlersRef.current = { chat, activity };

  const onMessage = useCallback((event: ServerEvent) => {
    handlersRef.current.chat.handleEvent(event);
    handlersRef.current.activity.handleEvent(event);
  }, []);

  const ws = useWebSocket({ flowType, onMessage });

  const handleSendPrompt = useCallback(
    (prompt: string) => {
      chat.sendPrompt(prompt);
      ws.connect();
      ws.send({ action: "start", prompt });
    },
    [ws, chat],
  );

  const handleRespondElicitation = useCallback(
    (id: string, value: string) => {
      ws.send({ action: "elicitation_response", id, value });
      chat.respondToElicitation(id, value);
    },
    [ws, chat],
  );

  const handleReset = useCallback(() => {
    ws.disconnect();
    chat.reset();
    activity.clearEvents();
  }, [ws, chat, activity]);

  return {
    chat,
    activity,
    ws,
    suggestedPrompt: SUGGESTED_PROMPT,
    handleSendPrompt,
    handleRespondElicitation,
    handleReset,
  };
}

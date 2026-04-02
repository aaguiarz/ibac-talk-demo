import { useCallback, useRef, useState } from "react";
import type {
  ChatMessage,
  ElicitationData,
  ServerEvent,
  ToolCall,
} from "../types";

let msgCounter = 0;
function nextId() {
  return `msg_${++msgCounter}`;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingElicitation, setPendingElicitation] =
    useState<ElicitationData | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  // Ref for current streaming assistant message id
  const streamingRef = useRef<string | null>(null);
  // Track whether the current message has any tool calls that finished
  const hasCompletedToolsRef = useRef(false);

  const handleEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case "agent_text": {
        const { text, done } = event.data as { text: string; done: boolean };

        if (text) {
          // If new text arrives after tool calls completed, start a fresh message
          if (streamingRef.current && hasCompletedToolsRef.current) {
            streamingRef.current = null;
            hasCompletedToolsRef.current = false;
          }

          if (!streamingRef.current) {
            streamingRef.current = nextId();
          }
          const streamId = streamingRef.current;

          setMessages((prev) => {
            const existing = prev.find((m) => m.id === streamId);
            if (existing) {
              return prev.map((m) =>
                m.id === streamId
                  ? { ...m, content: m.content + text }
                  : m,
              );
            }
            return [
              ...prev,
              { id: streamId, role: "assistant" as const, content: text },
            ];
          });
        }

        if (done) {
          streamingRef.current = null;
          hasCompletedToolsRef.current = false;
          setIsRunning(false);
        }
        break;
      }

      case "tool_call_start": {
        const { id, tool, args } = event.data as {
          id: string;
          tool: string;
          args: Record<string, unknown>;
        };
        const tc: ToolCall = { id, tool, args, done: false };

        if (!streamingRef.current) {
          streamingRef.current = nextId();
        }
        const streamId = streamingRef.current;

        setMessages((prev) => {
          const existing = prev.find((m) => m.id === streamId);
          if (existing) {
            return prev.map((m) =>
              m.id === streamId
                ? { ...m, toolCalls: [...(m.toolCalls || []), tc] }
                : m,
            );
          }
          return [
            ...prev,
            {
              id: streamId,
              role: "assistant" as const,
              content: "",
              toolCalls: [tc],
            },
          ];
        });
        break;
      }

      case "tool_call_end": {
        const { id, result, error } = event.data as {
          id: string;
          tool: string;
          result?: string;
          error?: string;
        };

        hasCompletedToolsRef.current = true;

        setMessages((prev) =>
          prev.map((m) => ({
            ...m,
            toolCalls: m.toolCalls?.map((tc) =>
              tc.id === id
                ? {
                    ...tc,
                    result: result ?? undefined,
                    error: error ?? undefined,
                    done: true,
                  }
                : tc,
            ),
          })),
        );
        break;
      }

      case "elicitation": {
        const d = event.data;
        const data: ElicitationData = {
          id: String(d.id ?? ""),
          message: String(d.message ?? ""),
          options: Array.isArray(d.options) ? (d.options as string[]) : [],
        };
        setPendingElicitation(data);
        break;
      }

      case "agent_turn_complete": {
        streamingRef.current = null;
        hasCompletedToolsRef.current = false;
        break;
      }

      case "flow_status": {
        const { phase } = event.data as { phase: string };
        if (phase === "complete" || phase === "error") {
          setIsRunning(false);
          streamingRef.current = null;
          hasCompletedToolsRef.current = false;
        }
        break;
      }
    }
  }, []);

  const sendPrompt = useCallback((prompt: string) => {
    const id = nextId();
    setMessages((prev) => [
      ...prev,
      { id, role: "user" as const, content: prompt },
    ]);
    setIsRunning(true);
    streamingRef.current = null;
    hasCompletedToolsRef.current = false;
  }, []);

  const respondToElicitation = useCallback(
    (elicitationId: string, value: string) => {
      setPendingElicitation(null);
      // Elicitation response creates a visual boundary — next text is a new message
      streamingRef.current = null;
      hasCompletedToolsRef.current = false;
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "system" as const,
          content: `Selected: ${value}`,
          elicitation: {
            id: elicitationId,
            message: "",
            options: [],
            responded: true,
            selectedValue: value,
          },
        },
      ]);
    },
    [],
  );

  const reset = useCallback(() => {
    setMessages([]);
    setPendingElicitation(null);
    setIsRunning(false);
    streamingRef.current = null;
    hasCompletedToolsRef.current = false;
  }, []);

  return {
    messages,
    pendingElicitation,
    isRunning,
    handleEvent,
    sendPrompt,
    respondToElicitation,
    reset,
  };
}

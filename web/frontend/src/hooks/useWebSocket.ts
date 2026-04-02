import { useCallback, useEffect, useRef, useState } from "react";
import type { ServerEvent } from "../types";

interface UseWebSocketOptions {
  flowType: string;
  onMessage: (event: ServerEvent) => void;
}

export function useWebSocket({ flowType, onMessage }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const pendingRef = useRef<Record<string, unknown>[]>([]);
  onMessageRef.current = onMessage;

  const flushPending = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    while (pendingRef.current.length > 0) {
      const msg = pendingRef.current.shift()!;
      ws.send(JSON.stringify(msg));
    }
  }, []);

  const connect = useCallback(() => {
    // Close existing connection first
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/${flowType}`);

    ws.onopen = () => {
      setIsConnected(true);
      flushPending();
    };

    ws.onmessage = (e) => {
      try {
        const event: ServerEvent = JSON.parse(e.data);
        if (event.type === "agent_text") {
          console.log("[WS] agent_text:", JSON.stringify(event.data).slice(0, 200));
        }
        onMessageRef.current(event);
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [flowType, flushPending]);

  const disconnect = useCallback(() => {
    pendingRef.current = [];
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const send = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    } else {
      // Buffer message to send when connected
      pendingRef.current.push(msg);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, []);

  return { isConnected, connect, disconnect, send };
}

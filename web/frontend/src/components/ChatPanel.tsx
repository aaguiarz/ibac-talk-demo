import { useEffect, useRef, useState, type FormEvent } from "react";
import { Send, RotateCcw } from "lucide-react";
import type { ChatMessage as ChatMessageType, ElicitationData } from "../types";
import ChatMessage from "./ChatMessage";
import ElicitationCard from "./ElicitationCard";

interface ChatPanelProps {
  messages: ChatMessageType[];
  pendingElicitation: ElicitationData | null;
  isRunning: boolean;
  isConnected: boolean;
  suggestedPrompt?: string;
  onSendPrompt: (prompt: string) => void;
  onRespondElicitation: (id: string, value: string) => void;
  onReset: () => void;
}

export default function ChatPanel({
  messages,
  pendingElicitation,
  isRunning,
  isConnected,
  suggestedPrompt,
  onSendPrompt,
  onRespondElicitation,
  onReset,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pendingElicitation]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isRunning) return;
    onSendPrompt(trimmed);
    setInput("");
  };

  return (
    <div className="flex-1 flex flex-col bg-slate-50">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <p className="text-slate-400 text-sm">
              Send a message to start the agent...
            </p>
            {suggestedPrompt && (
              <button
                onClick={() => {
                  if (!isRunning) onSendPrompt(suggestedPrompt);
                }}
                className="max-w-md px-4 py-3 rounded-xl border border-indigo-200 bg-indigo-50 text-sm text-indigo-700 hover:bg-indigo-100 transition-colors text-left"
              >
                {suggestedPrompt}
              </button>
            )}
          </div>
        )}

        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}

        {pendingElicitation && (
          <ElicitationCard
            elicitation={pendingElicitation}
            onRespond={onRespondElicitation}
          />
        )}

        {isRunning && !pendingElicitation && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 bg-white p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              isConnected
                ? "Type a message..."
                : "Connecting..."
            }
            disabled={!isConnected || isRunning}
            className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          />
          <button
            type="submit"
            disabled={!isConnected || isRunning || !input.trim()}
            className="px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={onReset}
            className="px-3 py-2.5 rounded-xl border border-slate-200 text-slate-600 text-sm hover:bg-slate-50 transition-colors"
            title="New conversation"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}

import { User, Bot, Info } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "../types";
import ToolCallCard from "./ToolCallCard";

interface ChatMessageProps {
  message: ChatMessageType;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          isUser
            ? "bg-indigo-100 text-indigo-600"
            : isSystem
              ? "bg-amber-100 text-amber-600"
              : "bg-slate-100 text-slate-600"
        }`}
      >
        {isUser ? (
          <User className="w-4 h-4" />
        ) : isSystem ? (
          <Info className="w-4 h-4" />
        ) : (
          <Bot className="w-4 h-4" />
        )}
      </div>

      <div
        className={`flex-1 max-w-[80%] ${isUser ? "flex flex-col items-end" : ""}`}
      >
        {message.content && (
          <div
            className={`rounded-xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
              isUser
                ? "bg-indigo-600 text-white"
                : isSystem
                  ? "bg-amber-50 text-amber-900 border border-amber-200"
                  : "bg-white text-slate-800 border border-slate-200 shadow-sm"
            }`}
          >
            {message.content}
          </div>
        )}

        {message.toolCalls?.map((tc) => (
          <ToolCallCard key={tc.id} toolCall={tc} />
        ))}
      </div>
    </div>
  );
}

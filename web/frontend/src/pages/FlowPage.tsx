import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import DemoLayout from "../components/DemoLayout";
import ChatPanel from "../components/ChatPanel";
import ActivityPanel from "../components/ActivityPanel";
import SessionFlowDiagram from "../components/SessionFlowDiagram";
import type { useFlowSession } from "../hooks/useFlowSession";

interface FlowPageProps {
  flowName: string;
  flowDescription: string;
  session: ReturnType<typeof useFlowSession>;
}

export default function FlowPage({
  flowName,
  flowDescription,
  session,
}: FlowPageProps) {
  const [diagramOpen, setDiagramOpen] = useState(false);

  return (
    <>
      <DemoLayout
        flowName={flowName}
        flowDescription={flowDescription}
        chatPanel={
          <ChatPanel
            messages={session.chat.messages}
            pendingElicitation={session.chat.pendingElicitation}
            isRunning={session.chat.isRunning}
            isConnected={true}
            suggestedPrompt={session.suggestedPrompt}
            onSendPrompt={session.handleSendPrompt}
            onRespondElicitation={session.handleRespondElicitation}
            onReset={session.handleReset}
          />
        }
        activityPanel={
          <ActivityPanel
            events={session.activity.events}
            onExpand={() => setDiagramOpen(true)}
          />
        }
      />

      <AnimatePresence>
        {diagramOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <SessionFlowDiagram
              events={session.activity.events}
              onClose={() => setDiagramOpen(false)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

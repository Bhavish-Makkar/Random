import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Sparkles, Wrench, Trash2 } from "lucide-react";

import MessageBubble from "./MessageBubble.jsx";

const initialMessages = [
  {
    id: 1,
    role: "assistant",
    content: "Hello! 👋 I'm your Flight Chat Assistant. How can I help?",
    time: "11:00 AM",
  },
];

export default function ChatPage() {
  const [messages, setMessages] = useState(initialMessages);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
 const API_BASE = "http://127.0.0.1:8001";

    // user + session identity (for per-user Redis context)
  const [userId] = useState(() => {
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem("flightChatUserId");
      if (stored) return stored;
      const fresh =
        (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
        `user-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      window.localStorage.setItem("flightChatUserId", fresh);
      return fresh;
    }
    return "anonymous-user";
  });

  const [sessionId, setSessionId] = useState(() => {
    if (typeof window !== "undefined" && window.sessionStorage) {
      const stored = window.sessionStorage.getItem("flightChatSessionId");
      if (stored) return stored;
      const fresh =
        (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
        `session-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      window.sessionStorage.setItem("flightChatSessionId", fresh);
      return fresh;
    }
    return `session-${Date.now()}`;
  });

  const [currentChatTitle, setCurrentChatTitle] = useState("New chat");

  const [recentChats, setRecentChats] = useState(() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = window.localStorage.getItem("flightChatRecentChats");
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const [currentStatus, setCurrentStatus] = useState("online");
  const [toolCalls, setToolCalls] = useState([]);
  const bottomRef = useRef(null);
  // 🔄 Auto-save: jab bhi is session me real conversation ho jaye,
  // usko recentChats + localStorage me persist kar do


  // --- scrolling state
  const [userHasScrolled, setUserHasScrolled] = useState(false);
  const [isNearBottom, setIsNearBottom] = useState(true);

  // chat container ref + onScroll handler
  const chatRef = useRef(null);
  const SCROLL_THRESHOLD = 24;

  const onScroll = () => {
    const el = chatRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.clientHeight - el.scrollTop;

    const nearBottom = distanceFromBottom <= SCROLL_THRESHOLD;
    setIsNearBottom(nearBottom);

    if (!nearBottom && distanceFromBottom > 100) {
      setUserHasScrolled(true);
    } else if (nearBottom) {
      setUserHasScrolled(false);
    }
  };
  const persistRecentChats = (chats) => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem("flightChatRecentChats", JSON.stringify(chats));
    } catch {
      // ignore storage errors
    }
  };

  // conservative auto-scroll (only when near bottom)
useEffect(() => {
  // sirf tab save karna jab:
  //  - greeting se zyada messages hon
  //  - kam se kam 1 user message ho
  if (!messages || messages.length <= 1) return;
  const hasUser = messages.some((m) => m.role === "user");
  if (!hasUser) return;

  const lastUser = [...messages].reverse().find((m) => m.role === "user");

  const titleFromUser =
    (lastUser?.content || "").slice(0, 32) +
    ((lastUser?.content || "").length > 32 ? "..." : "");

  const safeTitle =
    currentChatTitle !== "New chat"
      ? currentChatTitle
      : titleFromUser || "Previous chat";

  const chatObj = {
    id: sessionId,
    title: safeTitle,
    createdAt: Date.now(),
    messages,
  };

  setRecentChats((prev) => {
    // check: kya yeh session pehle se list me hai?
    const idx = prev.findIndex((c) => c.id === sessionId);

    let next;
    if (idx >= 0) {
      // ✅ existing session → same position pe update
      next = [...prev];
      next[idx] = { ...next[idx], ...chatObj };
    } else {
      // ✅ new session → list ke end me add
      next = [...prev, chatObj];
    }

    persistRecentChats(next);
    return next;
  });
}, [messages, sessionId, currentChatTitle]);



  // util: pretty JSON if possible
  const tryPrettyJson = (text) => {
    if (!text || typeof text !== "string") return null;
    try {
      const obj = JSON.parse(text);
      return JSON.stringify(obj, null, 2);
    } catch {
      return null;
    }
  };

  const startFreshSessionWithoutArchiving = () => {
    const freshSession =
      (typeof window !== "undefined" &&
        window.crypto &&
        window.crypto.randomUUID &&
        window.crypto.randomUUID()) ||
      `session-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

    if (typeof window !== "undefined" && window.sessionStorage) {
      window.sessionStorage.setItem("flightChatSessionId", freshSession);
    }

    setSessionId(freshSession);
    setMessages(initialMessages);
    setCurrentChatTitle("New chat");
    setToolCalls([]);
    setCurrentStatus("online");
    setUserHasScrolled(false);
    setIsNearBottom(true);
  };

   const handleNewChat = () => {
  const snapshotMessages = messages;

  if (snapshotMessages && snapshotMessages.length > 1) {
    const lastUser = [...snapshotMessages].reverse().find((m) => m.role === "user");
    const titleFromUser =
      (lastUser?.content || "").slice(0, 32) +
      ((lastUser?.content || "").length > 32 ? "..." : "");
    const safeTitle =
      currentChatTitle !== "New chat"
        ? currentChatTitle
        : titleFromUser || "Previous chat";

    const chatObj = {
      id: sessionId,
      title: safeTitle,
      createdAt: Date.now(),
      messages: snapshotMessages,
    };

setRecentChats((prev) => {
  const idx = prev.findIndex((c) => c.id === sessionId);
  let next;
  if (idx >= 0) {
    next = [...prev];
    next[idx] = { ...next[idx], ...chatObj };
  } else {
    next = [...prev, chatObj];
  }
  persistRecentChats(next);
  return next;
});
  }

  startFreshSessionWithoutArchiving();
};


const handleSelectRecentChat = (chatId) => {
  if (chatId === sessionId) return;

  // sirf existing chat ko dhundo
  const chat =
    recentChats.find((c) => c.id === chatId) ||
    sidebarChats.find((c) => c.id === chatId) ||
    null;

  if (!chat) return;

  // active session change karo
  setSessionId(chat.id);
  setCurrentChatTitle(chat.title || "Previous chat");
  setMessages(chat.messages || initialMessages);

  // ❌ yahan recentChats ko mutate NA karo, order same rehne do

  setToolCalls([]);
  setCurrentStatus("online");
  setUserHasScrolled(false);
  setIsNearBottom(true);
};



const sidebarChats = React.useMemo(() => {
  const base = [...recentChats];

  // current active session ko list me reflect karo
  const idx = base.findIndex((c) => c.id === sessionId);
  if (idx >= 0) {
    base[idx] = {
      ...base[idx],
      title: currentChatTitle,
      messages,
    };
  } else {
    // agar yeh brand new session hai to list me add karo
    base.push({
      id: sessionId,
      title: currentChatTitle,
      createdAt: Date.now(),
      messages,
    });
  }

  // 🧠 IMPORTANT: UI me newest chat upar chahiye
  // createdAt DESC (newest first)
  base.sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));

  return base;
}, [recentChats, sessionId, currentChatTitle, messages]);


    const deleteSession = async (sessionIdToDelete) => {
    if (!sessionIdToDelete) return;
    if (!confirm("Delete this session? This will remove its chat history.")) return;

    let nextAfterDelete = [];

    try {
      // 1) Optimistically remove from recentChats + localStorage
      setRecentChats((prev) => {
        nextAfterDelete = prev.filter((c) => c.id !== sessionIdToDelete);
        persistRecentChats(nextAfterDelete);
        return nextAfterDelete;
      });

      // 2) Agar yahi current open session hai → fallback chat choose karo
      if (sessionIdToDelete === sessionId) {
        // kis chat pe jump karein?
        const fallback =
          nextAfterDelete.find((c) => c.id !== sessionIdToDelete) ||
          nextAfterDelete[0];

        if (fallback) {
          // Kisi dusre stored chat pe switch
          setSessionId(fallback.id);
          setMessages(fallback.messages || initialMessages);
          setCurrentChatTitle(fallback.title || "New chat");
        } else {
          // koi bhi chat nahi bachi → totally fresh
          startFreshSessionWithoutArchiving();
        }
        setToolCalls([]);
        setCurrentStatus("online");
      }

      // 3) Backend Redis se bhi delete karo
      const params = new URLSearchParams({
        userId,
        sessionId: sessionIdToDelete,
      });

      const res = await fetch(`${API_BASE}/session?${params.toString()}`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
      });

      if (!res.ok) {
        console.warn("Failed to delete session on server", await res.text());
      } else {
        const body = await res.json();
        console.info("Delete session response:", body);
      }
    } catch (err) {
      console.error("deleteSession error:", err);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMsg = {
      id: Date.now(),
      role: "user",
      content: input.trim(),
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (currentChatTitle === "New chat") {
      const snippet =
        userMsg.content.length > 32
          ? `${userMsg.content.slice(0, 32)}...`
          : userMsg.content;
      if (snippet) {
        setCurrentChatTitle(snippet);
      }
    }

    const userPrompt = input.trim();
    setInput("");
    setIsLoading(true);
    setCurrentStatus("thinking...");
    setToolCalls([]); // Clear previous tool calls
    setUserHasScrolled(false);
    setIsNearBottom(true);

    // 🔵 placeholder assistant bubble — BIG DOTS animation (●), 1..7 dots loop
    const placeholderId = Date.now() + 1;
    let assistantMsg = {
      id: placeholderId,
      role: "assistant",
      content: "●", // start with one large dot
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    let messageAdded = true;
    setMessages((prev) => [...prev, assistantMsg]);

    // dots animation (●, ●●, ... up to 7) — DO NOT stop on TEXT_MESSAGE_START
    let dotCount = 1;
    let typingInterval = setInterval(() => {
      dotCount = dotCount >= 7 ? 1 : dotCount + 1; // 1..7
      assistantMsg.content = "●".repeat(dotCount);
      setMessages((prev) => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (lastIndex >= 0 && updated[lastIndex].id === assistantMsg.id) {
          updated[lastIndex] = { ...assistantMsg };
        }
        return updated;
      });
    }, 350);

    // firstContent flag to clear dots exactly on first delta
    let firstContentArrived = false;

    try {
          // const baseUrl = "http://10.35.8.178:8001/get_data";
          const baseUrl = "http://127.0.0.1:8001/get_data";

          const params = new URLSearchParams({
            userprompt: userPrompt,
            userId,
            sessionId,
          });

          const response = await fetch(`${baseUrl}?${params.toString()}`, {
            method: "POST",
            headers: {
              Accept: "text/event-stream",
            },
          });



      if (!response.ok || !response.body) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          if (part.startsWith("data: ")) {
            const data = part.slice(6);
            try {
              const event = JSON.parse(data);
              console.log("📦 Event received:", event.type, event);

              switch (event.type) {
                case "RUN_STARTED":
                  setCurrentStatus("processing...");
                  break;

                case "TEXT_MESSAGE_START":
                  setCurrentStatus("typing...");
                  // ⛔️ do NOT stop dots here — wait for first delta
                  break;

                case "TEXT_MESSAGE_CONTENT":
                  // On FIRST delta, stop dots & clear typing bubble
                  if (!firstContentArrived) {
                    firstContentArrived = true;
                    if (typingInterval) {
                      clearInterval(typingInterval);
                      typingInterval = null;
                    }
                    assistantMsg.content = "";
                    setMessages((prev) => {
                      const updated = [...prev];
                      const lastIndex = updated.length - 1;
                      if (lastIndex >= 0 && updated[lastIndex].id === assistantMsg.id) {
                        updated[lastIndex] = { ...assistantMsg };
                      }
                      return updated;
                    });
                  }
                  // Append streaming content
                  assistantMsg.content += event.delta;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const lastIndex = updated.length - 1;
                    if (lastIndex >= 0 && updated[lastIndex].id === assistantMsg.id) {
                      updated[lastIndex] = { ...assistantMsg };
                    }
                    return updated;
                  });
                  break;

                case "TEXT_MESSAGE_END":
                  setCurrentStatus("online");
                  break;

                case "TOOL_CALL_START":
                  setCurrentStatus(`calling ${event.toolCallName}...`);
                  setToolCalls((prev) => {
                    const exists = prev.find((tc) => tc.id === event.toolCallId);
                    if (exists) {
                      return prev.map((tc) =>
                        tc.id === event.toolCallId ? { ...tc, args: "", status: "calling" } : tc
                      );
                    }
                    const newToolCall = {
                      id: event.toolCallId,
                      name: event.toolCallName,
                      args: "",
                      result: "",
                      status: "calling",
                      expanded: false,
                    };
                    return [...prev, newToolCall];
                  });
                  break;

                case "TOOL_CALL_ARGS":
                  setToolCalls((prev) =>
                    prev.map((tc) =>
                      tc.id === event.toolCallId ? { ...tc, args: tc.args + event.delta } : tc
                    )
                  );
                  break;

                case "TOOL_CALL_RESULT":
                  setToolCalls((prev) =>
                    prev.map((tc) =>
                      tc.id === event.toolCallId
                        ? { ...tc, result: event.content, status: "completed" }
                        : tc
                    )
                  );
                  setCurrentStatus("processing results...");
                  break;

                case "RUN_FINISHED":
                  setCurrentStatus("online");
                  setIsLoading(false);

                  // Agar backend se table / chart aa raha hai to
                  if (event.table || event.chart) {
                    // assistant message ko enrich karo with table + chart
                    assistantMsg = {
                      ...assistantMsg,
                      table: event.table || null,
                      chart: event.chart || null,
                    };

                    setMessages((prev) => {
                      const updated = [...prev];
                      const lastIndex = updated.length - 1;
                      if (lastIndex >= 0 && updated[lastIndex].id === assistantMsg.id) {
                        updated[lastIndex] = { ...assistantMsg };
                      }
                      return updated;
                    });
                  }

                  break;


                case "RUN_ERROR":
                  console.error("❌ Run error:", event.message);
                  setCurrentStatus("error");
                  setIsLoading(false);
                  if (typingInterval) {
                    clearInterval(typingInterval);
                    typingInterval = null;
                  }
                  // convert typing bubble into error text
                  assistantMsg.content = `Error: ${event.message}`;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const lastIndex = updated.length - 1;
                    if (lastIndex >= 0 && updated[lastIndex].id === assistantMsg.id) {
                      updated[lastIndex] = { ...assistantMsg };
                    }
                    return updated;
                  });
                  break;

                default:
                  console.log("❓ Unknown event type:", event.type);
              }
            } catch (err) {
              console.error("Failed to parse event:", err);
            }
          }
        }
      }
    } catch (error) {
      console.error("Error:", error);
      if (typingInterval) {
        clearInterval(typingInterval);
        typingInterval = null;
      }
      // convert the typing bubble into generic error if stream failed early
      assistantMsg.content = "Sorry, an error occurred. Please try again.";
      setMessages((prev) => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (lastIndex >= 0 && updated[lastIndex].id === assistantMsg.id) {
          updated[lastIndex] = { ...assistantMsg };
        } else {
          updated.push({
            id: Date.now() + 2,
            role: "assistant",
            content: assistantMsg.content,
            time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          });
        }
        return updated;
      });
      setCurrentStatus("error");
    } finally {
      if (typingInterval) clearInterval(typingInterval);
      setIsLoading(false);
      setCurrentStatus("online");
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

return (
  <div className="page-shell">
    {/* LEFT: Side panel */}
    {isSidebarOpen && (
      <aside className="chat-sidebar">
        <div className="sidebar-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <button
            type="button"
            className="sidebar-new-chat-btn"
            onClick={handleNewChat}
            disabled={isLoading}
          >
            <span className="sidebar-new-chat-icon">＋</span>
            <span>New chat</span>
          </button>

          {/* 👇 Chhota close icon (optional) */}
          <button
            type="button"
            onClick={() => setIsSidebarOpen(false)}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              fontSize: "16px",
              lineHeight: 1,
            }}
            title="Close sidebar"
          >
            ×
          </button>
        </div>
<div className="sidebar-section">
        <div className="sidebar-section-title">Chats</div>
        {sidebarChats.length === 0 ? (
          <div className="sidebar-empty">No chats yet</div>
        ) : (
          sidebarChats.map((chat) => {
            const isActive = chat.id === sessionId;

            return (
              <div
                key={chat.id}
                style={{ display: "flex", gap: 8, alignItems: "center" }}
              >
                <button
                  type="button"
                  className={
                    "sidebar-chat-item" +
                    (isActive ? " sidebar-chat-item--active" : "")
                  }
                  onClick={() => handleSelectRecentChat(chat.id)}
                  disabled={isLoading && !isActive}
                  style={{ flex: 1, textAlign: "left" }}
                >
                  <span
                    className={
                      "sidebar-chat-dot" +
                      (isActive ? " sidebar-chat-dot--active" : "")
                    }
                  />
                  <span className="sidebar-chat-text">
                    {chat.title || "Untitled chat"}
                  </span>
                </button>

                {/* Delete button for each chat */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteSession(chat.id);
                  }}
                  disabled={isLoading}
                  title="Delete session"
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    padding: 6,
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            );
          })
        )}
      </div>
    </aside>

    )} 

    {/* RIGHT: your existing chat UI */}
    <div className="chat-wrapper">
      {/* Header */}
      <header className="chat-header">
        <div className="chat-header-left">
          <div>
            <div
              className="chat-title"
              style={{ display: "flex", alignItems: "center", gap: "8px" }}
            >
              <img
                src="src/assets/indigo-logo.png"
                alt="IndiGo Logo"
                style={{ height: "30px" }}
              />
              Flight Assistant
            </div>
            <div className="chat-subtitle">
              <Sparkles size={20} /> {currentStatus}
            </div>
          </div>
        </div>
        <div className="chat-header-right">
          <button
            className="header-pill"
            onClick={() => setIsSidebarOpen((prev) => !prev)}
            type="button"
          >
            {isSidebarOpen ? "Hide chats" : "Show chats"}
          </button>

          <button
            className="header-pill"
            onClick={handleNewChat}
            type="button"
          >
            New Chat
          </button>
        </div>
      </header> 
      
      <main className="chat-main" ref={chatRef} onScroll={onScroll}>
        <AnimatePresence>
          {messages.map((msg, index) => {
            const isLastAssistantMsg =
              msg.role === "assistant" && index === messages.length - 1;

            return (
              <React.Fragment key={msg.id}>
                {/* 🔹 RUN STATUS inside chat (ONLY status chip; no tool-call chips) */}
                {msg.role === "assistant" &&
                  isLastAssistantMsg &&
                  (isLoading ||
                    toolCalls.length > 0 ||
                    currentStatus !== "online") && (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="run-status-and-tools"
                      style={{
                        background: "#f8fafc",
                        borderRadius: "12px",
                        padding: "12px 16px",
                        marginBottom: "8px",
                        border: "1px solid #e2e8f0",
                      }}
                    >
                      {/* Status chip only */}
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 8,
                          marginBottom: toolCalls.length ? 8 : 0,
                        }}
                      >
                        <span
                          style={{
                            fontSize: "0.72rem",
                            padding: "4px 8px",
                            borderRadius: "999px",
                            background: "#eef2ff",
                            border: "1px solid #e0e7ff",
                            color: "#3730a3",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <Sparkles size={12} /> {currentStatus}
                        </span>
                      </div>

                      {/* Tool calls panel (dropdown list) */}
                      {toolCalls.length > 0 && (
                        <div
                          className="tool-calls-container"
                          style={{
                            background: "#f0f4ff",
                            borderRadius: "12px",
                            padding: "12px 16px",
                            border: "1px solid #d0d9ff",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.75rem",
                              fontWeight: "600",
                              color: "#4f46e5",
                              marginBottom: "8px",
                              display: "flex",
                              alignItems: "center",
                              gap: "6px",
                            }}
                          >
                            <Wrench size={14} />
                            Tool Calls
                          </div>

                          {toolCalls.map((tc) => {
                            const prettyArgs = tryPrettyJson(tc.args);
                            const prettyResult = tryPrettyJson(tc.result);
                            return (
                              <div
                                key={tc.id}
                                style={{
                                  background: "white",
                                  borderRadius: "8px",
                                  padding: "8px 10px",
                                  marginBottom: "6px",
                                  fontSize: "0.72rem",
                                  border: "1px solid #e0e7ff",
                                }}
                              >
                                {/* Dropdown Header */}
                                <div
                                  onClick={() =>
                                    setToolCalls((prev) =>
                                      prev.map((tool) =>
                                        tool.id === tc.id
                                          ? { ...tool, expanded: !tool.expanded }
                                          : tool
                                      )
                                    )
                                  }
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "space-between",
                                    cursor: "pointer",
                                    userSelect: "none",
                                  }}
                                >
                                  <strong style={{ color: "#1e293b" }}>
                                    {tc.name}
                                  </strong>
                                  {tc.expanded ? "▲" : "▼"}
                                </div>

                                {/* Dropdown Content */}
                                {tc.expanded && (
                                  <div
                                    style={{
                                      marginTop: "8px",
                                      paddingLeft: "16px",
                                      color: "#4b5563",
                                    }}
                                  >
                                    {tc.result && (
                                      <div style={{ marginTop: 6 }}>
                                        <strong>Result:</strong>
                                        {prettyResult ? (
                                          <pre
                                            style={{
                                              margin: "6px 0 0",
                                              whiteSpace: "pre-wrap",
                                              fontFamily:
                                                "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                                              fontSize: "12px",
                                            }}
                                          >
                                            {prettyResult}
                                          </pre>
                                        ) : (
                                          <> {tc.result}</>
                                        )}
                                      </div>
                                    )}

                                    <div style={{ marginTop: 6 }}>
                                      <strong>Status:</strong>{" "}
                                      {tc.status === "completed"
                                        ? "Completed"
                                        : "In Progress"}
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </motion.div>
                  )}

                {/* Message bubble */}
                <motion.div
                  initial={{ opacity: 0, y: 6, scale: 0.995 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.12 }}
                >
                  <MessageBubble
                    role={msg.role}
                    content={msg.content}
                    time={msg.time}
                    table={msg.table}
                    chart={msg.chart}
                  />
                </motion.div>
              </React.Fragment>
            );
          })}
        </AnimatePresence>
        <div ref={bottomRef} />
      </main>

      {/* Input */}
      <footer className="chat-footer">
        <div className="input-box">
          <textarea
            rows="1"
            className="input-text"
            placeholder="Type your message…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={isLoading}
          />
          <button
            onClick={sendMessage}
            className="send-btn"
            aria-label="Send message"
            disabled={isLoading || !input.trim()}
          >
            <Send size={18} />
          </button>
        </div>
      </footer>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  </div>
);
}



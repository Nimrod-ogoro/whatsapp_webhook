import React, { useEffect, useState, useRef } from "react";
import { supabase } from "./supabaseClient";

export default function App() {
  const [conversations, setConversations] = useState([]); // list of customers
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [messages, setMessages] = useState([]);
  const messagesEndRef = useRef(null);

  // Fetch customers (conversations)
  useEffect(() => {
    async function loadCustomers() {
      const { data, error } = await supabase
        .from("customers")
        .select("*")
        .order("last_seen", { ascending: false });

      if (error) console.error("Error loading customers:", error);
      else setConversations(data || []);
    }

    loadCustomers();

    const channel = supabase
      .channel("customers_channel")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "customers" },
        (payload) => {
          setConversations((prev) =>
            prev.map((c) =>
              c.phone === payload.new.phone ? payload.new : c
            )
          );
        }
      )
      .subscribe();

    return () => supabase.removeChannel(channel);
  }, []);

  // Fetch messages for selected conversation
  useEffect(() => {
    if (!selectedPhone) return;

    async function loadMessages() {
      const { data, error } = await supabase
        .from("messages")
        .select("*")
        .eq("phone", selectedPhone)
        .order("created_at", { ascending: true }) // ascending for proper top-to-bottom flow
        .limit(100);

      if (error) console.error("Error loading messages:", error);
      else setMessages(data || []);
    }

    loadMessages();

    const channel = supabase
      .channel(`messages_${selectedPhone}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "messages",
          filter: `phone=eq.${selectedPhone}`,
        },
        (payload) => {
          setMessages((prev) => [...prev, payload.new]); // append at end
        }
      )
      .subscribe();

    return () => supabase.removeChannel(channel);
  }, [selectedPhone]);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "Arial, sans-serif" }}>
      {/* Conversations list */}
      <div style={{ width: 300, borderRight: "1px solid #eee", overflowY: "auto" }}>
        <h3 style={{ padding: 12 }}>Conversations</h3>
        {conversations.map((c) => (
          <div
            key={c.phone}
            onClick={() => setSelectedPhone(c.phone)}
            style={{
              padding: 12,
              cursor: "pointer",
              borderBottom: "1px solid #f2f2f2",
              background: c.phone === selectedPhone ? "#f0f0f0" : "transparent",
            }}
          >
            <div style={{ fontWeight: 500 }}>{c.display_name || c.phone}</div>
            <div style={{ fontSize: 12, color: "#666" }}>
              {c.last_seen ? new Date(c.last_seen).toLocaleString() : "Never"}
            </div>
          </div>
        ))}
      </div>

      {/* Messages panel */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 16,
            background: "#f9f9f9",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {messages.map((m) => (
            <div
              key={m.id}
              style={{
                alignSelf: m.direction === "outgoing" ? "flex-end" : "flex-start",
                margin: "6px 0",
                maxWidth: "70%",
                wordBreak: "break-word",
              }}
            >
              <div
                style={{
                  padding: "10px 12px",
                  borderRadius: 12,
                  background: m.direction === "outgoing" ? "#dcf8c6" : "#fff",
                  border: "1px solid #eee",
                  color: "#000",
                }}
              >
                {m.body}
              </div>
              <div style={{ fontSize: 10, color: "#999", marginTop: 2 }}>
                {m.created_at ? new Date(m.created_at).toLocaleString() : ""}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <ChatComposer selectedPhone={selectedPhone} />
      </div>
    </div>
  );
}

function ChatComposer({ selectedPhone }) {
  const [text, setText] = useState("");

  async function send() {
    if (!selectedPhone || !text.trim()) return;

    try {
      await fetch(`/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: selectedPhone, text }),
      });
      setText("");
    } catch (err) {
      console.error("Failed to send message:", err);
    }
  }

  return (
    <div style={{ padding: 10, borderTop: "1px solid #eee", display: "flex", background: "#fff" }}>
      <input
        style={{
          flex: 1,
          padding: 10,
          borderRadius: 6,
          border: "1px solid #ccc",
          outline: "none",
        }}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={selectedPhone ? "Type a message" : "Select a conversation"}
        onKeyDown={(e) => e.key === "Enter" && send()}
      />
      <button
        onClick={send}
        style={{
          marginLeft: 8,
          padding: "10px 16px",
          background: "#4CAF50",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          cursor: "pointer",
        }}
      >
        Send
      </button>
    </div>
  );
}




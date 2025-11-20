import React, { useEffect, useState } from "react";
import { supabase } from "./supabaseClient";

export default function App() {
  const [conversations, setConversations] = useState([]); // list of customers
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [messages, setMessages] = useState([]);

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

    // Optional: subscribe to changes in customers table
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
        .order("created_at", { ascending: false })
        .limit(100);

      if (error) console.error("Error loading messages:", error);
      else setMessages(data || []);
    }

    loadMessages();

    // Subscribe to new messages for this conversation
    const channel = supabase
      .channel(`messages_${selectedPhone}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages", filter: `phone=eq.${selectedPhone}` },
        (payload) => {
          setMessages((prev) => [payload.new, ...prev]);
        }
      )
      .subscribe();

    return () => supabase.removeChannel(channel);
  }, [selectedPhone]);

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      {/* Conversations list */}
      <div style={{ width: 300, borderRight: "1px solid #eee", overflow: "auto" }}>
        <h3>Conversations</h3>
        {conversations.map((c) => (
          <div
            key={c.phone}
            onClick={() => setSelectedPhone(c.phone)}
            style={{
              padding: 12,
              cursor: "pointer",
              borderBottom: "1px solid #f2f2f2",
              background: c.phone === selectedPhone ? "#f0f0f0" : "transparent"
            }}
          >
            <div>{c.display_name || c.phone}</div>
            <div style={{ fontSize: 12, color: "#666" }}>
              {c.last_seen ? new Date(c.last_seen).toLocaleString() : "Never"}
            </div>
          </div>
        ))}
      </div>

      {/* Messages panel */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, overflow: "auto", padding: 16, display: "flex", flexDirection: "column-reverse" }}>
          {messages.map((m) => (
            <div
              key={m.id}
              style={{
                alignSelf: m.direction === "outgoing" ? "flex-end" : "flex-start",
                margin: 6,
                maxWidth: "60%",
              }}
            >
              <div
                style={{
                  padding: 10,
                  borderRadius: 8,
                  background: m.direction === "outgoing" ? "#dcf8c6" : "#fff",
                  boxShadow: "0 0 0 1px #eee inset",
                }}
              >
                {m.body}
              </div>
              <div style={{ fontSize: 10, color: "#999" }}>
                {m.created_at ? new Date(m.created_at).toLocaleString() : ""}
              </div>
            </div>
          ))}
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
    <div style={{ padding: 10, borderTop: "1px solid #eee", display: "flex" }}>
      <input
        style={{ flex: 1, padding: 8 }}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={selectedPhone ? "Type a message" : "Select a conversation"}
      />
      <button onClick={send} style={{ marginLeft: 8 }}>
        Send
      </button>
    </div>
  );
}




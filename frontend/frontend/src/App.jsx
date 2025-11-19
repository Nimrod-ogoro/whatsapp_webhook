import React, { useEffect, useState } from "react";
import { supabase } from "./supabaseClient";

export default function App() {
  const [conversations, setConversations] = useState([]); // list of customers
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    // fetch list of customers
    async function loadCustomers() {
      const { data, error } = await supabase
        .from("customers")
        .select("*")
        .order("last_seen", { ascending: false });

      if (error) console.error("Error loading customers:", error);
      else setConversations(data || []);
    }

    loadCustomers();
  }, []);

  useEffect(() => {
    if (!selected) return;

    // load messages for selected phone
    async function loadMessages() {
      const { data, error } = await supabase
        .from("messages")
        .select("*")
        .eq("phone", selected)
        .order("created_at", { ascending: false })
        .limit(100);

      if (error) console.error("Error loading messages:", error);
      else setMessages(data || []);
    }

    loadMessages();

    // Subscribe to new messages for the selected phone
    const channel = supabase
      .channel("messages_channel")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages", filter: `phone=eq.${selected}` },
        (payload) => {
          setMessages((prev) => [payload.new, ...prev]);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [selected]);

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <div style={{ width: 300, borderRight: "1px solid #eee", overflow: "auto" }}>
        <h3>Conversations</h3>
        {conversations.map((c) => (
          <div
            key={c.phone}
            onClick={() => setSelected(c.phone)}
            style={{ padding: 12, cursor: "pointer", borderBottom: "1px solid #f2f2f2" }}
          >
            <div>{c.display_name || c.phone}</div>
            <div style={{ fontSize: 12, color: "#666" }}>{c.last_seen}</div>
          </div>
        ))}
      </div>

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
                {new Date(m.created_at).toLocaleString()}
              </div>
            </div>
          ))}
        </div>

        <ChatComposer selected={selected} />
      </div>
    </div>
  );
}

function ChatComposer({ selected }) {
  const [text, setText] = React.useState("");

  async function send() {
    if (!selected || !text.trim()) return;

    // send via your webhook server endpoint /send
    await fetch(`/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: selected, text }),
    });

    setText("");
  }

  return (
    <div style={{ padding: 10, borderTop: "1px solid #eee", display: "flex" }}>
      <input
        style={{ flex: 1, padding: 8 }}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={selected ? "Type a message" : "Select a conversation"}
      />
      <button onClick={send} style={{ marginLeft: 8 }}>
        Send
      </button>
    </div>
  );
}



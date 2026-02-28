// DeepSeek Web Chat — Client-side JS

document.addEventListener("DOMContentLoaded", () => {
  const chat = document.getElementById("chat");
  const form = document.getElementById("chatForm");
  const messageInput = document.getElementById("message");
  const agentSelect = document.getElementById("agentSelect");
  const statusEl = document.getElementById("status");
  const statsEl = document.getElementById("stats");
  const clearBtn = document.getElementById("clearBtn");

  // Initial scroll to bottom
  chat.scrollTop = chat.scrollHeight;

  function addMessage(role, text, label) {
    const msg = document.createElement("div");
    msg.className = "msg " + role;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = label || (role === "user" ? "You" : "Assistant");
    const content = document.createElement("div");
    content.className = "content";
    content.textContent = text || "";
    msg.appendChild(meta);
    msg.appendChild(content);
    chat.appendChild(msg);
    chat.scrollTop = chat.scrollHeight;
    return content;
  }

  function formatStats(stats) {
    if (!stats) return "";
    const parts = [];
    if (stats.tokens_local) {
      const t = stats.tokens_local;
      parts.push(
        "Tokens (local): request=" +
        t.request +
        " (" +
        t.request_method +
        "), history=" +
        t.history +
        " (" +
        t.history_method +
        "), response=" +
        t.response +
        " (" +
        t.response_method +
        ")"
      );
    }
    const usageParts = [];
    if (stats.prompt_tokens != null) usageParts.push("prompt=" + stats.prompt_tokens);
    if (stats.completion_tokens != null)
      usageParts.push("completion=" + stats.completion_tokens);
    if (stats.total_tokens != null) usageParts.push("total=" + stats.total_tokens);
    const duration =
      stats.duration_ms != null ? stats.duration_ms + " ms" : "n/a";
    const usage = usageParts.length ? usageParts.join(", ") : "n/a";
    const cost =
      stats.cost_usd != null ? "$" + stats.cost_usd.toFixed(6) : "n/a";
    const sessionCost =
      stats.session_cost_usd != null ? "$" + stats.session_cost_usd.toFixed(6) : "n/a";
    if (
      stats.duration_ms != null ||
      usageParts.length ||
      stats.cost_usd != null ||
      stats.session_cost_usd != null
    ) {
      parts.push(
        "Time: " +
        duration +
        " | Tokens: " +
        usage +
        " | Cost: " +
        cost +
        " | Session Cost: " +
        sessionCost
      );
    }
    return parts.join(" | ");
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = messageInput.value.trim();
    if (!text) return;

    addMessage("user", text, "You");
    const agentLabel =
      agentSelect.options[agentSelect.selectedIndex]?.text || "Assistant";
    const assistantContent = addMessage("assistant", "", agentLabel);
    messageInput.value = "";
    statusEl.textContent = "Streaming...";
    statsEl.textContent = "";
    statsEl.style.display = "none";

    // Auto-scroll on submit action
    chat.scrollTop = chat.scrollHeight;

    const agentId = agentSelect.value || "android";
    const url =
      "/stream?message=" +
      encodeURIComponent(text) +
      "&agent=" +
      encodeURIComponent(agentId);
    const source = new EventSource(url);

    source.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.delta) {
        assistantContent.textContent += payload.delta;
        chat.scrollTop = chat.scrollHeight;
      }
      if (payload.stats) {
        const statsText = formatStats(payload.stats);
        statsEl.textContent = statsText;
        statsEl.style.display = statsText ? "block" : "none";
      }
      if (payload.done) {
        statusEl.textContent = "";
        source.close();
      }
      if (payload.error) {
        statusEl.textContent = "Error: " + payload.error;
        source.close();
      }
      // Keep scrolled to bottom during streaming
      chat.scrollTop = chat.scrollHeight;
    };

    source.onerror = () => {
      statusEl.textContent = "Stream connection error.";
      source.close();
    };
  });

  clearBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const res = await fetch("/clear", { method: "POST" });
    if (res.ok) {
      chat.innerHTML = "";
      statusEl.textContent = "Context cleared.";
      statsEl.textContent = "";
      statsEl.style.display = "none";
      chat.scrollTop = 0;
    }
  });

  // Handle enter key in textarea to submit form but shift+enter makes new line
  messageInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // Find the submit button and click it to ensure all form logic triggers naturally
      form.querySelector('button[type="submit"]').click();
    }
  });
});


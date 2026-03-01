// DeepSeek Web Chat — Client-side JS

document.addEventListener("DOMContentLoaded", () => {
  const chat = document.getElementById("chat");
  const form = document.getElementById("chatForm");
  const messageInput = document.getElementById("message");
  const agentSelect = document.getElementById("agentSelect");
  const strategySelect = document.getElementById("strategySelect");
  const statusEl = document.getElementById("status");
  const statsEl = document.getElementById("stats");
  const clearBtn = document.getElementById("clearBtn");

  chat.scrollTop = chat.scrollHeight;

  let currentSessionId = "default";
  const sessionListEl = document.getElementById("sessionList");

  async function loadSessions() {
    try {
      const res = await fetch("/sessions");
      if (res.ok) {
        const data = await res.json();
        sessionListEl.innerHTML = "";

        // Sort sessions descending by date (latest first)
        data.sessions.sort((a, b) => {
          const dateA = new Date(a.updated_at || 0);
          const dateB = new Date(b.updated_at || 0);
          return dateB - dateA;
        });

        let foundCurrent = false;

        data.sessions.forEach(s => {
          const item = document.createElement("button");
          item.className = "session-item";
          if (s.id === currentSessionId) {
            item.classList.add("active");
            foundCurrent = true;
          }

          const titleDiv = document.createElement("div");
          titleDiv.className = "session-title";
          // Title
          const titleText = document.createElement("div");
          if (!s.summary) {
            titleText.textContent = s.id === "default" ? "Default Branch" : "New Session";
          } else {
            titleText.textContent = s.summary;
          }
          titleDiv.appendChild(titleText);

          // Date
          if (s.updated_at) {
            const dateText = document.createElement("div");
            dateText.className = "session-date";
            dateText.textContent = new Date(s.updated_at).toLocaleString();
            titleDiv.appendChild(dateText);
          }

          item.appendChild(titleDiv);

          const delBtn = document.createElement("button");
          delBtn.className = "delete-btn";
          delBtn.textContent = "🗑";
          delBtn.title = "Delete session";
          delBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            await fetch(`/sessions/${encodeURIComponent(s.id)}`, { method: "DELETE" });
            if (currentSessionId === s.id) {
              currentSessionId = "default"; // Switch to default (it will be recreated)
              await loadHistory(currentSessionId);
            }
            await loadSessions();
          });
          item.appendChild(delBtn);

          item.addEventListener("click", async () => {
            currentSessionId = s.id;
            // update UI
            Array.from(sessionListEl.children).forEach(child => child.classList.remove("active"));
            item.classList.add("active");
            await loadHistory(s.id);
          });

          sessionListEl.appendChild(item);
        });

        if (!foundCurrent) {
          currentSessionId = "default";
          // Not re-loading history directly to prevent double loading on init, 
          // but normally we are safe since default is always there
        }
      }
    } catch (e) { console.error(e); }
  }

  function bindBranchButtons() {
    const btns = document.querySelectorAll(".branch-btn");
    btns.forEach(btn => {
      // Remove old listener if any to avoid duplicates
      const newBtn = btn.cloneNode(true);
      btn.parentNode.replaceChild(newBtn, btn);

      newBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        const msgDiv = newBtn.closest(".msg");
        const idx = parseInt(msgDiv.getAttribute("data-msg-id"), 10);
        const parentId = currentSessionId;
        const newId = "session_" + Date.now().toString();

        const res = await fetch(`/branch?parent_id=${encodeURIComponent(parentId)}&message_index=${idx + 1}&new_branch_id=${encodeURIComponent(newId)}`, { method: "POST" });
        if (res.ok) {
          currentSessionId = newId;
          await loadSessions();
          await loadHistory(newId);
          toggleBranchButtons();
        } else {
          alert("Failed to create branch.");
        }
      });
    });
  }

  const newSessionBtn = document.getElementById("newSessionBtn");
  if (newSessionBtn) {
    newSessionBtn.addEventListener("click", async () => {
      const newId = "session_" + Date.now().toString();
      const res = await fetch(`/branch?parent_id=${encodeURIComponent(currentSessionId)}&message_index=0&new_branch_id=${encodeURIComponent(newId)}`, { method: "POST" });
      if (res.ok) {
        currentSessionId = newId;
        await loadSessions();
        await loadHistory(newId);
        toggleBranchButtons();
      } else {
        alert("Failed to create new session.");
      }
    });
  }

  function toggleBranchButtons() {
    const isGeneral = agentSelect.value === "general";
    document.querySelectorAll(".branch-btn").forEach(btn => {
      btn.style.display = isGeneral ? "inline-block" : "none";
    });
  }

  strategySelect.addEventListener("change", toggleBranchButtons);

  async function loadHistory(sessionId) {
    try {
      const res = await fetch(`/history?session_id=${encodeURIComponent(sessionId)}`);
      if (res.ok) {
        const data = await res.json();
        chat.innerHTML = "";
        data.messages.forEach((msg, idx) => {
          addMessage(msg.role, msg.content, msg.role === "user" ? "You" : (agentSelect.options[agentSelect.selectedIndex]?.text || "Assistant"), idx);
        });
        if (data.facts) {
          addMessage("system", "System Facts restored: " + data.facts, "System");
        }
        toggleBranchButtons();
      }
    } catch (e) { console.error(e); }
  }



  function addMessage(role, text, label, idx = null) {
    const isSystem = role === "system";
    const cssRole = isSystem ? "assistant" : role;

    // Assign a default index for new messages if idx is null, using current child element count
    // Normally, this is somewhat crude, but functional for UI appending.
    if (idx === null) {
      idx = chat.querySelectorAll('.msg').length;
    }

    const msg = document.createElement("div");
    msg.className = "msg " + cssRole;
    if (role !== "system") {
      msg.setAttribute("data-msg-id", idx);
    }

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = label || (role === "user" ? "You" : "Assistant");

    if (role !== "system") {
      const branchBtn = document.createElement("button");
      branchBtn.className = "branch-btn";
      branchBtn.title = "Branch from here";
      branchBtn.style.fontSize = "0.7em";
      branchBtn.style.marginLeft = "8px";
      branchBtn.style.cursor = "pointer";
      branchBtn.textContent = "Branch";
      branchBtn.style.display = agentSelect.value === "general" ? "inline-block" : "none";
      meta.appendChild(branchBtn);
    }

    const content = document.createElement("div");
    content.className = "content";
    content.textContent = text || "";

    msg.appendChild(meta);
    msg.appendChild(content);
    chat.appendChild(msg);
    chat.scrollTop = chat.scrollHeight;

    bindBranchButtons();
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

    chat.scrollTop = chat.scrollHeight;

    const agentId = agentSelect.value || "android";
    const strategyId = strategySelect.value || "default";
    const sessionId = currentSessionId || "default";

    const url =
      "/stream?message=" +
      encodeURIComponent(text) +
      "&agent=" +
      encodeURIComponent(agentId) +
      "&strategy=" +
      encodeURIComponent(strategyId) +
      "&session_id=" +
      encodeURIComponent(sessionId);

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
        loadSessions(); // Reload sidebar to update titles
      }
      if (payload.error) {
        statusEl.textContent = "Error: " + payload.error;
        source.close();
      }
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
    const sessionId = currentSessionId || "default";
    const res = await fetch(`/clear?session_id=${encodeURIComponent(sessionId)}`, { method: "POST" });
    if (res.ok) {
      chat.innerHTML = "";
      statusEl.textContent = `Context cleared for branch ${sessionId}.`;
      statsEl.textContent = "";
      statsEl.style.display = "none";
      chat.scrollTop = 0;
    }
  });

  messageInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.querySelector('button[type="submit"]').click();
    }
  });

  function toggleStrategyControls() {
    const isGeneral = agentSelect.value === "general";
    strategySelect.style.display = isGeneral ? "inline-block" : "none";
    if (!isGeneral) {
      // Hide branch buttons as well
      document.querySelectorAll(".branch-btn").forEach(btn => {
        btn.style.display = "none";
      });
    } else {
      toggleBranchButtons();
    }
  }

  agentSelect.addEventListener("change", toggleStrategyControls);

  // Init
  loadSessions();
  bindBranchButtons();
  toggleStrategyControls();
});


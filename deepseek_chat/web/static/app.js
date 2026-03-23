// DeepSeek Web Chat — Client-side JS

document.addEventListener("DOMContentLoaded", () => {
  const chat = document.getElementById("chat");

  marked.setOptions({
    highlight: function (code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    }
  });

  function addCopyButtons(container) {
    const blocks = container.querySelectorAll("pre code");
    blocks.forEach((block) => {
      const pre = block.parentNode;
      if (pre.querySelector(".copy-btn")) return;

      const copyBtn = document.createElement("button");
      copyBtn.className = "copy-btn";
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(block.textContent);
        copyBtn.textContent = "Copied!";
        setTimeout(() => copyBtn.textContent = "Copy", 2000);
      });
      pre.style.position = "relative";
      pre.appendChild(copyBtn);
    });
  }
  const form = document.getElementById("chatForm");
  const messageInput = document.getElementById("message");
  const agentSelect = document.getElementById("agentSelect");

  const statusEl = document.getElementById("status");
  const statsEl = document.getElementById("stats");
  const clearBtn = document.getElementById("clearBtn");

  // Settings Modal elements
  const settingsBtn = document.getElementById("settingsBtn");
  const settingsModal = document.getElementById("settingsModal");
  const closeSettings = document.getElementById("closeSettings");
  const temperatureSlider = document.getElementById("temperatureSlider");
  const temperatureVal = document.getElementById("temperatureVal");
  const topPSlider = document.getElementById("topPSlider");
  const topPVal = document.getElementById("topPVal");
  // Memory Modal elements
  const memoryBtn = document.getElementById("memoryBtn");
  const memoryModal = document.getElementById("memoryModal");
  const closeMemory = document.getElementById("closeMemory");
  const tabWorking = document.getElementById("tabWorking");
  const tabLongTerm = document.getElementById("tabLongTerm");
  const panelWorking = document.getElementById("panelWorking");
  const panelLongTerm = document.getElementById("panelLongTerm");
  const workingInput = document.getElementById("workingInput");
  const addWorkingBtn = document.getElementById("addWorkingBtn");
  const workingList = document.getElementById("workingList");
  const longTermInput = document.getElementById("longTermInput");
  const addLongTermBtn = document.getElementById("addLongTermBtn");
  const longTermList = document.getElementById("longTermList");

  // Profile Modal elements
  const profileBtn = document.getElementById("profileBtn");
  const profileModal = document.getElementById("profileModal");
  const closeProfile = document.getElementById("closeProfile");
  const profileName = document.getElementById("profileName");
  const profileRole = document.getElementById("profileRole");
  const profileStyle = document.getElementById("profileStyle");
  const profileFormatting = document.getElementById("profileFormatting");
  const profileConstraints = document.getElementById("profileConstraints");
  const saveProfileBtn = document.getElementById("saveProfileBtn");
  const profileStatusMsg = document.getElementById("profileStatusMsg");

  // Invariants Modal elements
  const invariantsBtn = document.getElementById("invariantsBtn");
  const invariantsModal = document.getElementById("invariantsModal");
  const closeInvariants = document.getElementById("closeInvariants");
  const invariantInput = document.getElementById("invariantInput");
  const addInvariantBtn = document.getElementById("addInvariantBtn");
  const invariantsList = document.getElementById("invariantsList");

  const saveSettingsBtn = document.getElementById("saveSettingsBtn");
  const resetSettingsBtn = document.getElementById("resetSettingsBtn");
  const stopBtn = document.getElementById("stopBtn");
  const submitBtn = document.getElementById("submitBtn");

  // Provider toggle elements
  const providerDeepseekBtn = document.getElementById("providerDeepseekBtn");
  const providerOllamaBtn = document.getElementById("providerOllamaBtn");
  const providerBadge = document.getElementById("providerBadge");

  let currentProvider = "deepseek";

  function updateProviderUI(provider, model) {
    currentProvider = provider;
    const isOllama = provider === "ollama";
    providerDeepseekBtn.classList.toggle("active", !isOllama);
    providerOllamaBtn.classList.toggle("active", isOllama);
    providerBadge.textContent = isOllama ? `Ollama / ${model}` : `DeepSeek / ${model}`;
    providerBadge.classList.toggle("ollama", isOllama);
    messageInput.placeholder = isOllama ? "Message Ollama..." : "Message DeepSeek...";
  }

  async function initProvider() {
    try {
      const sid = currentSessionId || "default";
      const res = await fetch(`/config/provider?session_id=${encodeURIComponent(sid)}`);
      const data = await res.json();
      updateProviderUI(data.provider, data.model);
    } catch (e) { /* silently skip if backend unreachable */ }
  }

  async function switchProvider(provider) {
    try {
      const sid = currentSessionId || "default";
      const res = await fetch(`/config/provider?session_id=${encodeURIComponent(sid)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider })
      });
      const data = await res.json();
      if (data.ok) {
        updateProviderUI(data.provider, data.model);
        statusEl.textContent = "";
      } else {
        statusEl.textContent = data.error || "Provider switch failed";
        setTimeout(() => { statusEl.textContent = ""; }, 5000);
      }
    } catch (e) {
      statusEl.textContent = "Provider switch failed: " + e.message;
      setTimeout(() => { statusEl.textContent = ""; }, 5000);
    }
  }

  if (providerDeepseekBtn) {
    providerDeepseekBtn.addEventListener("click", () => switchProvider("deepseek"));
  }
  if (providerOllamaBtn) {
    providerOllamaBtn.addEventListener("click", () => switchProvider("ollama"));
  }

  initProvider();

  let currentSource = null;

  let customSettings = {
    temperature: null,
    top_p: null,
    agent: "general"
  };

  function loadSettings() {
    const saved = localStorage.getItem("deepseek_settings");
    if (saved) {
      try { customSettings = Object.assign(customSettings, JSON.parse(saved)); } catch (e) { }
    }
    if (customSettings.agent) {
      agentSelect.value = customSettings.agent;
    }
  }
  loadSettings();

  function updateSettingsUI() {
    if (customSettings.temperature !== null) {
      temperatureSlider.value = customSettings.temperature;
      temperatureVal.textContent = customSettings.temperature;
    } else {
      temperatureSlider.value = 1;
      temperatureVal.textContent = "Default";
    }
    if (customSettings.top_p !== null) {
      topPSlider.value = customSettings.top_p;
      topPVal.textContent = customSettings.top_p;
    } else {
      topPSlider.value = 1;
      topPVal.textContent = "Default";
    }
  }

  if (settingsBtn) {
    settingsBtn.addEventListener("click", () => {
      updateSettingsUI();
      settingsModal.style.display = "block";
    });
  }

  if (closeSettings) {
    closeSettings.addEventListener("click", () => {
      settingsModal.style.display = "none";
    });
  }

  temperatureSlider.addEventListener("input", (e) => {
    temperatureVal.textContent = e.target.value;
  });
  topPSlider.addEventListener("input", (e) => {
    topPVal.textContent = e.target.value;
  });

  // Memory Modal Logic
  if (memoryBtn) {
    memoryBtn.addEventListener("click", () => {
      loadMemory();
      memoryModal.style.display = "block";
    });
  }

  if (closeMemory) {
    closeMemory.addEventListener("click", () => {
      memoryModal.style.display = "none";
    });
  }

  tabWorking.addEventListener("click", () => {
    tabWorking.classList.add("active");
    tabWorking.style.color = "var(--text-primary)";
    tabWorking.style.fontWeight = "500";
    tabLongTerm.classList.remove("active");
    tabLongTerm.style.color = "var(--text-secondary)";
    tabLongTerm.style.fontWeight = "normal";
    panelWorking.style.display = "block";
    panelLongTerm.style.display = "none";
  });

  tabLongTerm.addEventListener("click", () => {
    tabLongTerm.classList.add("active");
    tabLongTerm.style.color = "var(--text-primary)";
    tabLongTerm.style.fontWeight = "500";
    tabWorking.classList.remove("active");
    tabWorking.style.color = "var(--text-secondary)";
    tabWorking.style.fontWeight = "normal";
    panelLongTerm.style.display = "block";
    panelWorking.style.display = "none";
  });

  async function loadMemory() {
    try {
      const res = await fetch(`/memory`);
      if (res.ok) {
        const data = await res.json();
        renderMemoryList(workingList, data.working_memory || [], "working");
        renderMemoryList(longTermList, data.long_term_memory || [], "long_term");
      }
    } catch (e) { console.error(e); }
  }

  function renderMemoryList(container, items, layer) {
    container.innerHTML = "";
    items.forEach((fact, index) => {
      const li = document.createElement("li");

      const span = document.createElement("span");
      span.textContent = fact;
      li.appendChild(span);

      const delBtn = document.createElement("button");
      delBtn.className = "memory-del-btn";
      delBtn.innerHTML = "🗑";
      delBtn.title = "Delete memory";
      delBtn.addEventListener("click", async () => {
        const res = await fetch(`/memory/${layer}/${index}`, { method: "DELETE" });
        if (res.ok) {
          loadMemory();
        }
      });
      li.appendChild(delBtn);

      container.appendChild(li);
    });
  }

  async function addMemoryItem(inputEl, layer) {
    const text = inputEl.value.trim();
    if (!text) return;

    try {
      const res = await fetch(`/memory/${layer}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text })
      });
      if (res.ok) {
        inputEl.value = "";
        loadMemory();
      }
    } catch (e) {
      console.error("Failed to add memory", e);
    }
  }

  addWorkingBtn.addEventListener("click", () => addMemoryItem(workingInput, "working"));
  workingInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addMemoryItem(workingInput, "working");
  });

  addLongTermBtn.addEventListener("click", () => addMemoryItem(longTermInput, "long_term"));
  longTermInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addMemoryItem(longTermInput, "long_term");
  });

  // Profile Modal Logic
  async function loadProfile() {
    try {
      const res = await fetch("/profile");
      if (res.ok) {
        const data = await res.json();
        profileName.value = data.name || "";
        profileRole.value = data.role || "";
        profileStyle.value = data.style_preferences || "";
        profileFormatting.value = data.formatting_rules || "";
        profileConstraints.value = data.constraints || "";
      }
    } catch (e) {
      console.error("Failed to load profile", e);
    }
  }

  if (profileBtn) {
    profileBtn.addEventListener("click", () => {
      loadProfile();
      profileModal.style.display = "block";
    });
  }

  if (closeProfile) {
    closeProfile.addEventListener("click", () => {
      profileModal.style.display = "none";
    });
  }

  if (saveProfileBtn) {
    saveProfileBtn.addEventListener("click", async () => {
      const payload = {
        name: profileName.value.trim(),
        role: profileRole.value.trim(),
        style_preferences: profileStyle.value.trim(),
        formatting_rules: profileFormatting.value.trim(),
        constraints: profileConstraints.value.trim()
      };

      try {
        const res = await fetch("/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          profileStatusMsg.style.opacity = "1";
          setTimeout(() => profileStatusMsg.style.opacity = "0", 2500);
        }
      } catch (e) {
        console.error("Failed to save profile", e);
      }
    });
  }

  // ── Invariants Modal Logic ────────────────────────────────
  async function loadInvariants() {
    try {
      const res = await fetch("/invariants");
      if (res.ok) {
        const data = await res.json();
        renderInvariantsList(data.invariants || []);
      }
    } catch (e) { console.error("Failed to load invariants", e); }
  }

  function renderInvariantsList(items) {
    invariantsList.innerHTML = "";
    items.forEach((rule, index) => {
      const li = document.createElement("li");

      const span = document.createElement("span");
      span.textContent = rule;
      li.appendChild(span);

      const delBtn = document.createElement("button");
      delBtn.className = "memory-del-btn";
      delBtn.innerHTML = "🗑";
      delBtn.title = "Delete invariant";
      delBtn.addEventListener("click", async () => {
        const res = await fetch(`/invariants/${index}`, { method: "DELETE" });
        if (res.ok) loadInvariants();
      });
      li.appendChild(delBtn);

      invariantsList.appendChild(li);
    });
  }

  async function addInvariant() {
    const text = invariantInput.value.trim();
    if (!text) return;
    try {
      const res = await fetch("/invariants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text })
      });
      if (res.ok) {
        invariantInput.value = "";
        loadInvariants();
      }
    } catch (e) { console.error("Failed to add invariant", e); }
  }

  if (invariantsBtn) {
    invariantsBtn.addEventListener("click", () => {
      loadInvariants();
      invariantsModal.style.display = "block";
    });
  }

  if (closeInvariants) {
    closeInvariants.addEventListener("click", () => {
      invariantsModal.style.display = "none";
    });
  }

  addInvariantBtn.addEventListener("click", () => addInvariant());
  invariantInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addInvariant();
  });

  // ── MCP Modal Logic ───────────────────────────────────────
  const mcpBtn = document.getElementById("mcpBtn");
  const mcpModal = document.getElementById("mcpModal");
  const closeMcp = document.getElementById("closeMcp");
  const mcpServersList = document.getElementById("mcpServersList");
  const addMcpForm = document.getElementById("addMcpForm");

  async function loadMcpServers() {
    try {
      const res = await fetch("/mcp");
      if (res.ok) {
        const data = await res.json();
        renderMcpList(data.servers, data.tools || []);
      }
    } catch (e) { console.error("Failed to load MCP servers", e); }
  }

  function renderMcpList(servers, allTools) {
    mcpServersList.innerHTML = "";
    if (servers.length === 0) {
      mcpServersList.innerHTML = '<div style="color: var(--text-secondary); font-size: 13px; text-align: center; padding: 20px 0;">No MCP servers configured yet.</div>';
      return;
    }

    servers.forEach(server => {
      const isConnecting = server.enabled && allTools.filter(t => t.function.name.startsWith(`${server.id}__`)).length === 0;

      const container = document.createElement("div");
      container.className = "mcp-server-card";

      const header = document.createElement("div");
      header.className = "mcp-server-header";

      const titlePanel = document.createElement("div");
      titlePanel.className = "mcp-server-title";

      const statusIcon = server.enabled ? (isConnecting ? "⏳" : "🟢") : "⚪";
      titlePanel.innerHTML = `<span style="font-size: 16px;">${statusIcon}</span> ${server.name} <span class="mcp-server-status ${server.enabled ? 'mcp-status-on' : 'mcp-status-off'}">${server.enabled ? (isConnecting ? 'Connecting...' : 'Connected') : 'Disabled'}</span>`;

      const controls = document.createElement("div");
      controls.className = "mcp-server-actions";

      // Toggle switch
      const switchLabel = document.createElement("label");
      switchLabel.className = "mcp-toggle-switch";
      switchLabel.title = server.enabled ? "Disable Server" : "Enable Server";

      const switchInput = document.createElement("input");
      switchInput.type = "checkbox";
      switchInput.checked = server.enabled;
      switchInput.addEventListener("change", async () => {
        const newState = switchInput.checked;
        switchInput.disabled = true;
        const res = await fetch(`/mcp/${encodeURIComponent(server.id)}/toggle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: newState })
        });
        if (res.ok) loadMcpServers();
        else switchInput.disabled = false;
      });

      const slider = document.createElement("span");
      slider.className = "mcp-toggle-slider";

      switchLabel.appendChild(switchInput);
      switchLabel.appendChild(slider);

      const delBtn = document.createElement("button");
      delBtn.className = "memory-del-btn";
      delBtn.innerHTML = "🗑";
      delBtn.title = `Delete ${server.name}`;
      delBtn.addEventListener("click", async () => {
        if (confirm(`Delete MCP server ${server.name}?`)) {
          const res = await fetch(`/mcp/${encodeURIComponent(server.id)}`, { method: "DELETE" });
          if (res.ok) loadMcpServers();
        }
      });

      controls.appendChild(switchLabel);
      controls.appendChild(delBtn);

      header.appendChild(titlePanel);
      header.appendChild(controls);
      container.appendChild(header);

      const cmdSpan = document.createElement("div");
      cmdSpan.className = "mcp-server-cmd";
      const isHttp = server.transport === "sse" || server.transport === "streamable_http";
      cmdSpan.textContent = isHttp
        ? `[${server.transport}] ${server.url || ""}`
        : `$ ${server.command || ""} ${(server.args || []).join(" ")}`;
      container.appendChild(cmdSpan);

      // Tools List
      if (server.enabled) {
        const serverTools = allTools.filter(t => t.function.name.startsWith(`${server.id}__`));
        if (serverTools.length > 0) {
          const toolsDiv = document.createElement("div");
          toolsDiv.className = "mcp-tools-list";
          serverTools.forEach(t => {
            const originalName = t.function.name.replace(`${server.id}__`, "");
            toolsDiv.innerHTML += `<span class="mcp-tool-badge">🔧 ${originalName}</span>`;
          });
          container.appendChild(toolsDiv);
        }
      }

      mcpServersList.appendChild(container);
    });
  }

  if (mcpBtn) {
    mcpBtn.addEventListener("click", () => {
      loadMcpServers();
      mcpModal.style.display = "block";
    });
  }

  if (closeMcp) {
    closeMcp.addEventListener("click", () => {
      mcpModal.style.display = "none";
    });
  }

  // Transport selector: toggle stdio vs http fields
  const mcpTransportSelect = document.getElementById("mcpTransport");
  if (mcpTransportSelect) {
    mcpTransportSelect.addEventListener("change", () => {
      const isHttp = mcpTransportSelect.value !== "stdio";
      document.getElementById("mcpStdioFields").style.display = isHttp ? "none" : "";
      document.getElementById("mcpHttpFields").style.display = isHttp ? "" : "none";
    });
  }

  if (addMcpForm) {
    addMcpForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const idInput = document.getElementById("mcpId").value.trim();
      const nameInput = document.getElementById("mcpName").value.trim();
      const transport = (document.getElementById("mcpTransport")?.value || "stdio");
      const isHttp = transport !== "stdio";

      if (!idInput || !nameInput) return;

      function parseKvPairs(str) {
        const obj = {};
        (str || "").split(',').forEach(pair => {
          const [k, ...v] = pair.split('=');
          if (k && k.trim()) obj[k.trim()] = v.join('=').trim();
        });
        return obj;
      }

      let payload;
      if (isHttp) {
        const urlInput = document.getElementById("mcpUrl").value.trim();
        const headersInput = (document.getElementById("mcpHeaders")?.value || "").trim();
        if (!urlInput) return;
        payload = {
          id: idInput.toLowerCase().replace(/[^a-z0-9_]/g, "_"),
          name: nameInput,
          transport,
          url: urlInput,
          headers: parseKvPairs(headersInput),
          enabled: true
        };
      } else {
        const cmdInput = document.getElementById("mcpCommand").value.trim();
        const argsInput = document.getElementById("mcpArgs").value.trim();
        const envInput = (document.getElementById("mcpEnv")?.value || "").trim();
        if (!cmdInput) return;
        payload = {
          id: idInput.toLowerCase().replace(/[^a-z0-9_]/g, "_"),
          name: nameInput,
          transport: "stdio",
          command: cmdInput,
          args: argsInput ? argsInput.split(/\s+/) : [],
          env: parseKvPairs(envInput),
          enabled: true
        };
      }

      try {
        const res = await fetch("/mcp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          addMcpForm.reset();
          if (mcpTransportSelect) {
            mcpTransportSelect.value = "stdio";
            document.getElementById("mcpStdioFields").style.display = "";
            document.getElementById("mcpHttpFields").style.display = "none";
          }
          loadMcpServers();
        } else {
          alert("Failed to add MCP server");
        }
      } catch (err) {
        console.error("Error adding MCP server", err);
      }
    });
  }

  saveSettingsBtn.addEventListener("click", () => {
    customSettings.temperature = parseFloat(temperatureSlider.value);
    customSettings.top_p = parseFloat(topPSlider.value);
    customSettings.agent = agentSelect.value;
    localStorage.setItem("deepseek_settings", JSON.stringify(customSettings));
    settingsModal.style.display = "none";
  });

  resetSettingsBtn.addEventListener("click", () => {
    customSettings = { temperature: null, top_p: null, agent: "general" };
    localStorage.removeItem("deepseek_settings");
    agentSelect.value = customSettings.agent;
    updateSettingsUI();
  });

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
            await initProvider();
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
      btn.style.display = isGeneral ? "" : "none";
    });
  }



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

    const msgInner = document.createElement("div");
    msgInner.className = "msg-inner";

    const meta = document.createElement("div");
    meta.className = "meta";

    const labelSpan = document.createElement("span");
    labelSpan.textContent = label || (role === "user" ? "You" : "Assistant");
    meta.appendChild(labelSpan);

    if (role !== "system") {
      const branchBtn = document.createElement("button");
      branchBtn.className = "branch-btn";
      branchBtn.title = "Branch from here";
      branchBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"></line><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M18 9a9 9 0 0 1-9 9"></path></svg>';
      branchBtn.style.display = agentSelect.value === "general" ? "" : "none";
      meta.appendChild(branchBtn);
    }

    msgInner.appendChild(meta);

    const content = document.createElement("div");
    content.className = "content markdown-body";
    content._rawText = text || "";
    if (text) {
      content.innerHTML = marked.parse(content._rawText);
      addCopyButtons(content);
    }
    msgInner.appendChild(content);

    msg.appendChild(msgInner);
    chat.appendChild(msg);
    chat.scrollTop = chat.scrollHeight;

    bindBranchButtons();
    return content;
  }

  function formatStats(stats) {
    if (!stats) return "";
    const parts = [];

    if (stats.duration_ms != null) {
      parts.push(`⏱ ${(stats.duration_ms / 1000).toFixed(1)}s`);
    }

    let totalTokens = null;
    if (stats.total_tokens != null) {
      totalTokens = stats.total_tokens;
    } else if (stats.tokens_local) {
      totalTokens = stats.tokens_local.request + stats.tokens_local.history + stats.tokens_local.response;
    }

    if (totalTokens != null) {
      parts.push(`🔤 ${totalTokens} ctx`);
    }

    if (stats.cost_usd != null) {
      let costStr = `💰 $${stats.cost_usd.toFixed(5)}`;
      if (stats.session_cost_usd != null) {
        costStr += ` (Total $${stats.session_cost_usd.toFixed(4)})`;
      }
      parts.push(costStr);
    } else if (stats.session_cost_usd != null) {
      parts.push(`💰 Total $${stats.session_cost_usd.toFixed(4)}`);
    }

    return parts.join(" • ");
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = messageInput.value.trim();
    if (!text) return;

    const sessionId = currentSessionId || "default";

    // In Agent mode, auto-start task if idle
    if (inputMode === "agent") {
      try {
        const taskRes = await fetch(`/task?session_id=${encodeURIComponent(sessionId)}`);
        if (taskRes.ok) {
          const taskData = await taskRes.json();
          if (taskData.phase === "idle") {
            const startRes = await fetch(`/task/start?session_id=${encodeURIComponent(sessionId)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ goal: text })
            });
            if (startRes.ok) {
              const startData = await startRes.json();
              if (startData.state) renderTaskState(startData.state);
            }
          }
        }
      } catch (err) { console.error("Task auto-start failed", err); }
    }

    addMessage("user", text, "You");
    const agentLabel =
      agentSelect.options[agentSelect.selectedIndex]?.text || "Assistant";
    const assistantContent = addMessage("assistant", "", agentLabel);
    messageInput.value = "";
    messageInput.style.height = "auto";
    statusEl.textContent = "Streaming...";
    statsEl.textContent = "";
    statsEl.style.display = "none";

    chat.scrollTop = chat.scrollHeight;

    const agentId = agentSelect.value || "general";

    let url =
      "/stream?message=" +
      encodeURIComponent(text) +
      "&agent=" +
      encodeURIComponent(agentId) +
      "&session_id=" +
      encodeURIComponent(sessionId);

    if (customSettings.temperature !== null) {
      url += "&temperature=" + encodeURIComponent(customSettings.temperature);
    }
    if (customSettings.top_p !== null) {
      url += "&top_p=" + encodeURIComponent(customSettings.top_p);
    }

    submitBtn.style.display = "none";
    stopBtn.style.display = "inline-block";

    // Disable inputs and task actions during stream
    messageInput.disabled = true;
    document.querySelectorAll(".task-btn").forEach(btn => btn.disabled = true);

    const source = new EventSource(url);
    currentSource = source;

    source.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.delta) {
        assistantContent._rawText += payload.delta;
        // Strip internal task markers before displaying
        const displayText = assistantContent._rawText
          .replace(/\[PLAN_READY\]/gi, "")
          .replace(/\[STEP_DONE\]/gi, "")
          .replace(/\[READY_FOR_VALIDATION\]/gi, "");
        assistantContent.innerHTML = marked.parse(displayText);
        addCopyButtons(assistantContent);
        chat.scrollTop = chat.scrollHeight;
      }
      if (payload.stats) {
        const statsText = formatStats(payload.stats);
        statsEl.textContent = statsText;
        statsEl.style.display = statsText ? "block" : "none";
      }
      if (payload.task_state) {
        renderTaskState(payload.task_state);
      }
      if (payload.done) {
        statusEl.textContent = "";
        source.close();
        currentSource = null;
        submitBtn.style.display = "inline-block";
        stopBtn.style.display = "none";

        // Re-enable inputs
        messageInput.disabled = false;
        document.querySelectorAll(".task-btn").forEach(btn => btn.disabled = false);

        loadSessions(); // Reload sidebar to update titles

        // Reliably refresh task state after stream ends (after_stream hooks have run)
        if (inputMode === "agent") {
          loadTaskState();
        }
      }
      if (payload.error) {
        statusEl.textContent = "Error: " + payload.error;
        source.close();
        currentSource = null;
        submitBtn.style.display = "inline-block";
        stopBtn.style.display = "none";

        // Re-enable inputs
        messageInput.disabled = false;
        document.querySelectorAll(".task-btn").forEach(btn => btn.disabled = false);
      }
      chat.scrollTop = chat.scrollHeight;
    };

    source.onerror = () => {
      statusEl.textContent = "Stream connection error.";
      source.close();
      currentSource = null;
      submitBtn.style.display = "inline-block";
      stopBtn.style.display = "none";

      // Re-enable inputs
      messageInput.disabled = false;
      document.querySelectorAll(".task-btn").forEach(btn => btn.disabled = false);
    };
  });

  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      if (currentSource) {
        currentSource.close();
        currentSource = null;
        statusEl.textContent = "Generation stopped by user.";
        submitBtn.style.display = "inline-block";
        stopBtn.style.display = "none";

        // Re-enable inputs
        messageInput.disabled = false;
        document.querySelectorAll(".task-btn").forEach(btn => btn.disabled = false);

        loadSessions(); // Optional: reload sessions
        // Allow time for the backend to detect the disconnect and pause the task
        setTimeout(loadTaskState, 300);
      }
    });
  }

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

  messageInput.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = (this.scrollHeight) + "px";
    if (this.value === "") {
      this.style.height = "auto";
    }
  });

  // Re-render pre-rendered messages with Marked
  document.querySelectorAll(".msg .content").forEach(el => {
    if (el._rawText) {
      el.classList.add("markdown-body");
      el.innerHTML = marked.parse(el._rawText);
      addCopyButtons(el);
    }
  });

  // Init
  loadSessions();
  bindBranchButtons();

  // ── Chat/Agent Mode Toggle ─────────────────────────────
  let inputMode = "chat"; // "chat" | "agent"
  const modeChatBtn = document.getElementById("modeChatBtn");
  const modeAgentBtn = document.getElementById("modeAgentBtn");
  const taskPanel = document.getElementById("taskPanel");
  const taskName = document.getElementById("taskName");
  const taskPhaseBadge = document.getElementById("taskPhaseBadge");
  const taskProgressFill = document.getElementById("taskProgressFill");
  const taskStepsList = document.getElementById("taskStepsList");
  const taskActions = document.getElementById("taskActions");
  const taskResetBtn = document.getElementById("taskResetBtn");
  const taskCollapseBtn = document.getElementById("taskCollapseBtn");
  const taskBody = document.getElementById("taskBody");

  function setMode(mode) {
    inputMode = mode;
    modeChatBtn.classList.toggle("active", mode === "chat");
    modeAgentBtn.classList.toggle("active", mode === "agent");
    messageInput.placeholder = mode === "agent"
      ? "Describe a task for the agent..."
      : "Message DeepSeek...";
    if (mode === "agent") {
      loadTaskState();
    } else {
      taskPanel.classList.remove("visible");
    }
  }

  modeChatBtn.addEventListener("click", () => setMode("chat"));
  modeAgentBtn.addEventListener("click", () => setMode("agent"));

  // ── Task State Panel ───────────────────────────────────

  async function loadTaskState() {
    try {
      const sessionId = currentSessionId || "default";
      const res = await fetch(`/task?session_id=${encodeURIComponent(sessionId)}`);
      if (!res.ok) return;
      const state = await res.json();
      renderTaskState(state);
    } catch (e) { console.error("Failed to load task state", e); }
  }

  function renderTaskState(state) {
    if (inputMode !== "agent") return;

    const phase = state.phase || "idle";

    if (phase === "idle") {
      taskPanel.classList.remove("visible");
      return;
    }

    taskPanel.classList.add("visible");

    // Title + badge
    taskName.textContent = state.task || "—";
    taskPhaseBadge.textContent = phase;
    taskPhaseBadge.className = "task-phase-badge " + phase;

    // Progress
    let pct;
    if (phase === "done" || phase === "validation") {
      pct = 100;
    } else {
      pct = state.total_steps > 0
        ? Math.round((state.current_step / state.total_steps) * 100)
        : 0;
    }
    taskProgressFill.style.width = pct + "%";

    // Steps
    taskStepsList.innerHTML = "";
    if (state.plan && state.plan.length > 0) {
      state.plan.forEach((step, i) => {
        const li = document.createElement("li");
        const marker = document.createElement("span");
        marker.className = "step-marker";

        if (i < state.current_step) {
          li.className = "done";
          marker.textContent = "✅";
        } else if (i === state.current_step && phase === "execution") {
          li.className = "active";
          marker.textContent = "👉";
        } else {
          li.className = "pending";
          marker.textContent = "⬚";
        }

        const text = document.createElement("span");
        text.textContent = `${i + 1}. ${step}`;

        li.appendChild(marker);
        li.appendChild(text);
        taskStepsList.appendChild(li);
      });
    }

    // Action buttons — driven by allowed_transitions from the server
    taskActions.innerHTML = "";
    const allowed = state.allowed_transitions || [];
    const addBtn = (label, cls, handler) => {
      const btn = document.createElement("button");
      btn.className = `task-btn ${cls}`;
      btn.textContent = label;

      // Disable buttons if a stream is currently active
      if (currentSource) {
        btn.disabled = true;
      }

      btn.addEventListener("click", handler);
      taskActions.appendChild(btn);
    };

    if (phase === "planning" && allowed.includes("execution") && state.plan && state.plan.length > 0) {
      addBtn("✓ Approve Plan", "primary", async () => {
        await taskAction("/task/approve");
        sendAutoMessage("Plan approved. Proceed with execution.");
      });
    }
    if (phase === "validation" && allowed.includes("done")) {
      addBtn("✓ Complete", "primary", async () => {
        await taskAction("/task/complete");
        sendAutoMessage("Task validated and completed. Provide a summary.");
      });
    }
    if (allowed.includes("paused")) {
      addBtn("⏸ Pause", "", () => taskAction("/task/pause"));
    }
    if (phase === "paused" && allowed.length > 0) {
      addBtn("▶ Resume", "primary", async () => {
        await taskAction("/task/resume");
        sendAutoMessage("Задача снята с паузы. Продолжай с того места, где остановился.");
      });
    }

  }

  async function taskAction(endpoint) {
    try {
      const sessionId = currentSessionId || "default";
      const res = await fetch(`${endpoint}?session_id=${encodeURIComponent(sessionId)}`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        if (data.state) renderTaskState(data.state);
      }
    } catch (e) { console.error("Task action failed", e); }
  }

  // Auto-send a message to the agent (used by Approve / Complete buttons)
  function sendAutoMessage(text) {
    messageInput.value = text;
    form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  }

  // Collapse/expand task panel body
  taskCollapseBtn.addEventListener("click", () => {
    taskBody.classList.toggle("collapsed");
    taskCollapseBtn.classList.toggle("rotated");
    taskCollapseBtn.title = taskBody.classList.contains("collapsed") ? "Expand" : "Collapse";
  });

  // Reset task
  taskResetBtn.addEventListener("click", async () => {
    const sessionId = currentSessionId || "default";
    await fetch(`/task/reset?session_id=${encodeURIComponent(sessionId)}`, { method: "POST" });
    taskPanel.classList.remove("visible");
  });

  // Reload task state when switching sessions (in agent mode)
  const origLoadHistory = loadHistory;
  loadHistory = async function (sessionId) {
    await origLoadHistory(sessionId);
    if (inputMode === "agent") {
      await loadTaskState();
    }
  };

  // Reload task state after /clear
  clearBtn.addEventListener("click", () => {
    if (inputMode === "agent") {
      setTimeout(loadTaskState, 300);
    }
  });

  // ── Scheduler Modal Logic ─────────────────────────────────
  const schedulerBtn = document.getElementById("schedulerBtn");
  const schedulerModal = document.getElementById("schedulerModal");
  const closeScheduler = document.getElementById("closeScheduler");
  const schedulerStats = document.getElementById("schedulerStats");
  const schedulerTasksList = document.getElementById("schedulerTasksList");
  const schedulerResultsList = document.getElementById("schedulerResultsList");
  let schedulerRefreshInterval = null;

  async function loadSchedulerData() {
    try {
      const res = await fetch("/scheduler/status");
      if (res.ok) {
        const data = await res.json();
        renderSchedulerStats(data.summary || {});
        renderSchedulerTasks(data.tasks || []);
        renderSchedulerResults(data.summary?.recent_results || []);
      }
    } catch (e) { console.error("Failed to load scheduler data", e); }
  }

  function renderSchedulerStats(summary) {
    schedulerStats.innerHTML = `
      <div class="scheduler-stat-card">
        <div class="scheduler-stat-value">${summary.total_tasks || 0}</div>
        <div class="scheduler-stat-label">Total</div>
      </div>
      <div class="scheduler-stat-card">
        <div class="scheduler-stat-value" style="color: #3fb950;">${summary.active || 0}</div>
        <div class="scheduler-stat-label">Active</div>
      </div>
      <div class="scheduler-stat-card">
        <div class="scheduler-stat-value" style="color: #d29922;">${summary.paused || 0}</div>
        <div class="scheduler-stat-label">Paused</div>
      </div>
      <div class="scheduler-stat-card">
        <div class="scheduler-stat-value" style="color: #92abec;">${summary.completed || 0}</div>
        <div class="scheduler-stat-label">Completed</div>
      </div>
    `;
  }

  function renderSchedulerTasks(tasks) {
    if (tasks.length === 0) {
      schedulerTasksList.innerHTML = '<div class="scheduler-empty">No tasks yet. Ask the agent to create a reminder or periodic task.</div>';
      return;
    }

    schedulerTasksList.innerHTML = "";
    tasks.forEach(task => {
      const statusClass = `scheduler-status-${task.status}`;
      const statusIcons = { active: "🟢", paused: "⏸️", completed: "✅", failed: "❌" };
      const typeLabels = { reminder: "⏰ Reminder", periodic_collect: "📊 Collect", periodic_summary: "📋 Summary" };

      const card = document.createElement("div");
      card.className = "scheduler-task-card";

      const nextRun = task.next_run_at ? new Date(task.next_run_at).toLocaleString() : "—";
      const lastRun = task.last_run_at ? new Date(task.last_run_at).toLocaleString() : "—";

      card.innerHTML = `
        <div class="scheduler-task-header">
          <div class="scheduler-task-name">
            ${statusIcons[task.status] || "❓"} ${task.name}
            <span class="scheduler-task-id">${task.id}</span>
          </div>
          <div class="scheduler-task-actions" id="actions-${task.id}"></div>
        </div>
        <div class="scheduler-task-meta">
          <span class="scheduler-type-badge">${typeLabels[task.type] || task.type}</span>
          <span class="scheduler-status-badge ${statusClass}">${task.status}</span>
          <span>📅 ${task.schedule}</span>
        </div>
        <div class="scheduler-task-meta" style="opacity: 0.7;">
          <span>Next: ${nextRun}</span>
          <span>Last: ${lastRun}</span>
        </div>
      `;

      const actionsEl = card.querySelector(`#actions-${task.id}`);

      if (task.status === "active") {
        const pauseBtn = document.createElement("button");
        pauseBtn.textContent = "⏸ Pause";
        pauseBtn.addEventListener("click", async () => {
          await fetch(`/scheduler/task/${task.id}/pause`, { method: "POST" });
          loadSchedulerData();
        });
        actionsEl.appendChild(pauseBtn);
      }

      if (task.status === "paused") {
        const resumeBtn = document.createElement("button");
        resumeBtn.textContent = "▶ Resume";
        resumeBtn.addEventListener("click", async () => {
          await fetch(`/scheduler/task/${task.id}/resume`, { method: "POST" });
          loadSchedulerData();
        });
        actionsEl.appendChild(resumeBtn);
      }

      const delBtn = document.createElement("button");
      delBtn.textContent = "🗑 Delete";
      delBtn.className = "danger";
      delBtn.addEventListener("click", async () => {
        if (confirm(`Delete task "${task.name}"?`)) {
          await fetch(`/scheduler/task/${task.id}`, { method: "DELETE" });
          loadSchedulerData();
        }
      });
      actionsEl.appendChild(delBtn);

      schedulerTasksList.appendChild(card);
    });
  }

  function renderSchedulerResults(results) {
    if (results.length === 0) {
      schedulerResultsList.innerHTML = '<div class="scheduler-empty">No results yet.</div>';
      return;
    }

    schedulerResultsList.innerHTML = "";
    results.forEach(r => {
      const item = document.createElement("div");
      item.className = "scheduler-result-item";
      const time = new Date(r.executed_at).toLocaleString();
      const resultText = (r.result || "").substring(0, 300);
      item.innerHTML = `
        <div class="scheduler-result-header">
          <span class="scheduler-result-task-name">${r.task_name || "—"}</span>
          <span class="scheduler-result-time">${time}</span>
        </div>
        <div class="scheduler-result-content">${resultText}</div>
      `;
      schedulerResultsList.appendChild(item);
    });
  }

  if (schedulerBtn) {
    schedulerBtn.addEventListener("click", () => {
      loadSchedulerData();
      schedulerModal.style.display = "block";
      // Auto-refresh every 15 seconds while modal is open
      schedulerRefreshInterval = setInterval(loadSchedulerData, 15000);
    });
  }

  if (closeScheduler) {
    closeScheduler.addEventListener("click", () => {
      schedulerModal.style.display = "none";
      if (schedulerRefreshInterval) {
        clearInterval(schedulerRefreshInterval);
        schedulerRefreshInterval = null;
      }
    });
  }

  // ── Scheduler Notification Polling ────────────────────────
  const toastContainer = document.getElementById("schedulerToastContainer");
  let lastNotificationCheck = new Date().toISOString();

  function showSchedulerToast(result) {
    const toast = document.createElement("div");
    toast.className = "scheduler-toast";

    const taskName = result.task_name || "Scheduler";
    const time = new Date(result.executed_at).toLocaleTimeString();
    const text = (result.result || "").substring(0, 250);

    toast.innerHTML = `
      <div class="scheduler-toast-header">
        <span class="scheduler-toast-title">📅 ${taskName}</span>
        <span class="scheduler-toast-time">${time}</span>
      </div>
      <div class="scheduler-toast-body">${text}</div>
    `;

    toastContainer.appendChild(toast);

    // Auto-dismiss after 8 seconds
    setTimeout(() => {
      toast.classList.add("fade-out");
      setTimeout(() => toast.remove(), 400);
    }, 8000);
  }

  function injectSchedulerMessage(result) {
    const taskName = result.task_name || "Scheduler";
    const text = result.result || "";
    const msg = `**📅 ${taskName}**\n\n${text}`;
    addMessage("assistant", msg, "Scheduler");
  }

  async function checkSchedulerNotifications() {
    try {
      const res = await fetch(`/scheduler/notifications?since=${encodeURIComponent(lastNotificationCheck)}`);
      if (res.ok) {
        const data = await res.json();
        if (data.results && data.results.length > 0) {
          data.results.forEach(r => {
            showSchedulerToast(r);
            injectSchedulerMessage(r);
          });
          // Update the timestamp to the latest result
          lastNotificationCheck = data.results[data.results.length - 1].executed_at;
        }
      }
    } catch (e) { /* silent */ }
  }

  // Poll every 15 seconds for new notifications
  setInterval(checkSchedulerNotifications, 15000);
});

    const modelSelect = document.querySelector("#modelSelect");
    const modelList = document.querySelector("#modelList");
    const historyList = document.querySelector("#historyList");
    const historyCount = document.querySelector("#historyCount");
    const statusDot = document.querySelector("#statusDot");
    const statusText = document.querySelector("#statusText");
    const messagesElement = document.querySelector("#messages");
    const welcome = document.querySelector("#welcome");
    const promptInput = document.querySelector("#promptInput");
    const sendButton = document.querySelector("#sendButton");
    const attachmentButton = document.querySelector("#attachmentButton");
    const attachmentInput = document.querySelector("#attachmentInput");
    const attachmentList = document.querySelector("#attachmentList");
    const themeToggle = document.querySelector("#themeToggle");
    const authThemeToggle = document.querySelector("#authThemeToggle");
    const serviceError = document.querySelector("#serviceError");
    const sendError = document.querySelector("#sendError");
    const authScreen = document.querySelector("#authScreen");
    const appShell = document.querySelector("#appShell");
    const authForm = document.querySelector("#authForm");
    const authTitle = document.querySelector("#authTitle");
    const authUsername = document.querySelector("#authUsername");
    const authPassword = document.querySelector("#authPassword");
    const authSubmit = document.querySelector("#authSubmit");
    const authSwitch = document.querySelector("#authSwitch");
    const authError = document.querySelector("#authError");
    const currentUsername = document.querySelector("#currentUsername");
    let conversation = [];
    let currentChatId = null;
    let busy = false;
    let authMode = "login";
    let selectedFiles = [];
    const modelCapabilities = new Map();

    function setTheme(theme) {
      const isDark = theme === "dark";
      document.documentElement.dataset.theme = isDark ? "dark" : "light";
      [themeToggle, authThemeToggle].forEach((toggle) => {
        toggle.textContent = isDark ? "☀ 浅色模式" : "☾ 深色模式";
        toggle.setAttribute("aria-label", isDark ? "切换到浅色主题" : "切换到深色主题");
        toggle.setAttribute("aria-pressed", String(isDark));
      });
      document.querySelector('meta[name="theme-color"]').content = isDark ? "#10171c" : "#eaf3f6";
      localStorage.setItem("ollama-theme", isDark ? "dark" : "light");
    }

    function displayName(name) {
      if (name.startsWith("llama32-1b-local")) return "Llama 3.2 · 1B";
      if (name.startsWith("llama32-3b-local")) return "Llama 3.2 · 3B";
      return name;
    }

    function setConnection(online, text) {
      statusDot.classList.toggle("online", online);
      statusText.textContent = text;
    }

    function showError(element, text) {
      element.textContent = text;
      element.hidden = false;
    }

    function showAuth(error = "") {
      appShell.hidden = true;
      authScreen.hidden = false;
      authError.textContent = error;
      authError.hidden = !error;
    }

    function showApp(user) {
      authScreen.hidden = true;
      appShell.hidden = false;
      currentUsername.textContent = user.username;
      loadModels();
    }

    function setAuthMode(mode) {
      authMode = mode;
      const registering = mode === "register";
      authTitle.textContent = registering ? "创建本地账号" : "登录本地工作台";
      authSubmit.textContent = registering ? "注册并登录" : "登录";
      authSwitch.textContent = registering ? "已有账号？返回登录" : "没有账号？注册新账号";
      authPassword.autocomplete = registering ? "new-password" : "current-password";
      authError.hidden = true;
    }

    async function handleUnauthorized(response) {
      if (response.status !== 401) return false;
      localStorage.removeItem("ollama-current-chat");
      currentChatId = null;
      conversation = [];
      clearAttachments();
      showAuth("登录状态已失效，请重新登录。");
      return true;
    }

    async function checkSession() {
      try {
        const response = await fetch("/api/session", { credentials: "same-origin" });
        const payload = await response.json();
        if (payload.user) showApp(payload.user);
        else showAuth();
      } catch (error) {
        showAuth(`无法连接网页服务：${error.message}`);
      }
    }

    function clearAttachments() {
      selectedFiles = [];
      attachmentInput.value = "";
      renderAttachments();
    }

    async function submitAuth(event) {
      event.preventDefault();
      authError.hidden = true;
      authSubmit.disabled = true;
      try {
        const response = await fetch(authMode === "register" ? "/api/register" : "/api/login", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: authUsername.value.trim(), password: authPassword.value }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "认证失败。");
        authPassword.value = "";
        localStorage.removeItem("ollama-current-chat");
        currentChatId = null;
        conversation = [];
        showApp(payload.user);
      } catch (error) {
        showAuth(error.message);
      } finally {
        authSubmit.disabled = false;
      }
    }

    async function logout() {
      try {
        await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
      } finally {
        localStorage.removeItem("ollama-current-chat");
        currentChatId = null;
        conversation = [];
        clearAttachments();
        authForm.reset();
        setAuthMode("login");
        showAuth();
      }
    }

    async function loadModels() {
      try {
        const response = await fetch("/api/models");
        if (await handleUnauthorized(response)) return;
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "读取模型列表失败。");
        const models = Array.isArray(payload.models) ? payload.models : [];
        modelSelect.replaceChildren();
        modelList.replaceChildren();
        modelCapabilities.clear();
        for (const model of models) {
          const name = model.name || model.model;
          if (!name) continue;
          modelCapabilities.set(
            name,
            Array.isArray(model.capabilities) ? model.capabilities : [],
          );
          modelSelect.add(new Option(displayName(name), name));
          const item = document.createElement("div");
          item.className = "model-item";
          item.dataset.model = name;
          const title = document.createElement("strong");
          title.textContent = displayName(name);
          const detail = document.createElement("span");
          const size = Number(model.size);
          detail.textContent = Number.isFinite(size) && size > 0 ? `${(size / 1_000_000_000).toFixed(1)} GB · 已就绪` : "已就绪";
          item.append(title, detail);
          modelList.append(item);
        }
        if (models.some((model) => model.capabilities_error)) {
          showError(serviceError, "部分模型的附件能力无法读取，仍可进行文本对话。");
        } else {
          serviceError.hidden = true;
        }
        if (modelSelect.options.length === 0) {
          modelSelect.add(new Option("没有可用模型", ""));
          modelSelect.disabled = true;
          modelList.innerHTML = '<div class="model-item"><strong>尚无已安装模型</strong><span>请先在 Ollama 中安装模型</span></div>';
          setConnection(true, "OLLAMA 在线 · 暂无模型");
          return;
        }
        modelSelect.disabled = false;
        sendButton.disabled = false;
        setConnection(true, `OLLAMA 在线 · ${modelSelect.options.length} 个模型`);
        updateActiveModel();
        await loadChats(true);
      } catch (error) {
        setConnection(false, "无法连接 Ollama");
        showError(serviceError, `${error.message} 请确认 Ollama 正在运行后刷新页面。`);
        modelList.innerHTML = '<div class="model-item"><strong>服务不可用</strong><span>检查 Ollama 是否已启动</span></div>';
      }
    }

    function updateActiveModel() {
      for (const item of modelList.children) {
        item.classList.toggle("active", item.dataset.model === modelSelect.value);
      }
      const supportsVision = modelCapabilities.get(modelSelect.value)?.includes("vision") || false;
      attachmentButton.hidden = !supportsVision;
      if (!supportsVision && selectedFiles.length) {
        clearAttachments();
      }
    }

    function renderAttachments() {
      attachmentList.replaceChildren();
      attachmentList.hidden = selectedFiles.length === 0;
      for (const [index, file] of selectedFiles.entries()) {
        const chip = document.createElement("span");
        chip.className = "attachment-chip";
        const name = document.createElement("span");
        name.className = "attachment-name";
        name.textContent = file.name;
        const remove = document.createElement("button");
        remove.className = "attachment-remove";
        remove.type = "button";
        remove.textContent = "×";
        remove.title = `移除附件：${file.name}`;
        remove.setAttribute("aria-label", `移除附件：${file.name}`);
        remove.addEventListener("click", () => {
          selectedFiles.splice(index, 1);
          renderAttachments();
        });
        chip.append(name, remove);
        attachmentList.append(chip);
      }
    }

    async function encodeAttachment(file) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      }
      return { name: file.name, data: btoa(binary) };
    }

    async function loadChats(restoreActive = false) {
      try {
        const response = await fetch("/api/chats");
        if (await handleUnauthorized(response)) return;
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "读取历史聊天失败。");
        const chats = Array.isArray(payload.chats) ? payload.chats : [];
        historyCount.textContent = String(chats.length);
        historyList.replaceChildren();

        if (chats.length === 0) {
          const empty = document.createElement("p");
          empty.className = "history-empty";
          empty.textContent = "还没有聊天记录。点击“新对话”开始。";
          historyList.append(empty);
        }

        for (const chat of chats) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "history-button";
          button.dataset.chatId = chat.id;
          button.title = chat.title;
          button.setAttribute("aria-label", `切换到聊天：${chat.title}`);
          const icon = document.createElement("span");
          icon.className = "history-icon";
          icon.setAttribute("aria-hidden", "true");
          icon.textContent = "◷";
          const title = document.createElement("span");
          title.className = "history-title";
          title.textContent = chat.title;
          button.append(icon, title);
          button.addEventListener("click", () => openChat(chat.id));
          const entry = document.createElement("div");
          entry.className = "history-entry";
          const deleteButton = document.createElement("button");
          deleteButton.type = "button";
          deleteButton.className = "history-delete";
          deleteButton.textContent = "×";
          deleteButton.title = `删除聊天：${chat.title}`;
          deleteButton.setAttribute("aria-label", `删除聊天：${chat.title}`);
          deleteButton.addEventListener("click", () => deleteChat(chat.id, chat.title));
          entry.append(button, deleteButton);
          historyList.append(entry);
        }

        if (restoreActive) {
          const savedId = localStorage.getItem("ollama-current-chat");
          const selected = chats.find((chat) => chat.id === savedId) || chats[0];
          if (selected) {
            await openChat(selected.id);
          } else {
            currentChatId = null;
            conversation = [];
            renderMessages([]);
          }
        } else {
          updateActiveHistory();
        }
      } catch (error) {
        showError(serviceError, `读取聊天历史失败：${error.message}`);
      }
    }

    async function createChatRecord() {
      const response = await fetch("/api/chats", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelSelect.value }),
      });
      if (await handleUnauthorized(response)) throw new Error("请先登录后再创建聊天。");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "无法新建聊天窗口。");
      return payload.chat;
    }

    async function startNewChat() {
      if (busy) return;
      serviceError.hidden = true;
      sendError.hidden = true;
      try {
        const chat = await createChatRecord();
        currentChatId = chat.id;
        localStorage.setItem("ollama-current-chat", currentChatId);
        conversation = [];
        renderMessages([]);
        await loadChats(false);
        promptInput.focus();
      } catch (error) {
        showError(sendError, `新建聊天失败：${error.message}`);
      }
    }

    async function openChat(chatId) {
      if (busy) return;
      try {
        const response = await fetch(`/api/chats/${encodeURIComponent(chatId)}`);
        if (await handleUnauthorized(response)) return;
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "读取聊天记录失败。");
        currentChatId = payload.chat.id;
        localStorage.setItem("ollama-current-chat", currentChatId);
        if ([...modelSelect.options].some((option) => option.value === payload.chat.model)) {
          modelSelect.value = payload.chat.model;
          updateActiveModel();
        }
        conversation = payload.messages.map(({ role, content }) => ({ role, content }));
        renderMessages(conversation);
        updateActiveHistory();
        serviceError.hidden = true;
        sendError.hidden = true;
      } catch (error) {
        showError(serviceError, `无法打开聊天记录：${error.message}`);
      }
    }

    async function deleteChat(chatId, title) {
      if (busy || !window.confirm(`确定删除“${title}”及其全部聊天记录吗？此操作无法撤销。`)) return;
      serviceError.hidden = true;
      sendError.hidden = true;
      try {
        const response = await fetch(`/api/chats/${encodeURIComponent(chatId)}`, {
          method: "DELETE",
          credentials: "same-origin",
        });
        if (await handleUnauthorized(response)) return;
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "删除聊天失败。");
        if (currentChatId === chatId) {
          currentChatId = null;
          localStorage.removeItem("ollama-current-chat");
          conversation = [];
          renderMessages([]);
        }
        await loadChats(false);
      } catch (error) {
        showError(sendError, `删除聊天失败：${error.message}`);
      }
    }

    function updateActiveHistory() {
      for (const button of historyList.querySelectorAll(".history-button")) {
        button.classList.toggle("active", button.dataset.chatId === currentChatId);
      }
    }

    function renderMessages(messages) {
      messagesElement.replaceChildren(welcome);
      welcome.hidden = false;
      for (const message of messages) addMessage(message.role, message.content);
      messagesElement.scrollTop = messagesElement.scrollHeight;
    }

    function addMessage(role, content = "") {
      const article = document.createElement("article");
      article.className = `message ${role}`;
      const avatar = document.createElement("div");
      avatar.className = "avatar";
      avatar.textContent = role === "user" ? "你" : "AI";
      const body = document.createElement("div");
      body.className = "message-body";
      const meta = document.createElement("p");
      meta.className = "message-meta";
      meta.textContent = role === "user" ? "YOU" : "LOCAL MODEL";
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = content;
      body.append(meta, bubble);
      article.append(avatar, body);
      welcome.hidden = true;
      messagesElement.append(article);
      messagesElement.scrollTop = messagesElement.scrollHeight;
      return { article, bubble };
    }

    async function sendMessage(text) {
      const content = text.trim();
      const model = modelSelect.value;
      const files = [...selectedFiles];
      if ((!content && files.length === 0) || !model || busy) return;
      serviceError.hidden = true;
      sendError.hidden = true;
      busy = true;
      sendButton.disabled = true;
      modelSelect.disabled = true;
      attachmentButton.disabled = true;
      let nextConversation = null;

      try {
        const attachments = await Promise.all(files.map(encodeAttachment));
        if (!currentChatId) {
          const chat = await createChatRecord();
          currentChatId = chat.id;
          localStorage.setItem("ollama-current-chat", currentChatId);
        }
        promptInput.value = "";
        const displayContent = [
          content,
          files.length ? `附件：${files.map((file) => file.name).join("、")}` : "",
        ].filter(Boolean).join("\n\n");
        addMessage("user", displayContent);
        const assistant = addMessage("assistant");
        assistant.bubble.innerHTML = '<span class="typing" aria-label="正在生成"><i></i><i></i><i></i></span>';
        nextConversation = [...conversation, { role: "user", content: displayContent }];
        const response = await fetch("/api/chat", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: currentChatId,
            model,
            message: content,
            attachments,
          }),
        });
        if (await handleUnauthorized(response)) throw new Error("请先登录后再发送消息。");
        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.error || `请求失败（${response.status}）。`);
        }
        selectedFiles = [];
        renderAttachments();
        if (!response.body) throw new Error("浏览器无法读取流式回复。");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let pending = "";
        let answer = "";
        let finished = false;
        while (!finished) {
          const { value, done } = await reader.read();
          pending += decoder.decode(value || new Uint8Array(), { stream: !done });
          const blocks = pending.split("\n\n");
          pending = blocks.pop() || "";
          for (const block of blocks) {
            const line = block.split("\n").find((part) => part.startsWith("data: "));
            if (!line) continue;
            const event = JSON.parse(line.slice(6));
            if (event.error) throw new Error(event.error);
            if (event.content) {
              answer += event.content;
              assistant.bubble.textContent = answer;
              messagesElement.scrollTop = messagesElement.scrollHeight;
            }
            if (event.done) finished = true;
          }
          if (done) break;
        }
        if (!answer) answer = "模型没有返回文字内容。";
        assistant.bubble.textContent = answer;
        conversation = [...nextConversation, { role: "assistant", content: answer }];
      } catch (error) {
        const assistant = messagesElement.querySelector(".message.assistant:last-child");
        if (assistant) {
          assistant.classList.add("error");
          assistant.querySelector(".bubble").textContent = error.message;
        }
        if (nextConversation) conversation = nextConversation;
        showError(sendError, `回复未完成：${error.message}`);
      } finally {
        await loadChats(false);
        busy = false;
        modelSelect.disabled = modelSelect.options.length === 0;
        sendButton.disabled = modelSelect.disabled;
        attachmentButton.disabled = false;
        promptInput.focus();
      }
    }

    document.querySelector("#chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage(promptInput.value);
    });
    attachmentButton.addEventListener("click", () => attachmentInput.click());
    attachmentInput.addEventListener("change", () => {
      const incoming = [...attachmentInput.files];
      attachmentInput.value = "";
      const supportedExtensions = /\.(png|jpe?g|webp|txt|pdf|docx|pptx|xlsx)$/i;
      if (incoming.some((file) => !supportedExtensions.test(file.name))) {
        showError(sendError, "附件格式不支持，请选择图片、TXT、PDF、DOCX、XLSX 或 PPTX 文件。");
        return;
      }
      if (incoming.some((file) => file.size > 10_000_000)) {
        showError(sendError, "单个附件不能超过 10 MB。");
        return;
      }
      const combined = [...selectedFiles, ...incoming];
      if (combined.length > 5) {
        showError(sendError, "一次最多上传 5 个附件。");
        return;
      }
      if (combined.reduce((total, file) => total + file.size, 0) > 20_000_000) {
        showError(sendError, "附件总大小不能超过 20 MB。");
        return;
      }
      sendError.hidden = true;
      selectedFiles = combined;
      renderAttachments();
    });
    promptInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        document.querySelector("#chatForm").requestSubmit();
      }
    });
    modelSelect.addEventListener("change", updateActiveModel);
    themeToggle.addEventListener("click", () => {
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
    authThemeToggle.addEventListener("click", () => {
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
    document.querySelector("#newChat").addEventListener("click", startNewChat);
    document.querySelector("#logoutButton").addEventListener("click", logout);
    authForm.addEventListener("submit", submitAuth);
    authSwitch.addEventListener("click", () => {
      setAuthMode(authMode === "login" ? "register" : "login");
    });
    document.querySelectorAll(".suggestion").forEach((button) => {
      button.addEventListener("click", () => {
        promptInput.value = button.dataset.prompt;
        promptInput.focus();
      });
    });
    setTheme(localStorage.getItem("ollama-theme") === "dark" ? "dark" : "light");
    checkSession();

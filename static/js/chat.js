(() => {
  const qs = (sel) => document.querySelector(sel);

  const messagesEl = qs("#messages");
  const messageForm = qs("#message-form");
  const messageInput = qs("#message-input");
  const imageInput = qs("#image-input");
  const userListEl = qs("#user-list");

  const usernameModal = qs("#username-modal");
  const usernameInput = qs("#username-input");
  const joinBtn = qs("#join-btn");
  const currentUsernameEl = qs("#current-username");

  const systemBanner = qs("#system-banner");
  const systemBannerText = qs("#system-banner-text");

  const encryptToggle = qs("#encrypt-toggle");
  const currentKeyEl = qs("#current-key");
  const refreshKeyBtn = qs("#refresh-key");

  const decryptKeyInput = qs("#decrypt-key-input");
  const decryptDropzone = qs("#decrypt-dropzone");
  const decryptFilesInput = qs("#decrypt-files-input");
  const selectDecryptFilesBtn = qs("#select-decrypt-files");
  const decryptFilesInfo = qs("#decrypt-files-info");
  const decryptBtn = qs("#decrypt-btn");
  const decryptOutput = qs("#decrypt-output");
  const encryptWaitModal = qs("#encrypt-wait-modal");

  let selfUserId = null;
  let username = null;
  let lastTs = 0;
  let pollTimer = null;
  let heartbeatTimer = null;
  let currentKey = null;
  const decryptFiles = [];

  function showSystemBanner(text) {
    systemBannerText.textContent = text;
    systemBanner.classList.remove("hidden");
    setTimeout(() => {
      systemBanner.classList.add("hidden");
    }, 2600);
  }

  function scrollToBottom() {
    if (!messagesEl) return;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function renderSystemMessage(content, timestamp) {
    const div = document.createElement("div");
    div.className = "system-message";
    const timeText = timestamp ? ` · ${new Date(timestamp).toLocaleTimeString()}` : "";
    div.textContent = `${content}${timeText}`;
    messagesEl.appendChild(div);
  }

  function renderMessage(msg) {
    const isSelf = msg.userId === selfUserId;
    const row = document.createElement("div");
    row.className = "message-row" + (isSelf ? " self" : "");

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    const header = document.createElement("div");
    header.className = "message-header";

    const nameSpan = document.createElement("span");
    nameSpan.className = "message-username";
    nameSpan.textContent = msg.username || "匿名用户";

    const tsSpan = document.createElement("span");
    tsSpan.className = "message-timestamp";
    tsSpan.textContent = new Date(msg.timestamp).toLocaleTimeString();

    header.appendChild(nameSpan);
    header.appendChild(tsSpan);

    const content = document.createElement("div");
    content.className = "message-content";

    if (msg.type === "image") {
      const img = document.createElement("img");
      img.className = "message-image";
      img.src = msg.content;
      img.alt = "图片";
      img.loading = "lazy";
      content.appendChild(img);
    } else {
      content.innerHTML = escapeHtml(msg.content);
    }

    bubble.appendChild(header);
    bubble.appendChild(content);
    row.appendChild(bubble);
    messagesEl.appendChild(row);
  }

  function updateUserList(users) {
    if (!userListEl) return;
    userListEl.innerHTML = "";
    users.forEach((u) => {
      const li = document.createElement("li");
      li.className = "user-list-item";

      const avatar = document.createElement("div");
      avatar.className = "user-avatar";
      const initial = (u.username || "匿")[0].toUpperCase();
      avatar.textContent = initial;

      const name = document.createElement("div");
      name.className = "user-name";
      name.textContent = u.username || "匿名用户";

      li.appendChild(avatar);
      li.appendChild(name);

      if (u.userId === selfUserId) {
        const selfTag = document.createElement("span");
        selfTag.className = "user-self-tag";
        selfTag.textContent = "我";
        li.appendChild(selfTag);
      }

      userListEl.appendChild(li);
    });
  }

  function generateRandomKey() {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    let s = "";
    for (let i = 0; i < 8; i++) {
      s += chars[Math.floor(Math.random() * chars.length)];
    }
    return s;
  }

  function syncKeyToUI() {
    if (!currentKey) {
      currentKey = generateRandomKey();
    }
    if (currentKeyEl) currentKeyEl.textContent = currentKey;
    if (decryptKeyInput && !decryptKeyInput.value) {
      decryptKeyInput.value = currentKey;
    }
  }

  async function joinChat() {
    const name = usernameInput.value.trim() || "匿名用户";
    username = name;
    currentUsernameEl.textContent = `当前用户：${username}`;
    usernameModal.style.display = "none";
    if (!selfUserId) {
      selfUserId = "u_" + Math.random().toString(36).slice(2);
    }
    // 向后端请求为该用户分配一个密钥（尽量复用已有密钥且不与其他在线用户重复）
    try {
      const resp = await fetch("/api/assign_key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: selfUserId,
          username,
        }),
      });
      const data = await resp.json();
      if (data.ok && data.key) {
        currentKey = data.key;
      } else {
        currentKey = generateRandomKey();
      }
    } catch (e) {
      console.error("assign key error", e);
      currentKey = generateRandomKey();
    }
    syncKeyToUI();
    startHeartbeat();
    startPolling();
  }

  if (refreshKeyBtn) {
    refreshKeyBtn.addEventListener("click", () => {
      currentKey = generateRandomKey();
      syncKeyToUI();
      showSystemBanner("已生成新的密钥");
    });
  }

  joinBtn.addEventListener("click", () => {
    joinChat();
  });

  usernameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      joinChat();
    }
  });

  messageForm.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!username) {
      showSystemBanner("请先设置昵称并加入聊天室");
      return;
    }
    const text = messageInput.value.trim();
    if (!text) return;
    if (encryptToggle && encryptToggle.checked) {
      encryptAndSend(text);
    } else {
      sendTextMessage(text);
    }
    messageInput.value = "";
  });

  if (imageInput) {
    imageInput.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      await uploadImageFile(file);
      imageInput.value = "";
    });
  }

  async function uploadImageFile(file) {
    if (!username) {
      showSystemBanner("请先设置昵称并加入聊天室");
      return;
    }
    const formData = new FormData();
    formData.append("image", file);

    try {
      showSystemBanner("正在上传图片...");
      const resp = await fetch("/upload", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      if (!data.success) {
        showSystemBanner(data.error || "图片上传失败");
        return;
      }
      await sendImageMessage(data.url);
    } catch (err) {
      console.error("Upload error", err);
      showSystemBanner("图片上传失败");
    }
  }

  // 中间聊天区域的拖拽上传
  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    messagesEl.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    messagesEl.addEventListener(eventName, () => {
      messagesEl.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    messagesEl.addEventListener(eventName, () => {
      messagesEl.classList.remove("drag-over");
    });
  });

  messagesEl.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    if (!file.type.startsWith("image/")) {
      showSystemBanner("只能上传图片文件");
      return;
    }
    uploadImageFile(file);
  });

  // 右侧解密区域的拖拽与文件选择
  if (decryptDropzone && decryptFilesInput) {
    ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
      decryptDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      decryptDropzone.addEventListener(eventName, () => {
        decryptDropzone.classList.add("drag-over");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      decryptDropzone.addEventListener(eventName, () => {
        decryptDropzone.classList.remove("drag-over");
      });
    });

    decryptDropzone.addEventListener("drop", (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (!files || files.length === 0) return;
      for (let i = 0; i < files.length; i++) {
        if (files[i].type.startsWith("image/")) {
          decryptFiles.push(files[i]);
        }
      }
      updateDecryptFilesInfo();
    });

    if (selectDecryptFilesBtn) {
      selectDecryptFilesBtn.addEventListener("click", () => {
        decryptFilesInput.click();
      });
    }

    decryptFilesInput.addEventListener("change", (e) => {
      const files = e.target.files;
      for (let i = 0; i < files.length; i++) {
        if (files[i].type.startsWith("image/")) {
          decryptFiles.push(files[i]);
        }
      }
      updateDecryptFilesInfo();
    });
  }

  function updateDecryptFilesInfo() {
    if (!decryptFilesInfo) return;
    if (decryptFiles.length === 0) {
      decryptFilesInfo.textContent = "尚未选择图片";
    } else {
      decryptFilesInfo.textContent = `已选择 ${decryptFiles.length} 张图片，将按当前顺序解密`;
    }
  }

  if (decryptBtn) {
    decryptBtn.addEventListener("click", async () => {
      const key = (decryptKeyInput && decryptKeyInput.value.trim()) || currentKey;
      if (!key) {
        showSystemBanner("请先设置解密密钥");
        return;
      }
      if (decryptFiles.length === 0) {
        showSystemBanner("请先拖入或选择需要解密的图片");
        return;
      }
      const formData = new FormData();
      formData.append("key", key);
      decryptFiles.forEach((f) => formData.append("images", f));
      try {
        const resp = await fetch("/api/decrypt_images", {
          method: "POST",
          body: formData,
        });
        const data = await resp.json();
        if (!data.ok) {
          showSystemBanner(data.error || "解密失败");
          return;
        }
        if (decryptOutput) {
          decryptOutput.value = data.text || "";
        }
      } catch (e) {
        console.error("decrypt error", e);
        showSystemBanner("解密失败");
      }
    });
  }

  async function sendTextMessage(text) {
    try {
      const resp = await fetch("/api/send_message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: selfUserId,
          username,
          content: text,
        }),
      });
      const data = await resp.json();
      if (!data.ok) {
        showSystemBanner("消息发送失败");
      }
    } catch (e) {
      console.error(e);
      showSystemBanner("消息发送失败");
    }
  }

  async function sendImageMessage(url) {
    try {
      const resp = await fetch("/api/send_image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: selfUserId,
          username,
          url,
        }),
      });
      const data = await resp.json();
      if (!data.ok) {
        showSystemBanner("图片消息发送失败");
      }
    } catch (e) {
      console.error(e);
      showSystemBanner("图片消息发送失败");
    }
  }

  async function pollMessages() {
    try {
      const resp = await fetch(`/api/messages?since=${lastTs}`);
      const data = await resp.json();
      if (!data.ok) return;
      if (Array.isArray(data.messages) && data.messages.length > 0) {
        data.messages.forEach((msg) => {
          if (msg.type === "system") {
            renderSystemMessage(msg.content, msg.timestamp);
          } else {
            renderMessage(msg);
          }
          lastTs = Math.max(lastTs, msg.tsMs || 0);
        });
        scrollToBottom();
      }
      if (typeof data.serverTime === "number") {
        lastTs = Math.max(lastTs, data.serverTime);
      }
    } catch (e) {
      console.error("poll error", e);
    }
  }

  async function sendHeartbeat() {
    if (!selfUserId || !username) return;
    try {
      const resp = await fetch("/api/heartbeat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: selfUserId,
          username,
        }),
      });
      const data = await resp.json();
      if (data.ok && Array.isArray(data.users)) {
        updateUserList(data.users);
      }
    } catch (e) {
      console.error("heartbeat error", e);
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollMessages();
    pollTimer = setInterval(pollMessages, 1000);
  }

  function startHeartbeat() {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    sendHeartbeat();
    // 心跳频率恢复为约 8 秒一次，减轻前端压力
    heartbeatTimer = setInterval(sendHeartbeat, 8000);
  }

  async function encryptAndSend(text) {
    const key = currentKey || (currentKeyEl && currentKeyEl.textContent.trim());
    if (!key) {
      showSystemBanner("当前密钥为空，无法加密");
      return;
    }
    try {
      if (encryptWaitModal) {
        encryptWaitModal.classList.remove("hidden");
      }
      const resp = await fetch("/api/encrypt_text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key,
          text,
        }),
      });
      const data = await resp.json();
      if (encryptWaitModal) {
        encryptWaitModal.classList.add("hidden");
      }
      if (!data.ok) {
        showSystemBanner(data.error || "加密失败");
        return;
      }
      if (data.initializedNow) {
        showSystemBanner("首次使用该密钥，已完成图片映射初始化");
      }
      const images = data.images || [];
      for (const url of images) {
        await sendImageMessage(url);
      }
    } catch (e) {
      console.error("encrypt error", e);
      showSystemBanner("加密失败");
      if (encryptWaitModal) {
        encryptWaitModal.classList.add("hidden");
      }
    }
  }

  // 页面关闭前主动通知后端下线
  window.addEventListener("beforeunload", () => {
    if (!selfUserId) return;
    const payload = JSON.stringify({ userId: selfUserId });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/logout", payload);
    } else {
      fetch("/api/logout", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: payload,
      });
    }
  });

  // 默认不提前生成密钥，等用户加入后统一从后端/本地生成
})();


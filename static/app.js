document.addEventListener("DOMContentLoaded", () => {
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const chatMessages = document.getElementById("chat-messages");
    const modelSelect = document.getElementById("model-select");
    const tempInput = document.getElementById("temp-input");
    const tokensInput = document.getElementById("tokens-input");
    const clearChatBtn = document.getElementById("clear-chat-btn");
    const refreshMetricsBtn = document.getElementById("refresh-metrics-btn");
    const ttsToggle = document.getElementById("tts-toggle");
    const attachBtn = document.getElementById("attach-btn");
    const attachInput = document.getElementById("attach-input");
    const attachPreview = document.getElementById("attach-preview");

    // Pending file attachments for the next message: {kind, name, dataUrl?, content?}
    let pendingAttachments = [];

    // UI Stats elements
    const ramPercentage = document.getElementById("ram-percentage");
    const ramFill = document.getElementById("ram-fill");
    const ramUsed = document.getElementById("ram-used");
    const ramTotal = document.getElementById("ram-total");
    const memorySummaryHeader = document.getElementById("memory-summary-header");
    // Handle model mode selection from the left sidebar Settings panel
    if (modelSelect) {
        modelSelect.addEventListener("change", async (e) => {
            const targetModel = e.target.value;
            const activeDisplay = document.getElementById("active-model-name-display");
            const activeIcon = document.getElementById("active-model-icon");

            if (activeDisplay) {
                activeDisplay.textContent = "Swapping model server...";
            }
            if (activeIcon) {
                activeIcon.className = "fa-solid fa-arrows-rotate fa-spin";
            }

            try {
                const res = await fetch("/api/switch-model", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ model: targetModel })
                });
                const data = await res.json();

                if (data.status === "ok") {
                    if (activeDisplay) {
                        if (targetModel === "qwen") {
                            activeDisplay.textContent = "Qwen 2.5 Coder 3B Instruct (Expert Code Specialist Mode)";
                            if (activeIcon) activeIcon.className = "fa-solid fa-laptop-code";
                        } else if (targetModel === "granite") {
                            activeDisplay.textContent = "Granite 3.1 3B A800M Instruct (Tutoring & Guidance Mode)";
                            if (activeIcon) activeIcon.className = "fa-solid fa-graduation-cap";
                        } else {
                            activeDisplay.textContent = "Auto (Smart Intent Routing Mode)";
                            if (activeIcon) activeIcon.className = "fa-solid fa-bolt";
                        }
                    }
                    updateMetrics();
                }
            } catch (err) {
                console.error("Model switch failed:", err);
                if (activeDisplay) activeDisplay.textContent = "Model switch failed";
                if (activeIcon) activeIcon.className = "fa-solid fa-triangle-exclamation";
            }
        });
    }

    // Breakdown elements
    const breakdownCard = document.getElementById("metrics-breakdown-card");
    const breakdownPanel = document.getElementById("breakdown-panel");
    const chevronIcon = document.getElementById("chevron-icon");
    const breakdownOs = document.getElementById("breakdown-os");
    const breakdownGpu = document.getElementById("breakdown-gpu");
    const breakdownModelName = document.getElementById("breakdown-model-name");
    const breakdownEngine = document.getElementById("breakdown-engine");
    const breakdownCache = document.getElementById("breakdown-cache");
    const breakdownVision = document.getElementById("breakdown-vision");
    const breakdownColbert = document.getElementById("breakdown-colbert");
    const breakdownKokoro = document.getElementById("breakdown-kokoro");
    const breakdownOrchestrator = document.getElementById("breakdown-orchestrator");
    const breakdownOtherUser = document.getElementById("breakdown-other-user");
    const breakdownTotal = document.getElementById("breakdown-total");

    // Toggle breakdown panel visibility on click
    if (breakdownCard && breakdownPanel && chevronIcon) {
        const header = breakdownCard.querySelector(".metric-header");
        header.addEventListener("click", () => {
            const isHidden = breakdownPanel.style.display === "none" || breakdownPanel.style.display === "";
            if (isHidden) {
                breakdownPanel.style.display = "flex";
                chevronIcon.style.transform = "rotate(180deg)";
            } else {
                breakdownPanel.style.display = "none";
                chevronIcon.style.transform = "rotate(0deg)";
            }
        });
    }

    let chatHistory = [];

    // Auto-resize input textarea
    chatInput.addEventListener("input", function() {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight - 16) + "px";
    });

    // Keyboard shortcuts: Enter alone submits prompt; Ctrl+Enter / Shift+Enter creates a new line natively
    chatInput.addEventListener("keydown", function(e) {
        if (e.key === "Enter") {
            if (e.ctrlKey || e.shiftKey) {
                // Ctrl+Enter or Shift+Enter -> Let browser natively insert \n in textarea
                return;
            } else {
                // Enter alone -> Click Send Button
                e.preventDefault();
                e.stopPropagation();
                const sendBtn = document.getElementById("send-btn");
                if (sendBtn) {
                    sendBtn.click();
                } else if (typeof chatForm.requestSubmit === "function") {
                    chatForm.requestSubmit();
                }
            }
        }
    });

    // Refresh System Metrics
    async function updateMetrics() {
        try {
            const res = await fetch("/api/metrics");
            const data = await res.json();
            if (data.status === "Healthy") {
                const total = data.total_gb;
                const used = data.used_gb;
                const percentage = Math.round((used / total) * 100);

                if (ramPercentage) ramPercentage.textContent = `${percentage}%`;
                if (ramFill) ramFill.style.width = `${percentage}%`;
                if (ramUsed) ramUsed.textContent = `${used.toFixed(1)} GB`;
                if (ramTotal) ramTotal.textContent = `${total.toFixed(1)} GB`;

                const summaryHeader = document.getElementById("memory-summary-header");
                if (summaryHeader) {
                    summaryHeader.textContent = `${used.toFixed(1)} GB / ${total.toFixed(1)} GB`;
                }

                // Populate detailed memory breakdown
                if (data.breakdown) {
                    const b = data.breakdown;
                    if (breakdownOs) breakdownOs.textContent = `${Number(b.os_baseline_mb || 0).toFixed(1)} MB`;
                    if (breakdownGpu) {
                        const gpuMb = Number(b.granite_gpu_mb || 0);
                        const weightsMb = Number(b.model_weights_mb || 0);
                        const activeMb = gpuMb > 0 ? gpuMb : weightsMb;
                        const diskGb = Number(b.model_disk_gb || 0).toFixed(1);
                        breakdownGpu.textContent = activeMb >= 1024
                            ? `${(activeMb / 1024).toFixed(2)} GB (${diskGb} GB file)`
                            : `${activeMb.toFixed(1)} MB (${diskGb} GB file)`;
                    }
                    if (breakdownModelName) breakdownModelName.textContent = b.model_name || "Active Model";
                    
                    const activeDisplay = document.getElementById("active-model-name-display");
                    const activeIcon = document.getElementById("active-model-icon");
                    if (activeDisplay && b.model_name) {
                        const mName = String(b.model_name).toLowerCase();
                        if (mName.includes("qwen")) {
                            activeDisplay.textContent = `${b.model_name} (Expert Code Specialist Mode)`;
                            if (activeIcon) activeIcon.className = "fa-solid fa-laptop-code";
                        } else {
                            activeDisplay.textContent = `${b.model_name} (Tutoring & Guidance Mode)`;
                            if (activeIcon) activeIcon.className = "fa-solid fa-graduation-cap";
                        }
                    }
                    if (breakdownEngine) breakdownEngine.textContent = `${Number(b.llama_cpp_overhead_mb || 0).toFixed(1)} MB`;
                    if (breakdownCache) breakdownCache.textContent = `${Number(b.prompt_cache_mb || 0).toFixed(1)} MB`;
                    if (breakdownVision) {
                        const vStatus = b.vision_status || "Idle (CPU - 0 VRAM)";
                        breakdownVision.textContent = vStatus;
                        if (vStatus.includes("Active")) {
                            breakdownVision.style.color = "#f59e0b";
                        } else {
                            breakdownVision.style.color = "#38bdf8";
                        }
                    }
                    
                    if (breakdownColbert) breakdownColbert.textContent = `${Number(b.colbert_rss_mb || 0).toFixed(1)} MB`;
                    if (breakdownKokoro) breakdownKokoro.textContent = `${Number(b.kokoro_rss_mb || 0).toFixed(1)} MB`;
                    if (breakdownOrchestrator) breakdownOrchestrator.textContent = `${Number(b.orchestrator_rss_mb || 0).toFixed(1)} MB`;
                    if (breakdownOtherUser) breakdownOtherUser.textContent = `${Number(b.other_user_programs_mb || 0).toFixed(1)} MB`;
                    
                    const totMb = Number(b.total_used_mb || 0);
                    if (breakdownTotal) breakdownTotal.textContent = `${(totMb / 1024).toFixed(2)} GB (${totMb.toFixed(0)} MB)`;
                }

                // Warning color if RAM is critically high (> 90%)
                if (percentage > 90) {
                    ramFill.style.background = "var(--error)";
                } else {
                    ramFill.style.background = "var(--accent-gradient)";
                }
            }
        } catch (e) {
            console.error("Failed to load metrics", e);
        }
    }

    refreshMetricsBtn.addEventListener("click", updateMetrics);
    // Auto-update metrics every 8 seconds
    setInterval(updateMetrics, 8000);
    updateMetrics();

    // Fetch initial TTS setting
    async function loadSettings() {
        try {
            const res = await fetch("/api/settings");
            const data = await res.json();
            if (ttsToggle) {
                ttsToggle.checked = !!data.tts_enabled;
            }
        } catch (e) {
            console.error("Failed to load settings", e);
        }
    }

    if (ttsToggle) {
        ttsToggle.addEventListener("change", async function() {
            try {
                await fetch("/api/settings", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ tts_enabled: this.checked })
                });
            } catch (e) {
                console.error("Failed to save settings", e);
            }
        });
    }

    loadSettings();

    // Helper to escape raw HTML
    function escapeHtml(s) {
        return s
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    // Inline markdown: bold, italic, strikethrough, links, inline code.
    // Operates on a single line of raw (unescaped) text.
    function renderInline(s) {
        const codes = [];
        // Protect inline code spans before escaping/formatting
        s = s.replace(/`([^`]+)`/g, (m, c) => {
            codes.push(c);
            return ` IC${codes.length - 1} `;
        });
        s = escapeHtml(s);
        s = s
            .replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>")
            .replace(/__([^_]+?)__/g, "<strong>$1</strong>")
            .replace(/(^|[^*])\*([^*\n]+?)\*/g, "$1<em>$2</em>")
            .replace(/(^|[^_])_([^_\n]+?)_/g, "$1<em>$2</em>")
            .replace(/~~([^~]+?)~~/g, "<del>$1</del>")
            .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
                     '<a href="$2" target="_blank" rel="noopener">$1</a>');
        // Restore inline code (escaped)
        s = s.replace(/ IC(\d+) /g, (m, i) => `<code>${escapeHtml(codes[i])}</code>`);
        return s;
    }

    function renderCodeBlock(lang, code) {
        const label = (lang || "code").trim();
        return `<div class="code-block">` +
               `<div class="code-block-header">` +
               `<span class="code-lang">${escapeHtml(label)}</span>` +
               `<button class="code-copy-btn" type="button"><i class="fa-solid fa-copy"></i> Copy</button>` +
               `</div>` +
               `<pre><code>${escapeHtml(code)}</code></pre>` +
               `</div>`;
    }

    // Block-level markdown renderer (headings, lists, blockquotes, hr, code fences).
    function formatMessageText(src) {
        const blocks = [];
        // Extract fenced code blocks first so their contents are left untouched.
        src = src.replace(/```([^\n`]*)\n?([\s\S]*?)```/g, (m, lang, code) => {
            blocks.push({ lang: lang.trim(), code: code.replace(/\n$/, "") });
            return `\n CB${blocks.length - 1} \n`;
        });

        const lines = src.replace(/\r\n/g, "\n").split("\n");
        let html = "";
        let para = [];
        const flushPara = () => {
            if (para.length) {
                html += `<p>${para.map(renderInline).join("<br>")}</p>`;
                para = [];
            }
        };

        let i = 0;
        while (i < lines.length) {
            const line = lines[i];

            const cb = line.match(/^ CB(\d+) $/);
            if (cb) {
                flushPara();
                const b = blocks[Number(cb[1])];
                html += renderCodeBlock(b.lang, b.code);
                i++;
                continue;
            }
            if (/^\s*$/.test(line)) { flushPara(); i++; continue; }

            const h = line.match(/^(#{1,6})\s+(.*)$/);
            if (h) {
                flushPara();
                const lvl = h[1].length;
                html += `<h${lvl}>${renderInline(h[2])}</h${lvl}>`;
                i++;
                continue;
            }
            if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
                flushPara(); html += "<hr>"; i++; continue;
            }
            if (/^\s*>\s?/.test(line)) {
                flushPara();
                const quote = [];
                while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
                    quote.push(lines[i].replace(/^\s*>\s?/, ""));
                    i++;
                }
                html += `<blockquote>${quote.map(renderInline).join("<br>")}</blockquote>`;
                continue;
            }
            if (/^\s*[-*+]\s+/.test(line)) {
                flushPara();
                const items = [];
                while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
                    items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
                    i++;
                }
                html += `<ul>${items.map(it => `<li>${renderInline(it)}</li>`).join("")}</ul>`;
                continue;
            }
            if (/^\s*(\d+)\.\s+/.test(line)) {
                flushPara();
                const items = [];
                while (i < lines.length) {
                    const m = lines[i].match(/^\s*(\d+)\.\s+(.*)$/);
                    if (!m) break;
                    items.push({ num: m[1], text: m[2] });
                    i++;
                }
                html += `<ol>${items.map(it => `<li value="${it.num}">${renderInline(it.text)}</li>`).join("")}</ol>`;
                continue;
            }

            para.push(line);
            i++;
        }
        flushPara();
        return html;
    }

    // Append Message to container
    function appendMessage(role, content) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role}`;
        
        const avatarDiv = document.createElement("div");
        avatarDiv.className = "avatar";
        avatarDiv.innerHTML = role === "user" ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-robot"></i>';

        const wrapperDiv = document.createElement("div");
        wrapperDiv.className = "message-content-wrapper";

        const headerDiv = document.createElement("div");
        headerDiv.className = "message-header";
        if (role === "assistant") {
            const currentModelName = document.getElementById("active-model-name-display")?.textContent || "Granite 3.1 3B (Tutoring Mode)";
            const isQwen = currentModelName.toLowerCase().includes("qwen");
            const modelBadgeLabel = isQwen ? "Qwen 2.5 Coder 3B (Code Specialist)" : "Granite 3.1 3B (Socratic Tutor)";
            const modelIcon = isQwen ? "fa-laptop-code" : "fa-graduation-cap";
            headerDiv.innerHTML = `<span class="sender-name">Antigravity AI</span> <span style="margin-left: 8px; font-size: 10px; font-weight: 500; color: #34d399; background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 1px 8px; border-radius: 10px;"><i class="fa-solid ${modelIcon}"></i> ${modelBadgeLabel}</span>`;
        } else {
            headerDiv.innerHTML = `<span class="sender-name">You</span>`;
        }

        const contentDiv = document.createElement("div");
        contentDiv.className = "message-content";
        if (role === "user") {
            // Render the user's own text verbatim (escaped) so their symbols aren't mangled.
            contentDiv.innerHTML = escapeHtml(content).replace(/\n/g, "<br>");
        } else {
            contentDiv.innerHTML = formatMessageText(content);
        }

        wrapperDiv.appendChild(headerDiv);
        wrapperDiv.appendChild(contentDiv);
        msgDiv.appendChild(avatarDiv);
        msgDiv.appendChild(wrapperDiv);
        
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        return contentDiv;
    }

    // Submit Chat message
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (!text && pendingAttachments.length === 0) return;

        chatInput.value = "";
        chatInput.style.height = "auto";

        // Snapshot and clear attachments for this turn
        const attachments = pendingAttachments;
        pendingAttachments = [];
        renderAttachPreview();

        // Build the API message content and a display string
        const imageAtts = attachments.filter(a => a.kind === "image");
        const fileAtts = attachments.filter(a => a.kind === "file");
        const docAtts = attachments.filter(a => a.kind === "doc");

        let fileText = "";
        for (const f of fileAtts) {
            fileText += `\n\nFile: ${f.name}\n\`\`\`${f.lang || ""}\n${f.content}\n\`\`\``;
        }
        const combinedText = (text + fileText).trim();

        let apiContent;
        if (imageAtts.length || docAtts.length) {
            apiContent = [];
            if (combinedText) apiContent.push({ type: "text", text: combinedText });
            for (const img of imageAtts) {
                apiContent.push({ type: "image_url", image_url: { url: img.dataUrl } });
            }
            for (const doc of docAtts) {
                apiContent.push({ type: "doc_url", doc_url: { url: doc.dataUrl, name: doc.name } });
            }
        } else {
            apiContent = combinedText;
        }

        // Display string: user's prose + a chip line naming the attachments
        let displayText = text;
        if (attachments.length) {
            const names = attachments.map(a => `📎 ${a.name}`).join("  ");
            displayText = (text ? text + "\n\n" : "") + names;
        }

        // Append User message
        appendMessage("user", displayText);
        chatHistory.push({ role: "user", content: apiContent });

        // Create Assistant placeholder
        const assistantContentDiv = appendMessage("assistant", "...");
        
        try {
            const response = await fetch("/v1/chat/completions", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    model: modelSelect.value,
                    messages: chatHistory,
                    stream: true,
                    temperature: parseFloat(tempInput.value) || 0.2,
                    max_tokens: parseInt(tokensInput.value) || 1024
                })
            });

            if (!response.ok) {
                throw new Error(`Server returned HTTP ${response.status}`);
            }

            // Read exact model used from server response header and update badges immediately
            const usedModel = response.headers.get("x-model-used") || "granite-3.1-3b-a800m-instruct";
            const isQwen = usedModel.toLowerCase().includes("qwen");

            const activeDisplay = document.getElementById("active-model-name-display");
            const activeIcon = document.getElementById("active-model-icon");
            if (activeDisplay) {
                activeDisplay.textContent = isQwen ? "Qwen 2.5 Coder 3B Instruct (Expert Code Specialist Mode)" : "Granite 3.1 3B A800M Instruct (Tutoring & Guidance Mode)";
                if (activeIcon) activeIcon.className = isQwen ? "fa-solid fa-laptop-code" : "fa-solid fa-graduation-cap";
            }

            const msgWrapper = assistantContentDiv.closest(".message-content-wrapper");
            if (msgWrapper) {
                const msgHeader = msgWrapper.querySelector(".message-header");
                if (msgHeader) {
                    const modelBadgeLabel = isQwen ? "Qwen 2.5 Coder 3B (Code Specialist)" : "Granite 3.1 3B (Socratic Tutor)";
                    const modelIcon = isQwen ? "fa-laptop-code" : "fa-graduation-cap";
                    msgHeader.innerHTML = `<span class="sender-name">Antigravity AI</span> <span style="margin-left: 8px; font-size: 10px; font-weight: 500; color: #34d399; background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 1px 8px; border-radius: 10px;"><i class="fa-solid ${modelIcon}"></i> ${modelBadgeLabel}</span>`;
                }
            }

            // Stream response
            assistantContentDiv.innerHTML = "";
            let fullReply = "";
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    const cleanLine = line.trim();
                    if (!cleanLine.startsWith("data: ")) continue;
                    const dataStr = cleanLine.substring(6).trim();
                    
                    if (dataStr === "[DONE]") {
                        break;
                    }

                    try {
                        const chunk = JSON.parse(dataStr);
                        const token = chunk.choices[0].delta.content;
                        if (token) {
                            fullReply += token;
                            assistantContentDiv.innerHTML = formatMessageText(fullReply);
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        }
                    } catch (err) {
                        // Handle potential chunk truncation
                    }
                }
            }

            chatHistory.push({ role: "assistant", content: fullReply });
            updateMetrics();

        } catch (err) {
            console.error(err);
            assistantContentDiv.innerHTML = `<span style="color: var(--error)"><i class="fa-solid fa-triangle-exclamation"></i> Error: ${err.message}</span>`;
        }
    });

    // Clear Chat
    clearChatBtn.addEventListener("click", () => {
        if (confirm("Are you sure you want to clear chat history?")) {
            const messages = chatMessages.querySelectorAll(".message:not(.welcome)");
            messages.forEach(m => m.remove());
            chatHistory = [];
        }
    });

    // ---- File attachments ----
    const IMAGE_RE = /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i;
    const LANG_BY_EXT = {
        py: "python", js: "javascript", ts: "typescript", tsx: "tsx", jsx: "jsx",
        sh: "bash", bash: "bash", json: "json", yaml: "yaml", yml: "yaml",
        md: "markdown", html: "html", css: "css", c: "c", cpp: "cpp", h: "c",
        hpp: "cpp", java: "java", go: "go", rs: "rust", rb: "ruby", php: "php",
        sql: "sql", toml: "toml", xml: "xml"
    };

    function renderAttachPreview() {
        if (!attachPreview) return;
        if (!pendingAttachments.length) {
            attachPreview.style.display = "none";
            attachPreview.innerHTML = "";
            return;
        }
        attachPreview.style.display = "flex";
        attachPreview.innerHTML = pendingAttachments.map((a, idx) => {
            const icon = a.kind === "image" ? "fa-image" : "fa-file-code";
            return `<span class="attach-chip"><i class="fa-solid ${icon}"></i>` +
                   `${escapeHtml(a.name)}` +
                   `<button type="button" class="attach-remove" data-idx="${idx}" title="Remove">` +
                   `<i class="fa-solid fa-xmark"></i></button></span>`;
        }).join("");
    }

    function readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            const ext = (file.name.split(".").pop() || "").toLowerCase();
            const isImage = file.type.startsWith("image/") || IMAGE_RE.test(file.name);
            const isBinaryDoc = ["pdf", "docx", "doc"].includes(ext);

            reader.onload = () => {
                if (isImage) {
                    resolve({ kind: "image", name: file.name, dataUrl: reader.result });
                } else if (isBinaryDoc) {
                    resolve({ kind: "doc", name: file.name, dataUrl: reader.result });
                } else {
                    resolve({
                        kind: "file", name: file.name,
                        lang: LANG_BY_EXT[ext] || "",
                        content: reader.result
                    });
                }
            };
            reader.onerror = () => reject(reader.error);
            if (isImage || isBinaryDoc) reader.readAsDataURL(file);
            else reader.readAsText(file);
        });
    }

    if (attachBtn && attachInput) {
        attachBtn.addEventListener("click", () => attachInput.click());
        attachInput.addEventListener("change", async () => {
            for (const file of Array.from(attachInput.files)) {
                try {
                    pendingAttachments.push(await readFile(file));
                } catch (err) {
                    console.error("Failed to read attachment", file.name, err);
                }
            }
            attachInput.value = "";  // allow re-selecting the same file
            renderAttachPreview();
        });
    }

    if (attachPreview) {
        attachPreview.addEventListener("click", (e) => {
            const btn = e.target.closest(".attach-remove");
            if (!btn) return;
            pendingAttachments.splice(Number(btn.dataset.idx), 1);
            renderAttachPreview();
        });
    }

    // Action chip click listener
    chatMessages.addEventListener("click", (e) => {
        const chip = e.target.closest(".action-chip");
        if (chip && chip.dataset.prompt) {
            chatInput.value = chip.dataset.prompt;
            chatInput.focus();
        }
    });

    // Interactive Hands-Free Voice Mode (Web Speech API)
    const micBtn = document.getElementById("mic-btn");
    let recognition = null;
    let isListening = false;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition && micBtn) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onstart = () => {
            isListening = true;
            micBtn.classList.add("active");
            micBtn.title = "Listening... Speak your prompt! Click again to stop.";
            chatInput.placeholder = "🎙️ Listening... Speak your prompt!";
        };

        recognition.onresult = (event) => {
            let transcript = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
                transcript += event.results[i][0].transcript;
            }
            chatInput.value = transcript;
        };

        recognition.onerror = (event) => {
            console.warn("Speech recognition error:", event.error);
            stopListening();
            if (event.error === "not-allowed" || event.error === "service-not-allowed") {
                alert("Microphone permission was denied. Please allow microphone access in your browser location bar (icon next to URL).");
            } else if (event.error === "no-speech") {
                chatInput.placeholder = "No speech detected. Click 🎙️ to try again.";
            } else if (event.error !== "aborted") {
                alert(`Voice Recognition Error: ${event.error}`);
            }
        };

        recognition.onend = () => {
            const hadText = chatInput.value.trim().length > 0;
            stopListening();
            if (hadText) {
                // Auto-submit the voice prompt
                chatForm.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
            }
        };

        function stopListening() {
            isListening = false;
            if (micBtn) {
                micBtn.classList.remove("active");
                micBtn.title = "Toggle Interactive Voice Mode (Hands-Free Dictation)";
            }
            chatInput.placeholder = "Ask a coding question, attach scripts/docs/screenshots, or click 🎙️ for Voice Mode...";
        }

        micBtn.addEventListener("click", async () => {
            if (isListening) {
                try { recognition.stop(); } catch (e) {}
                stopListening();
            } else {
                chatInput.value = "";
                // Explicitly request microphone permission first to ensure Chrome/Edge prompt user
                try {
                    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                        // Immediately close the test stream tracks
                        stream.getTracks().forEach(track => track.stop());
                    }
                    recognition.start();
                } catch (e) {
                    console.error("Failed to start speech recognition / mic permission:", e);
                    alert("Microphone access is required for Voice Mode. Please ensure a microphone is connected and allowed in your browser settings.");
                    stopListening();
                }
            }
        });
    } else if (micBtn) {
        micBtn.addEventListener("click", () => {
            alert("Speech recognition is not supported in this browser. Please use Google Chrome, Microsoft Edge, or Brave for Web Speech API support.");
        });
        micBtn.title = "Speech recognition is not supported in this browser.";
    }

    // Copy button on rendered code blocks (event delegation)
    chatMessages.addEventListener("click", (e) => {
        const btn = e.target.closest(".code-copy-btn");
        if (!btn) return;
        const codeEl = btn.closest(".code-block").querySelector("pre code");
        if (!codeEl) return;
        navigator.clipboard.writeText(codeEl.textContent).then(() => {
            const original = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied';
            setTimeout(() => { btn.innerHTML = original; }, 1500);
        }).catch(() => {});
    });
});

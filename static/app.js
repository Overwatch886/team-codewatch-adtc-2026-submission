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
    async function switchSessionMode(targetModel) {
        const activeDisplay = document.getElementById("active-model-name-display");
        const activeIcon = document.getElementById("active-model-icon");
        if (modelSelect) modelSelect.value = targetModel;

        // Sync active tab state in main header
        const headerBtns = document.querySelectorAll(".header-mode-btn");
        headerBtns.forEach(btn => {
            if (btn.dataset.mode === targetModel) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });

        if (activeDisplay) activeDisplay.textContent = "Swapping mode...";
        if (activeIcon) activeIcon.className = "fa-solid fa-arrows-rotate fa-spin";

        try {
            const res = await fetch("/api/switch-model", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model: targetModel })
            });
            const data = await res.json();

            if (data.status === "ok") {
                if (activeDisplay) {
                    if (targetModel === "fast_ship" || targetModel === "qwen") {
                        activeDisplay.textContent = "Qwen 2.5 Coder 3B (Build & Ship Fast Mode)";
                        if (activeIcon) activeIcon.className = "fa-solid fa-rocket";
                    } else if (targetModel === "socratic_study" || targetModel === "granite" || targetModel === "lfm") {
                        activeDisplay.textContent = "Granite 4.1 3B (Step-by-Step Socratic Study Mode)";
                        if (activeIcon) activeIcon.className = "fa-solid fa-graduation-cap";
                    } else {
                        activeDisplay.textContent = "Auto-Routing Mode (ColBERT Intent Analyzer)";
                        if (activeIcon) activeIcon.className = "fa-solid fa-bolt";
                    }
                }
                updateMetrics();
            }
        } catch (err) {
            console.error("Failed to switch model mode:", err);
            if (activeDisplay) activeDisplay.textContent = "Error switching mode";
            if (activeIcon) activeIcon.className = "fa-solid fa-triangle-exclamation";
        }
    }

    if (modelSelect) {
        modelSelect.addEventListener("change", (e) => switchSessionMode(e.target.value));
    }

    // Main window header mode tab click handlers
    const headerBtns = document.querySelectorAll(".header-mode-btn");
    headerBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetMode = btn.dataset.mode;
            switchSessionMode(targetMode);
        });
    });

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
                const percentage = Math.min(100, Math.round((used / total) * 100));

                if (ramPercentage) ramPercentage.textContent = `${percentage}%`;
                if (ramFill) {
                    ramFill.style.width = `${percentage}%`;
                    // Turn bar amber when above 85% of cgroup ceiling
                    ramFill.style.background = percentage >= 90
                        ? "linear-gradient(90deg, #ef4444, #f97316)"
                        : percentage >= 75
                        ? "linear-gradient(90deg, #f59e0b, #fbbf24)"
                        : "";
                }
                if (ramUsed) ramUsed.textContent = `${used.toFixed(1)} GB`;
                if (ramTotal) {
                    ramTotal.textContent = data.cgroup_active
                        ? `${total.toFixed(1)} GB (cgroup cap)`
                        : `${total.toFixed(1)} GB`;
                }

                const summaryHeader = document.getElementById("memory-summary-header");
                if (summaryHeader) {
                    summaryHeader.textContent = data.cgroup_active
                        ? `${used.toFixed(1)} GB / ${total.toFixed(1)} GB  🛡️ cgroup`
                        : `${used.toFixed(1)} GB / ${total.toFixed(1)} GB`;
                }

                // Populate detailed memory breakdown
                if (data.breakdown) {
                    const b = data.breakdown;
                    if (breakdownOs) breakdownOs.textContent = `${Number(b.os_baseline_mb || 0).toFixed(1)} MB`;
                    if (breakdownGpu) {
                        const gpuMb = Number(b.granite_gpu_mb || 0);
                        const weightsMb = Number(b.model_weights_mb || 0);
                        const activeMb = gpuMb > 0 ? gpuMb : weightsMb;
                        const diskGb = Number(b.model_disk_gb || 0).toFixed(2);
                        breakdownGpu.textContent = activeMb >= 1024
                            ? `${(activeMb / 1024).toFixed(2)} GB (${diskGb} GB on disk)`
                            : `${activeMb.toFixed(1)} MB (${diskGb} GB on disk)`;
                    }
                    if (breakdownModelName) breakdownModelName.textContent = b.model_name || "Active Model";
                    
                    const activeDisplay = document.getElementById("active-model-name-display");
                    const activeIcon = document.getElementById("active-model-icon");
                    if (activeDisplay && b.model_name && b.model_name !== "None") {
                        const mName = String(b.model_name).toLowerCase();
                        if (mName.includes("qwen")) {
                            activeDisplay.textContent = "Qwen 2.5 Coder 3B (Build & Ship Fast Mode)";
                            if (activeIcon) activeIcon.className = "fa-solid fa-rocket";
                        } else if (mName.includes("granite")) {
                            activeDisplay.textContent = "Granite 4.1 3B (Step-by-Step Socratic Study Mode)";
                            if (activeIcon) activeIcon.className = "fa-solid fa-graduation-cap";
                        }
                    }
                    if (breakdownEngine) breakdownEngine.textContent = `${Number(b.llama_cpp_overhead_mb || 0).toFixed(1)} MB`;
                    if (breakdownCache) breakdownCache.textContent = `${Number(b.prompt_cache_mb || 0).toFixed(1)} MB`;
                    if (breakdownVision) {
                        const vStatus = b.vision_status || "0 MB (Idle)";
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
            const currentModelName = document.getElementById("active-model-name-display")?.textContent || "Auto-Routing Mode";
            const isQwen = currentModelName.toLowerCase().includes("qwen") || currentModelName.toLowerCase().includes("fast");
            const isGranite = currentModelName.toLowerCase().includes("granite") || currentModelName.toLowerCase().includes("socratic") || currentModelName.toLowerCase().includes("lfm");
            let modelBadgeLabel = "Auto-Routing (ColBERT)";
            let modelIcon = "fa-bolt";
            if (isQwen) {
                modelBadgeLabel = "Qwen 2.5 Coder 3B (Fast Ship)";
                modelIcon = "fa-rocket";
            } else if (isGranite) {
                modelBadgeLabel = "Granite 4.1 3B (Socratic Tutor)";
                modelIcon = "fa-graduation-cap";
            }
            headerDiv.innerHTML = `<span class="sender-name">Professor LowaCode</span> <span style="margin-left: 8px; font-size: 10px; font-weight: 500; color: #34d399; background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 1px 8px; border-radius: 10px;"><i class="fa-solid ${modelIcon}"></i> ${modelBadgeLabel}</span>`;
        } else {
            headerDiv.innerHTML = `<span class="sender-name">You</span>`;
        }

        const contentDiv = document.createElement("div");
        contentDiv.className = "message-content";
        if (role === "user") {
            // Render the user's own text verbatim (escaped) so their symbols aren't mangled.
            contentDiv.innerHTML = escapeHtml(content).replace(/\n/g, "<br>");
        } else if (content === "..." || content === "thinking") {
            contentDiv.innerHTML = `<div class="thinking-indicator"><i class="fa-solid fa-pen-nib thinking-writer"></i><span>Professor LowaCode is writing</span><div class="thinking-dots"><span></span><span></span><span></span></div></div>`;
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
            const usedModel = response.headers.get("x-model-used") || "granite-4.1-3b";
            const isQwen = usedModel.toLowerCase().includes("qwen");
            const isGranite = usedModel.toLowerCase().includes("granite") || usedModel.toLowerCase().includes("lfm");

            const activeDisplay = document.getElementById("active-model-name-display");
            const activeIcon = document.getElementById("active-model-icon");
            if (activeDisplay) {
                if (isQwen) {
                    activeDisplay.textContent = "Qwen 2.5 Coder 3B (Build & Ship Fast Mode)";
                    if (activeIcon) activeIcon.className = "fa-solid fa-rocket";
                } else if (isGranite) {
                    activeDisplay.textContent = "Granite 4.1 3B (Step-by-Step Socratic Study Mode)";
                    if (activeIcon) activeIcon.className = "fa-solid fa-graduation-cap";
                } else {
                    activeDisplay.textContent = "Auto-Routing Mode (ColBERT Intent Analyzer)";
                    if (activeIcon) activeIcon.className = "fa-solid fa-bolt";
                }
            }

            const msgWrapper = assistantContentDiv.closest(".message-content-wrapper");
            if (msgWrapper) {
                const msgHeader = msgWrapper.querySelector(".message-header");
                if (msgHeader) {
                    let modelBadgeLabel = "Auto-Routing (ColBERT)";
                    let modelIcon = "fa-bolt";
                    if (isQwen) {
                        modelBadgeLabel = "Qwen 2.5 Coder 3B (Fast Ship)";
                        modelIcon = "fa-rocket";
                    } else if (isGranite) {
                        modelBadgeLabel = "Granite 4.1 3B (Socratic Tutor)";
                        modelIcon = "fa-graduation-cap";
                    }
                    msgHeader.innerHTML = `<span class="sender-name">Professor LowaCode</span> <span style="margin-left: 8px; font-size: 10px; font-weight: 500; color: #34d399; background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 1px 8px; border-radius: 10px;"><i class="fa-solid ${modelIcon}"></i> ${modelBadgeLabel}</span>`;
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

    // Interactive Hands-Free Voice Mode (100% Offline Parakeet TDT STT)
    const micBtn = document.getElementById("mic-btn");
    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;

    if (micBtn) {
        micBtn.addEventListener("click", async () => {
            if (isRecording) {
                // Stop recording
                if (mediaRecorder && mediaRecorder.state !== "inactive") {
                    mediaRecorder.stop();
                }
            } else {
                // Start recording audio locally using HTML5 MediaRecorder API
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    audioChunks = [];
                    mediaRecorder = new MediaRecorder(stream);

                    mediaRecorder.ondataavailable = (e) => {
                        if (e.data.size > 0) audioChunks.push(e.data);
                    };

                    mediaRecorder.onstart = () => {
                        isRecording = true;
                        micBtn.classList.add("active");
                        micBtn.title = "🎙️ Recording... Speak your prompt! Click again to transcribe with Parakeet.";
                        chatInput.placeholder = "🎙️ Listening (100% Offline Parakeet TDT STT)... Speak now!";
                    };

                    mediaRecorder.onstop = async () => {
                        isRecording = false;
                        micBtn.classList.remove("active");
                        micBtn.title = "Toggle Interactive Voice Mode (Parakeet TDT STT)";
                        chatInput.placeholder = "⚙️ Transcribing via Parakeet TDT (Offline CPU)...";

                        // Release microphone stream
                        stream.getTracks().forEach(track => track.stop());

                        if (audioChunks.length === 0) {
                            chatInput.placeholder = "Ask a coding question, attach scripts/docs/screenshots, or click 🎙️ for Voice Mode...";
                            return;
                        }

                        const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
                        audioChunks = [];

                        const formData = new FormData();
                        formData.append("file", audioBlob, "recording.webm");

                        try {
                            const res = await fetch("/v1/audio/transcriptions", {
                                method: "POST",
                                body: formData
                            });
                            if (!res.ok) throw new Error(`Server returned HTTP ${res.status}`);
                            const data = await res.json();
                            if (data.text && data.text.trim()) {
                                const newText = data.text.trim();
                                chatInput.value = chatInput.value ? (chatInput.value.trim() + " " + newText) : newText;
                                chatInput.focus();
                                chatInput.style.height = "auto";
                                chatInput.style.height = (chatInput.scrollHeight - 16) + "px";
                                chatInput.placeholder = "Review your transcribed text above, edit if needed, and press Enter or click Send!";
                            } else {
                                chatInput.placeholder = "No speech detected. Click 🎙️ to try again.";
                            }
                        } catch (err) {
                            console.error("Parakeet STT transcription failed:", err);
                            alert(`Offline Parakeet Transcription Error: ${err.message}`);
                            chatInput.placeholder = "Ask a coding question, attach scripts/docs/screenshots, or click 🎙️ for Voice Mode...";
                        }
                    };

                    mediaRecorder.start();
                } catch (err) {
                    console.error("Microphone access failed:", err);
                    alert("Microphone access is required for Voice Mode. Please ensure a microphone is connected and allowed in your browser settings.");
                }
            }
        });
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

# 🚀 Antigravity CodeLab Architecture & Product Guide

**Antigravity CodeLab** (Code Persona) is a 100% offline, privacy-first AI Pair-Programmer & Socratic Coding Tutor engineered specifically for 8GB system constraints.

---

## 🎯 Core Product Workflows

Antigravity CodeLab provides three specialized, interactive pair-programming workflows:

### 1. 🎓 Step-by-Step Socratic Tutor Mode
- **Purpose**: Interactive coding mentorship without full-code spoilers.
- **Behavior**: Outputs ONLY Step 1 + **Your Task**, then pauses generation, forcing the user to write their code before moving forward.
- **Hardware Optimization**: Enforces a strict token generation budget + GGML BNF (GBNF) Grammar constraints (`STEP1_GBNF_GRAMMAR`) at the `llama.cpp` inference engine layer to mathematically forbid the model from generating Step 2+ or trailing filler.

### 2. 🐛 Debugging & Traceback Diagnostic Mode
- **Purpose**: Instant, plain-English error analysis for terminal tracebacks and broken scripts.
- **Behavior**: Pinpoints the exact line number, explains *why* the bug occurred with intuitive real-world analogies, and asks a probing question to help the user fix it.

### 3. 💻 Code Review & Refactor Mode
- **Purpose**: Code quality, performance, and readability optimization.
- **Behavior**: Analyzes submitted code, highlights edge cases, and provides clean, idiomatic refactored blocks with inline explanations.

---

## 🔒 Focus Workstation & Distraction-Free Kiosk Mode

- **Educational Impact**: Designed for real-world African technical schools and budget hardware where background desktop bloat and browser tabs consume critical RAM.
- **RAM Optimization**: Suspends background Linux daemons (`tracker-miner`, `snapd`, `packagekit`), freeing 600 MB - 1.2 GB of physical RAM.
- **Memory Guard**: Enforces systemd cgroup bounds (`MemoryMax=7.5G`), keeping total system memory usage strictly safe inside the 8 GB ceiling.
- **Student Focus**: Launches Code Persona in a clean, distraction-free kiosk window, helping technical students focus on learning without social media distractions.

---

## 🎙️ Interactive Voice & Multimodal Features

### 🔊 Text-to-Speech (Kokoro ONNX v1.0)
- **Model**: `Kokoro-82M` (`af_heart` voice) running via ONNX Runtime.
- **Spoken Code Verbalizer**: Automatically strips code fences and verbalizes symbols naturally (e.g., `def` -> "define", `()` -> "parentheses").
- **Automatic Unloader**: Disabling TTS on the sidebar instantly purges the model from RAM via `gc.collect()`, freeing 340 MB back to the OS.

### 🎙️ Parakeet TDT Push-to-Talk STT & Manual User Review
- **Engine**: Parakeet TDT Multilingual (`SBPN_multilingual_large_q8_0.gguf`).
- **User Review & Edit**: Speech is transcribed directly into the text input box, allowing the user to inspect, edit, or add code before manually sending to the model.

### 📄 Adaptive Document & Image Ingestion
- **Formats Supported**: `.py`, `.js`, `.ts`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), `.pdf`, `.png`, `.jpg` (Vision).
- **Small Documents (≤ 1,500 words)**: Direct context dumping into the prompt for 100% full-text accuracy.
- **Large Documents (> 1,500 words)**: Auto-indexed on-the-fly with AnswerAI ColBERT in ~0.25 seconds.

---

## 🧠 Reasoning Engine & Quantization Selection

| Component | Choice | Specs & Performance |
| :--- | :--- | :--- |
| **Primary Model** | **Granite 4.0 H-Tiny** | Hybrid Mamba/MoE (3.3B total / 800M active), linear context scaling. |
| **Quantization** | **`IQ4_XS` (imatrix)** | 4-bit importance matrix calibration (~2.45 GB - 3.5 GB RAM footprint, ~28.6 t/s speed). |
| **Memory Locking** | `--mlock` | Locks model weights into physical RAM, preventing Linux kernel swap stutters. |
| **CPU Execution** | `-ngl 0` / Vulkan iGPU | 100% pure CPU execution, or Vulkan/GTT layer offloading (`-ngl 14`) when iGPU is available. |
| **KV Cache** | `-ctk q8_0 -ctv q8_0` | 8-bit quantized context cache to minimize memory overhead under long contexts. |

---

## ⚙️ Hardware & VRAM Telemetry (8GB System Budget)

- **Physical System RAM**: 6.35 GiB usable physical RAM on budget 8 GB laptops.
- **ZRAM State**: Permanently masked (`/dev/null`) to eliminate memory compression CPU overhead.
- **Real-Time Memory Breakdown**: Tracks OS Baseline, Active LLM RAM (`granite_rss_mb`), llama.cpp overhead, Kokoro TTS, and Orchestrator RSS in real time via `/api/metrics`.

---

## 🚀 Service Architecture & Endpoints

- **Model Server**: `http://localhost:8081` (llama-server)
- **Orchestrator & Web UI**: `http://localhost:8085` (FastAPI orchestrator)

### Key Endpoints:
- `POST /v1/chat/completions`: Standard OpenAI-compatible completion endpoint with dynamic GBNF grammar constraints.
- `POST /api/switch-model`: Swaps active model between Granite 4.0 H-Tiny and Qwen 2.5 Coder 3B dynamically.
- `GET /api/metrics`: Returns detailed system VRAM, RAM, and breakdown metrics.
- `POST /api/settings`: Toggles Kokoro TTS and triggers immediate memory unloader when disabled.

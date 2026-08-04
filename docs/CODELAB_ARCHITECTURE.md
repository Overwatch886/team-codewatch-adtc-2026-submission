# 🚀 Antigravity CodeLab Architecture & Product Guide

**Antigravity CodeLab** (Code Persona) is a 100% offline, privacy-first AI Pair-Programmer & Socratic Coding Tutor engineered under a **hard 4 GB RAM system ceiling**.

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

## 🔒 Memory Ceiling & Workstation Tuning

- **Educational Impact**: Designed for real-world technical education and budget hardware where RAM is strictly constrained.
- **Memory Ceiling Guard**: Enforces systemd cgroup bounds (`MemoryMax=4G`, `MemoryHigh=3.7G`), keeping total system memory usage strictly bounded.
- **System Tuning**: `setup_system_permanently.sh` configures 4 GB `/dev/shm`, 12 GB persistent swap, `vm.swappiness=5`, `vm.dirty_ratio=20`, `vm.dirty_background_ratio=5`, and unlimited memlock.

---

## 🎙️ Interactive Voice & Multimodal Features

### 🔊 Text-to-Speech (Kokoro ONNX v1.0)
- **Model**: `Kokoro-82M` (`af_heart` voice) running via ONNX Runtime.
- **Spoken Code Verbalizer**: Automatically strips code fences and verbalizes symbols naturally (e.g., `def` -> "define", `()` -> "parentheses").
- **Automatic Unloader**: Disabling TTS on the sidebar instantly purges the model from RAM via `gc.collect()`, freeing 340 MB back to the OS.

### 🎙️ Parakeet TDT Push-to-Talk STT & Manual User Review
- **Engine**: Parakeet TDT Multilingual (`tdt-0.6b-v2-q5_k.gguf`).
- **User Review & Edit**: Speech is transcribed directly into the text input box, allowing the user to inspect, edit, or add code before manually sending to the model.

### 📄 Adaptive Document Ingestion
- **Formats Supported**: `.py`, `.js`, `.ts`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), `.pdf`.
- **Small Documents (≤ 1,500 words)**: Direct context dumping into the prompt for 100% full-text accuracy.
- **Large Documents (> 1,500 words)**: Auto-indexed on-the-fly with AnswerAI ColBERT in ~0.25 seconds.

---

## 🧠 Reasoning Engine & Model Selection

| Component | Model / Spec | Config & Details |
| :--- | :--- | :--- |
| **Socratic Tutor LLM** | **Granite 4.1 3B** (`Q4_K_M`) | Primary Socratic Tutor model (4,096 context window). |
| **Fast Ship LLM** | **Qwen 2.5 Coder 3B** (`Q4_K_M`) | Fast Ship coding model (10,240 / 10k context window). |
| **Memory Locking** | `--mlock` + `--mmap` | Locks model weights into physical RAM, preventing swap stutters. |
| **KV Cache** | `-ctk q8_0 -ctv q8_0` | 8-bit quantized context cache to minimize memory overhead under long contexts. |
| **RAG Engine** | **AnswerAI ColBERT** (ONNX) | Late-interaction semantic search (~200 MB resident memory). |

---

## ⚙️ Memory & Process Telemetry

- **Real-Time Memory Breakdown**: Tracks OS Baseline, Active Model RAM (`RssAnon`), llama.cpp engine, Kokoro TTS, and Orchestrator RSS in real time via `/api/metrics`.
- **RssAnon Accounting**: Reads anonymous heap memory to exclude mmap'd GGUF file pages, giving an accurate physical RAM usage readout alongside actual disk size.

---

## 🚀 Service Architecture & Endpoints

- **Backend Model Server**: `http://localhost:8081` (`llama-server`)
- **Orchestrator & Web UI**: `http://localhost:8085` (FastAPI orchestrator)

### Key Endpoints:
- `POST /v1/chat/completions`: Standard OpenAI-compatible completion endpoint with dynamic GBNF grammar constraints and auto-recovery retry logic.
- `POST /api/switch-model`: Swaps active model between Granite 4.1 3B and Qwen 2.5 Coder 3B dynamically.
- `GET /api/metrics`: Returns detailed system memory breakdown and dynamic GGUF disk sizes.
- `POST /api/settings`: Toggles Kokoro TTS and triggers immediate memory unloader when disabled.

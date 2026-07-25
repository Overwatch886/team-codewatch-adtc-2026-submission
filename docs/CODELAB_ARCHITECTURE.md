# 🚀 Antigravity CodeLab Architecture & Product Guide

**Antigravity CodeLab** is a 100% offline, privacy-first AI Pair-Programmer & Socratic Coding Tutor engineered specifically for 8GB system constraints.

---

## 🎯 Core Product Workflows

Antigravity CodeLab provides three specialized, interactive pair-programming workflows:

### 1. 🎓 Step-by-Step Socratic Tutor Mode
- **Purpose**: Interactive coding mentorship without full-code spoilers.
- **Behavior**: Outputs ONLY Step 1 + **Your Task**, then pauses generation, forcing the user to write their code before moving forward.
- **Hardware Optimization**: Enforces a strict 280-token generation budget + transition stop-sequences (`Step 2`, `Next, we`, `Finally,`).

### 2. 🐛 Debugging & Traceback Diagnostic Mode
- **Purpose**: Instant, plain-English error analysis for terminal tracebacks and broken scripts.
- **Behavior**: Pinpoints the exact line number, explains *why* the bug occurred with intuitive real-world analogies, and asks a probing question to help the user fix it.

### 3. 💻 Code Review & Refactor Mode
- **Purpose**: Code quality, performance, and readability optimization.
- **Behavior**: Analyzes submitted code, highlights edge cases, and provides clean, idiomatic refactored blocks with inline explanations.

---

## 🎙️ Interactive Voice & Multimodal Features

### 🔊 Text-to-Speech (Kokoro ONNX v1.0)
- **Model**: `Kokoro-82M` running via ONNX Runtime.
- **Spoken Code Verbalizer**: Automatically strips code fences and verbalizes symbols naturally (e.g., `def` -> "define", `()` -> "parentheses").
- **Automatic Unloader**: Disabling TTS on the sidebar instantly purges the model from RAM via `gc.collect()`, freeing 340 MB back to the OS.

### 🎙️ Hands-Free Interactive Voice Mode
- **Web Speech API**: Click 🎙️ next to the input box to start hands-free voice dictation.
- **Live Transcription & Auto-Submit**: Speech is transcribed live and automatically submitted when you finish speaking.
- **Spoken Audio Loop**: Combined with Kokoro TTS for a 100% hands-free conversational dialogue loop.

### 📄 Adaptive Document & Image Ingestion
- **Formats Supported**: `.py`, `.js`, `.ts`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), `.pdf`, `.png`, `.jpg` (Vision).
- **Small Documents (≤ 1,500 words)**: Direct context dumping into the prompt for 100% full-text accuracy.
- **Large Documents (> 1,500 words)**: Auto-indexed on-the-fly with AnswerAI ColBERT in ~0.25 seconds.

---

## 🧠 Dynamic Dual-Model Engine

| Model | Specs | Primary Role |
| :--- | :--- | :--- |
| **Granite 3.1 3B A800M Instruct** | 3.3B total / 800M active (IQ4_XS, 1.7 GB disk) | **Speed & Tutoring (30 t/s)**: Fast Socratic tutoring, concept breakdowns, general chat. |
| **Qwen 2.5 Coder 3B Instruct** | 3.1B dense parameters (Q4_K_M, 2.1 GB disk) | **Expert Code Specialist (9.1 t/s)**: Complex data structures (LRU caches), pointer math, 2D grid backtracking. |

---

## ⚙️ Hardware & VRAM Telemetry (8GB System Budget)

- **Physical System RAM**: 6.35 GiB usable physical RAM.
- **ZRAM State**: Permanently masked (`/dev/null`) to eliminate memory compression stutters.
- **Real-Time Memory Breakdown**: Tracks OS Baseline, Active LLM VRAM, llama.cpp overhead, Kokoro TTS, and Orchestrator RSS in real time via `/api/metrics`.

---

## 🚀 Service Architecture & Endpoints

- **Model Server**: `http://localhost:8081` (llama-server)
- **Orchestrator & Web UI**: `http://localhost:8085` (FastAPI orchestrator)

### Key Endpoints:
- `POST /v1/chat/completions`: Standard OpenAI-compatible completion endpoint with dynamic teacher prompt injection.
- `POST /api/switch-model`: Swaps active model between Granite 3.1 3B and Qwen 2.5 Coder 3B dynamically.
- `GET /api/metrics`: Returns detailed system VRAM, RAM, and breakdown metrics.
- `POST /api/settings`: Toggles Kokoro TTS and triggers immediate memory unloader when disabled.

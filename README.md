# 🎓 Code Persona / Antigravity CodeLab — Offline Voice-Driven AI Pair Programmer & Tutor

> **Africa Deep Tech Challenge 2026 Submission** | **Track:** `coding_assistants` | **Team:** `code-persona`

Code Persona (Antigravity CodeLab) is a 100% offline, privacy-first AI Pair Programmer and Socratic Coding Tutor designed to run on budget 8 GB RAM laptops with integrated graphics.

---

## 🌟 Key Features & Capabilities

- **🧠 Granite 4.0 H-Tiny Engine (`IQ4_XS` imatrix)**: Powered by IBM's hybrid Mamba/MoE architecture (3.3B parameters, 800M active), offering top-tier instruction following and linear context scaling under 8 GB RAM constraints.
- **🔒 Focus Workstation & Distraction-Free Kiosk Mode**: Tailored for technical education environments; suspends desktop background bloat (`tracker-miner`, `snapd`), freeing 600MB - 1.2GB of RAM while helping students maintain 100% focus.
- **🎙️ Parakeet TDT Push-to-Talk STT & User Review**: Speech is transcribed directly into the chat input box using Parakeet TDT, allowing users to review and edit their prompt before sending.
- **🎓 3-Mode Socratic Mentorship (GBNF Grammar Constrained)**:
  1. *Step-by-Step Tutor*: Outputs Step 1 + actionable task without full-code spoilers, constrained via GBNF grammar.
  2. *Traceback Diagnostic*: Explains Python/C/JS errors in plain English and gives hints.
  3. *Code Review & Refactoring*: Evaluates code readability, edge cases, and performance.
- **📄 Adaptive Multi-Format Document Ingestion**: Attach `.py`, `.js`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), or `.pdf` files.
  - Small files (≤ 1,500 words) dump directly into the context window.
  - Large files (> 1,500 words) are automatically indexed on-the-fly via ColBERT in ~0.25s.
- **⚙️ Real-Time 8GB Telemetry & Memory Guard**: Tracks OS Baseline, Model RAM (`--mlock`), Kokoro TTS, and system memory in real time via `/api/metrics`.

---

## 📁 Repository Structure

```
code-persona-adtc-2026-submission/
├── docs/
│   └── CODELAB_ARCHITECTURE.md ← Complete system architecture, GBNF rules & API guide
├── REPORT.md                  ← Detailed technical competition report & benchmarks
├── README.md                  ← Public repository documentation & usage guide
├── metadata.json              ← Required competition metadata & test prompts
├── download_model.sh          ← Model download script for llama.cpp runtime
├── acolbert.py                ← Local ColBERT Late-Interaction RAG & On-The-Fly Indexer
├── scripts/
│   ├── orchestrator_server.py ← Local FastAPI Orchestrator, TTS & Teacher Prompt Manager
│   ├── orchestrator.py        ← Query intent router & file context builder
│   ├── start-all-services-no-sudo.sh ← Single launcher script
│   ├── voice_type_parakeet.sh ← Push-to-talk STT transcription helper
│   └── speak.py               ← Kokoro TTS helper script
├── static/
│   ├── index.html             ← Modern Glassmorphism Web Dashboard & Voice Controls
│   ├── app.js                 ← Web Speech API, Model Swapper & Telemetry JS engine
│   └── style.css              ← Sleek Dark Mode UI Tokens & Micro-Animations
```

---

## 🚀 Quick Start Guide

### 1. Download Model Weights
Run the automated downloader script to fetch the quantized model weights:
```bash
bash download_model.sh
```

### 2. Launch All Local Services
Start the local model server, ColBERT vector indexer, and web orchestrator:
```bash
bash scripts/start-all-services-no-sudo.sh
```

### 3. Open Web Dashboard
Navigate to `http://localhost:8085` in your browser.

- Click 🎙️ for **Push-to-Talk Voice Dictation** (transcribes into input box for manual review).
- Click **🎓 Step-by-Step Socratic Tutor** to start an interactive lesson.
- Attach any `.pdf`, `.docx`, or `.py` file to ask questions about your documents offline.

---

## 📊 Benchmarks & Memory Optimization

Tested on **HP EliteBook 845 G7 (AMD Ryzen 5 PRO 4650U, 6.35 GiB usable RAM)**:

| Engine | Quantization | Resident RAM | Generation Speed |
| :--- | :--- | :--- | :--- |
| **Granite 4.0 H-Tiny** | `IQ4_XS` (imatrix) | **~2.5 GB - 3.5 GB** | **~28.6 t/s** (CPU Only, `--mlock`) |
| **Qwen 2.5 Coder 3B** | `Q4_K_M` | **~2.1 GB** | **9.1 t/s** (Dense Code Specialist) |
| **Kokoro TTS ONNX** | ONNX v1.0 | **340 MB** (Auto-purged) | Instant (0.3s audio latency) |
| **ColBERT RAG** | ONNX Late-Interaction | **~50 MB** | **0.02s** Search latency |

---

## 📄 License & Attribution

Licensed under [GNU General Public License v3.0](LICENSE).  
Built for the **Africa Deep Tech Challenge 2026**.

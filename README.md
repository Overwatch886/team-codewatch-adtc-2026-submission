# 🎓 Code Persona / Antigravity CodeLab — Offline Voice-Driven AI Pair Programmer & Tutor

> **Africa Deep Tech Challenge 2026 Submission** | **Track:** `coding_assistants` | **Team:** `code-persona`

Code Persona (Antigravity CodeLab) is a 100% offline, privacy-first AI Pair Programmer and Socratic Coding Tutor designed to run on budget 8 GB RAM laptops with integrated graphics.

---

## 🌟 Key Features & Capabilities

- **🎙️ Interactive Hands-Free Voice Mode**: Speak your coding questions or logic; live speech is transcribed and auto-submitted, while Kokoro TTS speaks the response back aloud.
- **🎓 3-Mode Socratic Mentorship**:
  1. *Step-by-Step Tutor*: Outputs Step 1 + actionable task without full-code spoilers.
  2. *Traceback Diagnostic*: Explains Python/C/JS errors in plain English and gives hints.
  3. *Code Review & Refactoring*: Evaluates code readability, edge cases, and performance.
- **📄 Adaptive Multi-Format Document Ingestion**: Attach `.py`, `.js`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), or `.pdf` files.
  - Small files (≤ 1,500 words) dump directly into the context window.
  - Large files (> 1,500 words) are automatically indexed on-the-fly via ColBERT in ~0.25s.
- **🧠 Dynamic Dual-Model Engine**:
  - **Granite 3.1 3B A800M Instruct** (30 tokens/sec) for rapid Socratic tutoring & concepts.
  - **Qwen 2.5 Coder 3B Instruct** (9.1 tokens/sec) for complex algorithms & data structures.
- **⚙️ Real-Time 8GB VRAM Telemetry**: Tracks OS Baseline, Model VRAM, Kokoro TTS, and system RAM in real time.

---

## 📁 Repository Structure

```
code-persona-adtc-2026-submission/
├── CODELAB_ARCHITECTURE.md   ← Complete system architecture & API guide
├── REPORT.md                  ← Detailed technical competition report & benchmarks
├── README.md                  ← Public repository documentation & usage guide
├── metadata.json              ← Required competition metadata & test prompts
├── download_model.sh          ← Model download script for llama.cpp runtime
├── acolbert.py                ← Local ColBERT Late-Interaction RAG & On-The-Fly Indexer
├── scripts/
│   ├── orchestrator_server.py ← Local FastAPI Orchestrator, TTS & Teacher Prompt Manager
│   ├── orchestrator.py        ← Query intent router & file context builder
│   ├── start-all-services-no-sudo.sh ← Single launcher script
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

- Click 🎙️ for **Hands-Free Interactive Voice Mode**.
- Click **🎓 Step-by-Step Socratic Tutor** to start an interactive lesson.
- Attach any `.pdf`, `.docx`, or `.py` file to ask questions about your documents offline.

---

## 📊 Benchmarks & Hardware Optimization

Tested on **HP EliteBook 845 G7 (AMD Ryzen 5 PRO 4650U, 6.35 GiB usable RAM)**:

| Engine | Generation Speed | Peak Memory | Use Case |
| :--- | :--- | :--- | :--- |
| **Granite 3.1 3B A800M** | **30.0 t/s** | 1.91 GB VRAM | Fast Chat, Socratic Tutoring, RAG |
| **Qwen 2.5 Coder 3B** | **9.1 t/s** | 2.10 GB VRAM | Complex Algorithms & Data Structures |
| **Kokoro TTS ONNX** | **Instant (0.3s)** | 340 MB (Auto-purged) | Spoken Audio Responses |
| **ColBERT RAG** | **0.02s Search** | In-Memory (~50MB) | On-the-Fly Document Retrieval |

---

## 📄 License & Attribution

Licensed under [GNU General Public License v3.0](LICENSE).  
Built for the **Africa Deep Tech Challenge 2026**.

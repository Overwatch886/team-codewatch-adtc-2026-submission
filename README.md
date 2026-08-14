# Professor Lowacode / — Offline Coding Tutor and Assistant

> **Africa Deep Tech Challenge 2026 Submission** | **Track:** `coding_assistants` | **Team:** `code-persona`

Professor Lowacode is a 100% offline AI Pair Programmer and Socratic Coding Tutor built to run on 8gb RAM systems with only CPUs and integrated graphics.

---

## Key Features

- **Bi-Modal Architecture**:
  - **Granite 4.1 3B (`Q4_K_M`)**: Primary Socratic Tutor model for step-by-step guidance and debugging without giving full-code answers to helps students learn by asking them probing questions and guiding them to the final answer rather thna just dumping it to them.
  - **Qwen 2.5 Coder 3B (`Q4_K_M`)**: Fast Ship coding model for direct code generation and full one time answers to help student sbuild fast when necessary.
- **Hard 4 GB RAM Ceiling Guard**: Enforces systemd cgroup bounds (`MemoryMax=4G`, `MemoryHigh=3.7G`) to keep the orchestrator, model server, and RAG search strictly bounded.
- **Parakeet TDT Push-to-Talk STT & User Review**: Speech is transcribed directly into the input box using Parakeet TDT, allowing users to review and edit prompts before sending.
- **3-Mode Socratic Mentorship (GBNF Grammar Constrained)**:
  1. *Step-by-Step Tutor*: Outputs Step 1 + actionable task without full-code spoilers, constrained via GBNF grammar.
  2. *Traceback Diagnostic*: Explains Python/C/JS errors in plain English and gives actionable hints.
  3. *Code Review & Refactoring*: Evaluates code readability, edge cases, and performance.
- **Adaptive Multi-Format Document Ingestion**: Attach `.py`, `.js`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), or `.pdf` files.
  - Small files (≤ 1,500 words) load directly into the context window.
  - Large files (> 1,500 words) are automatically indexed on-the-fly via ColBERT in ~0.25s.
- **Real-Time Telemetry & Precise Memory Accounting**: Tracks OS Baseline, Active Model RAM (`RssAnon`), llama.cpp engine, and dynamic GGUF disk sizes in real time via `/api/metrics`.

---

## Repository Structure

```
code-persona-adtc-2026-submission/
├── docs/
│   └── CODELAB_ARCHITECTURE.md   ← Complete system architecture & API guide
├── REPORT.md                    ← Detailed technical competition report & benchmarks
├── README.md                    ← Public repository documentation & usage guide
├── metadata.json                ← Required competition metadata & test prompts
├── download_model.sh            ← Benchmark model downloader script
├── download_models.sh           ← Supporting models downloader (Granite, Qwen, ColBERT, Audio)
├── install.sh                   ← Automated installer script (native Linux & Windows WSL2)
├── run_4gb_bounded_server.sh    ← Main memory-bounded server launcher script
├── requirements.txt             ← Python dependencies
├── acolbert.py                  ← Local ColBERT Late-Interaction RAG & On-The-Fly Indexer
├── build_colbert_index.py       ← Local document indexing script
├── scripts/
    |- orchestrator.py -- Contains extended orchestrator logic
│   ├── orchestrator_server.py   ← Local FastAPI Orchestrator, TTS & Teacher Prompt Manager
│   └── setup_system_permanently.sh ← System performance & memory tuning script
└── static/
    ├── index.html               ← Modern Glassmorphism Web Dashboard & Voice Controls
    ├── app.js                   ← Web Speech API, Model Swapper & Telemetry JS engine
    └── style.css                ← Sleek Dark Mode UI Tokens & Micro-Animations
```

---

## Quick Start Guide

### 1. Download Model Weights
Run the supporting model downloader to fetch Granite 4.1 3B, Qwen 2.5 Coder 3B, and ColBERT weights:
```bash
./download_models.sh
./download_model.sh
```

### 2. Run System Optimizations (Optional, recommended)
Configure system memory settings (4 GB `/dev/shm`, 12 GB swap, `swappiness=5`, unlimited memlock):
```bash
sudo ./scripts/setup_system_permanently.sh
```

### 3. Automated Installation
For native Linux (Ubuntu, Debian, Fedora, Arch) and Windows WSL2:
```bash
./install.sh
```

### 4. Launch Service Under Hard RAM Cap
Start the orchestrator server using the canonical launcher:
```bash
./start.sh
```
```
*(Or launch directly under 6 GB RAM cgroup enforcement with `./run_6gb_bounded_server.sh`).*

### 5. Open Web Dashboard
Navigate to `http://localhost:8085` in your browser. (If using WSL2, open `http://localhost:8085` directly in Windows browser).

---

## Benchmarks & Memory Breakdown

Tested under **Hard 4 GB RAM Ceiling** (`MemoryMax=4G`):

| Component | Target / Config | Resident Memory / Details |
| :--- | :--- | :--- |
| **Granite 4.1 3B** | `Q4_K_M` (Socratic Mode) | **~1.96 GB** on disk (mmap + `--mlock`), 10,240 ctx |
| **Qwen 2.5 Coder 3B** | `Q4_K_M` (Fast Ship Mode) | **~1.96 GB** on disk (mmap + `--mlock`), 10,240 (10k) ctx |
| **ColBERT RAG** | ONNX Late-Interaction | **~200 MB** resident |
| **Orchestrator FastAPI** | Uvicorn | **~40 MB** resident |
| **KV Cache** | `q8_0` Quantized | **~160 MB - 280 MB** |

---

## License & Attribution

Licensed under [GNU General Public License v3.0](LICENSE).  
Built for the **Africa Deep Tech Challenge 2026**.

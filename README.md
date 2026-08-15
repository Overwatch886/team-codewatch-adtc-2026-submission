# Professor Lowacode / — Offline Coding Tutor and Assistant

> **Africa Deep Tech Challenge 2026 Submission** | **Track:** `coding_assistants` | **Team:** `code-persona`

Professor Lowacode is a 100% offline AI Pair Programmer and Socratic Coding Tutor built to run on 8gb RAM systems with only CPUs and integrated graphics.

---

## Key Features
- **Dual Mode**:
  - **Socratic Tutor Mode**: In this mode, the model behaves like a tutor guiding the student by asking them probing question that can help them learn the answers to their request rather than just giving it to them.
  - **Build and Ship Fast Mode**: In this mode the model gives direct responses to the user request behaving more like a coding assistant rather than a tutor.

- **Primary Model**:
  - **Granite 4.0 h tiny (`IQ4_XS`)**: Primary model serving as both the socratic tutor and the build and ship fast model depending on the mode selected on the interface.
- **Hard 6 GB RAM Memory Ceiling**: Enforces systemd cgroup bounds (`MemoryMax=6G`, `MemoryHigh=5.7G`) to prevent the setup from using too much memory and causing out of memory crashes.
- **Parakeet TDT Push-to-Talk STT & User Review**: Speech is transcribed directly into the input box using Parakeet TDT audio model, allowing users to review and edit prompts before sending.

- **Document Uploads**: The setup allows the upload of `.py`, `.js`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), or `.pdf` files which depending on size are eithr dumped directly into the model context window if small in size or transformed into embeddings for extraction of only context relevant to the prompt if large(powered by the answerai colbert model).
- **Image Uploads**: Images can also be uploaded which are then described in context relevant to the prompt the by the LFM VL 1.2b vision model and the description is sent as context to Granite 4.0 h tiny.
- **Real-Time Memory Reporting**: Tracks Memory usage by extimating usage of OS processes and Active Model weights in RAM, llama.cpp engine all within the systemd cgroup limits to help track model memory usage`.
- **System Optimizations**: Running ```bash sudo ./scripts/setup_system_permanently.sh``` is hghly essential for the best model performance. It limits cpu power usage to save battery, increases size of swap memory, enables unlimited memlock and many other essential system optimizations.

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
├── run_6gb_bounded_server.sh    ← Main memory-bounded server launcher script
├── requirements.txt             ← Python dependencies
├── acolbert.py                  ← Colbert RAG script
├── build_colbert_index.py       ← Local document indexing script
├── scripts/
    |- orchestrator.py -- Contains extended orchestrator logic
│   ├── orchestrator_server.py   ← Local FastAPI Orchestrator, TTS & Teacher Prompt Manager
│   └── setup_system_permanently.sh ← System performance & memory tuning script
└── static/
    ├── index.html               ← Web Dashboard & Setup Control Options
    ├── app.js                   ← Web Speech API, Model Swapper & Telemetry JS engine
    └── style.css                ← Dashboard styling and Animations
```

---

## Quick Start Guide

### 1. Download Model Weights
Run the needed model weights:
```bash
./download_models.sh
./download_model.sh
```

### 2. Run System Optimizations (Optional, recommended)
Configure system settings for optimal model performance:
```bash
sudo ./scripts/setup_system_permanently.sh
```

### 3. Automated Installation
Now install the require software on native Linux (Ubuntu, Debian, Fedora, Arch) or on through Windows WSL2(must have been setup previously):
```bash
./install.sh
```

### 4. Launch Service Under Hard RAM Cap
Start the orchestrator server using the canonical launcher:
```bash
./start.sh
```



### 5. Open Web Dashboard
Navigate to `http://localhost:8085` in your browser. 

---

## Benchmarks & Memory Breakdown

Tested under **6 GB RAM Memory Ceiling** (`MemoryMax=6G`):

| Component | Target / Config | Resident Memory / Details |
| :--- | :--- | :--- |
| **Granite 4.1 3B** | `IQ4_XS` (Socratic Mode) | **~3.49 GB** on disk (mmap + `--mlock`), 8096 ctx |
| **ColBERT RAG** | ONNX Late-Interaction | **~200 MB** resident |
| **Orchestrator FastAPI** | Uvicorn | **~40 MB** resident |
| **Llama Server Memory Overhead** | Server | **~50 MB** resident |
| **KV Cache** | `q8_0` Quantized | **~160 MB - 280 MB** |

## Other Uses Cases
Beyond just being a coding tutor and assistant in our own setup dashboard, code persona can be used from any other software that supports OpenAI compatibe endpoints including VS code for as a live coding tutor and assistant the same way we use Github Copilot for auto-completing, asking questions and agentic tasks! Yes agentic tasks. It can also be used in Browser Extensions like Page Assist to give it access to web search tools or even in agentic frameworks like OpenClaw to give it access to a wider range of tools.
It can also be connected to tools like Open Interpreter for access to execute commands in your own terminal.

It features two open ai compatible endpoint:
1. At `http://localhost:8085` which holds our whole model architecture making it a multi modal setup able to accept text, image and document uploads and even audio requests(although audio requests compatibility might require extra setup). Depending on the model style preset in the web dashboard, the model behaviour on the endpoint can be configured to be either a socratic coding tutor or direct a coding assistant. But what if I am not after coding tasks at all. well. . .

2. The endpoint at `http://127.0.0.1:8080`, also open ai compatible, enables you to setup the primary model with your own system prompt for other tasks outside coding. This endpoint primary supports text input and might require bolting on other tools to support other media.
---

## License & Attribution

Licensed under [GNU General Public License v3.0](LICENSE).  
Built for the **Africa Deep Tech Challenge 2026**.

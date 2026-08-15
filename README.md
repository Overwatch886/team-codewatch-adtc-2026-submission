# Code Persona -- Offline Coding Tutor and Assistant

> **Africa Deep Tech Challenge 2026 Submission** | **Track:** `coding_assistants` | **Team:** `code-persona`

Code Persona is a 100% offline AI Pair Programmer and Socratic Coding Tutor built to run on 8 GB RAM systems with only CPUs and integrated graphics.

---

## Key Features
- **Dual Mode**:
  - **Socratic Tutor Mode**: In this mode, the model behaves like a tutor guiding the student by asking them probing questions that can help them learn the answers to their request rather than just giving it to them.
  - **Build and Ship Fast Mode**: In this mode the model gives direct responses to the user request behaving more like a coding assistant rather than a tutor.

- **Primary Model**:
  - **Granite 4.0 h tiny (`IQ4_XS`)**: Primary model serving as both the socratic tutor and the build and ship fast model depending on the mode selected on the interface.
- **Hard 6 GB RAM Memory Ceiling**: Enforces systemd cgroup bounds (`MemoryMax=6G`, `MemoryHigh=5.5G`) to prevent the setup from using too much memory and causing out of memory crashes.
- **Parakeet TDT Push-to-Talk STT & User Review**: Speech is transcribed directly into the input box using Parakeet TDT audio model, allowing users to review and edit prompts before sending.

- **Document Uploads**: The setup allows the upload of `.py`, `.js`, `.ts`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), or `.pdf` files which depending on size are either dumped directly into the model context window if small in size or transformed into embeddings for extraction of only context relevant to the prompt if large (powered by the AnswerAI ColBERT model).
- **Image Uploads**: Images can also be uploaded which are then described in context relevant to the prompt by the LFM 2.5 VL 1.6B vision model and the description is sent as context to Granite 4.0 H-Tiny.
- **Real-Time Memory Reporting**: Tracks memory usage by estimating usage of OS processes and active model weights in RAM, llama.cpp engine, all within the systemd cgroup limits to help track model memory usage.
- **System Optimizations**: Running `sudo ./scripts/setup_system_permanently.sh` is highly essential for the best model performance. It limits CPU power usage to save battery, increases size of swap memory, enables unlimited memlock and many other essential system optimizations.

---

## Repository Structure

```
code-persona-adtc-2026-submission/
├── docs/
│   └── CODELAB_ARCHITECTURE.md   <- Complete system architecture and API guide
├── REPORT.md                     <- Detailed technical competition report and benchmarks
├── README.md                     <- Public repository documentation and usage guide
├── metadata.json                 <- Required competition metadata and test prompts
├── download_model.sh             <- Benchmark model downloader script
├── download_models.sh            <- Supporting models downloader (Granite, ColBERT, Kokoro, Parakeet)
├── install.sh                    <- Automated installer script (native Linux and Windows WSL2)
├── run_6gb_bounded_server.sh     <- Main memory-bounded server launcher script
├── start.sh                      <- Primary launcher (activates venv, runs bounded server)
├── requirements.txt              <- Python dependencies
├── acolbert.py                   <- ColBERT RAG and intent routing engine
├── build_colbert_index.py        <- Local document indexing script
├── scripts/
│   ├── orchestrator.py           <- Extended orchestrator logic (intent routing, tool pruning, vision)
│   ├── orchestrator_server.py    <- FastAPI orchestrator, TTS and prompt persona manager
│   └── setup_system_permanently.sh <- System performance and memory tuning script
└── static/
    ├── index.html                <- Web dashboard and setup control options
    ├── app.js                    <- Streaming SSE, model swapper and telemetry JS engine
    └── style.css                 <- Dashboard styling and animations
```

---

## Quick Start Guide

### 1. Download Model Weights
Download the required model weights:
```bash
./download_models.sh
./download_model.sh
```

### 2. Run System Optimizations (Recommended)
Configure system settings for optimal model performance:
```bash
sudo ./scripts/setup_system_permanently.sh
```

### 3. Automated Installation
Install the required software on native Linux (Ubuntu, Debian, Fedora, Arch) or through Windows WSL2 (must have been set up previously):
## To install WSL on Windows
Run this command with powershell running as administrator
```powershell
wsl --install -d Ubuntu-22.04
```
After installation, reboot your system and then setup username and passsword.

**Linux users can start from here (WSL not needed)**
> Note that the installation would use up about 6-7GB while downloading so have it prepared

Now run this command to install required scripts and model weights:
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

## Benchmarks and Memory Breakdown

Tested under **6 GB RAM Memory Ceiling** (`MemoryMax=6G`):

| Component | Target / Config | Resident Memory / Details |
| :--- | :--- | :--- |
| **Granite 4.0 H-Tiny** | `IQ4_XS` (Single Resident LLM) | **~3.49 GB** on disk (mmap), 8192 ctx |
| **ColBERT RAG** | ONNX Late-Interaction | **~200 MB** resident |
| **Orchestrator FastAPI** | Uvicorn | **~50 MB** resident |
| **Llama Server Memory Overhead** | Server | **~20 MB** resident |
| **KV Cache** | `q8_0` Quantized | **~160 MB - 280 MB** |

## Other Use Cases
Beyond just being a coding tutor and assistant in our own setup dashboard, Code Persona can be used from any other software that supports OpenAI compatible endpoints including VS Code as a live coding tutor and assistant the same way we use Github Copilot for auto-completing, asking questions and agentic tasks. It can also be used in browser extensions like Page Assist to give it access to web search tools or even in agentic frameworks like OpenClaw to give it access to a wider range of tools.
It can also be connected to tools like Open Interpreter for access to execute commands in your own terminal.

It features two OpenAI compatible endpoints:
1. At `http://localhost:8085` which holds our whole model architecture making it a multimodal setup able to accept text, image and document uploads and even audio requests in the form of speech to text and even text to speech. Depending on the model style preset in the web dashboard, the model behaviour on the endpoint can be configured to be either a Socratic coding tutor or a direct coding assistant. But what if I am not after coding tasks at all?

2. The endpoint at `http://127.0.0.1:8081`, also OpenAI compatible, enables you to set up the primary model with your own system prompt for other tasks outside coding. This endpoint primarily supports text input and might require bolting on other tools to support other media.

---

## License and Attribution

Licensed under [GNU General Public License v3.0](LICENSE).  
Built for the **Africa Deep Tech Challenge 2026**.

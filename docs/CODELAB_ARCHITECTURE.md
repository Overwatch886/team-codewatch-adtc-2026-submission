# Code Persona Architecture and Product Guide

**Code Persona** (Professor LowaCode) is a 100% offline, privacy-first AI Pair Programmer and Socratic Coding Tutor engineered to operate within a **hard 6 GB RAM systemd cgroup ceiling** on budget laptops with 8 GB RAM, CPUs, and integrated graphics.

---

## Core Product Workflows

Code Persona provides two specialized, interactive pair-programming workflows driven by a single resident model with dynamic system-prompt persona switching:

### 1. Socratic Study Mode

- **Purpose**: Interactive coding mentorship that guides the student toward understanding rather than handing them answers.
- **Behavior**: Enforces the Professor LowaCode persona with a strict multi-step progression mandate (`Step N: [Focus]`), delivering a single step per turn with guiding questions and zero direct code block disclosures, forcing the user to write their own code before moving forward.

### 2. Build and Ship Fast Mode

- **Purpose**: Direct, production-grade coding assistance for rapid development.
- **Behavior**: Provides immediate, complete code solutions, refactoring guidance, debugging analysis, and architectural recommendations without the Socratic scaffolding.

Both modes are served seamlessly by the same resident Granite 4.0 H-Tiny model. Switching between modes swaps only the system prompt persona, eliminating any background model-loading latency.

---

## Memory Ceiling and Workstation Tuning

- **Target Hardware**: 8 GB RAM, integrated GPU, Ubuntu 22.04 -- matching the typical profile of a budget student or developer laptop.
- **Memory Ceiling Guard**: Enforces systemd cgroup v2 bounds (`MemoryMax=6G`, `MemoryHigh=5.5G`) via `systemd-run --scope --user`, keeping the entire orchestrator scope (including the spawned `llama-server` subprocess) strictly bounded. This leaves approximately 2 GB free alongside increased swap memory for the OS, desktop environment, browser, and other applications.
- **System Tuning** (`setup_system_permanently.sh`): A 7-step root-level script that configures:
  - 4 GB `/dev/shm` shared memory allocation
  - 12 GB persistent swap space
  - `vm.swappiness=5` (protects anonymous memory and KV cache from swap eviction)
  - `vm.dirty_ratio=20`, `vm.dirty_background_ratio=5`
  - Unlimited soft/hard `memlock` limits
  - CPU scaling governor set to `performance` with Transparent HugePages set to `madvise`
  - RyzenAdj power clamping (22W sustained/fast limit, 82C thermal ceiling)
  - AMD iGPU GTT memory allocation set to 5096 MB; Intel iGPU GuC/HuC hardware submission enabled

---

## Reasoning Engine and Model Architecture

Code Persona uses a **single-model architecture** powered by one resident LLM. Mode switching is achieved through dynamic system-prompt persona swapping, not model file swapping.

| Component | Model / Spec | Configuration and Details |
| :--- | :--- | :--- |
| **Resident LLM** | **Granite 4.0 H-Tiny** (`IQ4_XS`) | Single resident model serving both Socratic and Fast Ship modes (~3.5 GB on disk). MoE architecture enables better inference speeds. |
| **Context Window** | 8,192 tokens | `LLAMA_CTX_SIZE=8192` |
| **Batch / Micro-Batch** | 2048 / 512 | `LLAMA_BATCH_SIZE=2048`, `LLAMA_UBATCH_SIZE=512` |
| **KV Cache** | `q8_0` quantized | `-ctk q8_0 -ctv q8_0`, 8-bit quantized context cache to minimize memory overhead under long contexts. |
| **Memory Load Mode** | `--mmap` | Memory-maps the GGUF model file into the process address space. Pages are loaded from disk into RAM on demand, reducing cold-start time. |
| **Cache RAM** | 64 MB | `LLAMA_CACHE_RAM=64` |
| **RAG Engine** | **AnswerAI ColBERT** (`model_int8.onnx`) | ONNX-quantized late-interaction semantic search (~200 MB resident). |
| **Vision Model** | **LFM 2.5 VL 1.6B** (`Q4_0`) | Invoked on demand via `llama-cli` for image description; not permanently resident in RAM (~1.1 GB when active). |
| **TTS Engine** | **Kokoro v1.0** (ONNX, 82 MB) | `af_heart` voice variant. Unloadable on toggle, reclaiming ~340 MB. |
| **STT Engine** | **Parakeet TDT v2** (0.6B, `q5_k`) | Push-to-talk voice typing via `parakeet-cli`. |

### GPU Auto-Detection

The orchestrator automatically detects available GPU acceleration at startup:

- **NVIDIA**: Uses CUDA (`-DGGML_CUDA=ON`)
- **AMD**: Uses Vulkan (`-DGGML_VULKAN=ON`)
- **Intel**: Evaluates Level Zero/SYCL, then OpenCL, then Vulkan, then CPU fallback
- **CPU-only**: Falls back to native CPU (`-DGGML_NATIVE=ON`)

When a GPU is detected, the orchestrator offloads 25 model layers to the iGPU (`-ngl 25`) and sets CPU threads to half the physical cores. In CPU-only mode, all physical cores are used with zero layer offload.

---

## Interactive Voice and Multimodal Features

### Text-to-Speech (Kokoro ONNX v1.0)

- **Model**: `kokoro-v1.0.onnx` with `voices-v1.0.bin` via ONNX Runtime CPU.
- **Spoken Code Verbalizer**: Automatically strips code fences and verbalizes programming symbols naturally (e.g., `def` becomes "define", `==` becomes "is equal to", `(` becomes "open paren").
- **Automatic Unloader**: Disabling TTS on the sidebar instantly purges the Kokoro model from RAM via `gc.collect()`, freeing approximately 340 MB back to the OS.
- **TTS State Persistence**: TTS toggle state is saved to `scratch/tts_settings.json` across sessions.

### Parakeet TDT Push-to-Talk STT

- **Engine**: Parakeet TDT Multilingual v2 (`tdt-0.6b-v2-q5_k.gguf`) via `parakeet-cli`.
- **User Review and Edit**: Speech is transcribed directly into the text input box using the HTML5 `MediaRecorder` API, allowing the user to inspect, edit, or augment the prompt before manually sending to the model.

### Adaptive Document Ingestion

- **Formats Supported**: `.py`, `.js`, `.ts`, `.json`, `.md`, `.txt`, `.docx` (Microsoft Word), `.pdf`.
- **Small Documents (up to 6,000 characters)**: Injected directly into the prompt context for full-text accuracy.
- **Large Documents (over 6,000 characters)**: Auto-indexed on-the-fly with AnswerAI ColBERT in approximately 0.25 seconds. The top-3 most relevant excerpts are retrieved and injected as context.

### Vision Pipeline

- **Model**: LFM 2.5 VL 1.6B (`LFM2.5-VL-1.6B-Q4_0.gguf`) with multimodal projector (`mmproj-LFM2.5-VL-1.6b-Q8_0.gguf`).
- **Execution**: Invoked via `llama-cli` in pure CPU mode (`GGML_VK_DISABLE=1`, `-ngl 0`, `-c 512`, `-n 256`, `-t 2`) to extract visual descriptions and OCR without directly answering the user query. The description is then passed as context to the resident Granite model.
- **Memory**: Not permanently resident; loaded only for the duration of the vision request (~1.1 GB when active).

---

## Intent Routing and Dynamic Tool Pruning

### ColBERT Intent Classification

The orchestrator uses the ColBERT model for semantic intent routing. Canonical intent definitions (`RAG`, `VISION`, `CODE`, `GENERAL`) are pre-encoded, and each incoming user query is scored against them via ColBERT `maxsim` to determine the optimal execution pipeline.

### Dynamic Tool Pruning

When the model uses tool-calling capabilities, ColBERT MaxSim scoring is applied between the user query and available tool specifications. A whitelist of core tools (`bash`, `execute_command`, `exec`, `read`, `write`, `edit`, `apply_patch`, `web_search`, `web_fetch`) is always retained, plus the top-k dynamically relevant tools are added based on semantic similarity.

### System Prompt Pruning

For long system prompts, the orchestrator chunks the prompt by Markdown headers, preserving core persona instructions while selecting only the top-k semantically relevant context sections via ColBERT scoring. This keeps the prompt within manageable token budgets.

---

## Memory Budget Breakdown

RAM allocation under the 6 GB systemd cgroup ceiling (`MemoryMax=6G`):

| Component | Estimated Memory | Notes |
| :--- | :--- | :--- |
| **Granite 4.0 H-Tiny (IQ4_XS)** | ~3.5 GB | Resident LLM weights (mmap) |
| **KV Cache (8192 ctx, q8_0)** | ~160--280 MB | Varies with active context length |
| **ColBERT RAG (ONNX)** | ~200 MB | In-process via `acolbert.py`, also used for intent routing |
| **Kokoro TTS (ONNX)** | ~340 MB | Only when TTS is enabled; unloaded when disabled |
| **Orchestrator (FastAPI)** | ~50 MB | Uvicorn server overhead |
| **llama.cpp Engine** | ~20 MB | Server process overhead |
| **OS Baseline** | ~200 MB | OS processes within the systemd cgroup |
| **Vision Model** | ~1.1 GB | On-demand only; not permanently resident |
| **Total (steady state)** | ~4.2--5.3 GB | Well under the 6 GB ceiling |

---

## Process Telemetry

- **Real-Time Memory Breakdown**: The `/api/metrics` endpoint tracks OS Baseline, Active Model RAM (`RssAnon`), llama.cpp engine overhead, prompt cache tokens, Kokoro TTS, ColBERT, Vision engine, and Orchestrator RSS in real time by reading cgroup v2 `memory.stat` (`anon + file + shmem`).
- **RssAnon Accounting**: Reads anonymous heap memory to exclude mmap'd GGUF file pages, providing an accurate physical RAM usage readout alongside actual disk size.
- **AMD APU VRAM/GTT Monitoring**: Reads GPU memory allocation via `/proc/{pid}/fdinfo` for AMD integrated graphics.
- **Prompt Cache Tracking**: Queries the llama-server `/slots` endpoint for current prompt cache token counts.

---

## Service Architecture and Endpoints

- **Backend Model Server**: `http://127.0.0.1:8081` (`llama-server` -- the llama.cpp inference server)
- **Orchestrator and Web UI**: `http://localhost:8085` (FastAPI orchestrator serving the web dashboard)

### API Endpoints

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the web dashboard (`static/index.html`) |
| `GET` | `/v1/models` | Proxies available models from the llama-server on port 8081 |
| `GET` | `/models` | Alias for `/v1/models` |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions with streaming (SSE). Handles base64 image decoding, document ingestion (PDF, DOCX, source files), ColBERT intent routing, dynamic tool pruning, and real-time code-aware TTS sentence buffering. |
| `POST` | `/api/switch-model` | Switches session mode between `socratic_study` and `fast_ship` and verifies Granite model residency |
| `POST` | `/set_session_mode` | Updates the active session mode |
| `GET` | `/api/metrics` | Returns detailed system memory breakdown, cgroup v2 RAM limit/usage, per-process memory, and dynamic GGUF disk sizes |
| `GET` | `/api/settings` | Returns current settings state (TTS enabled/disabled) |
| `POST` | `/api/settings` | Persists TTS toggle and triggers immediate Kokoro model unload when disabled |
| `POST` | `/v1/audio/speech` | Kokoro ONNX text-to-speech endpoint (supports WAV, MP3, FLAC output) |
| `POST` | `/audio/speech` | Alias for `/v1/audio/speech` |
| `POST` | `/v1/audio/transcriptions` | Offline Parakeet TDT speech-to-text endpoint via `parakeet-cli` and `ffmpeg` |
| `POST` | `/audio/transcriptions` | Alias for `/v1/audio/transcriptions` |
| `GET` | `/favicon.ico` | Returns 204 No Content |

### Auto-Recovery

If the `llama-server` process on port 8081 crashes or becomes unresponsive, the orchestrator automatically detects the failure, restarts the server process, and retries the pending request before returning an error to the client.

---

## Web Dashboard

The web dashboard at `http://localhost:8085` provides a full-featured interface:

### Sidebar
- **Settings Panel**: Session mode selector (Socratic Study vs Fast Ship), temperature control (default 0.2), max tokens (default 2048), text-to-speech toggle.
- **System Metrics Panel**: Real-time RAM progress bar with percentage and used/total GB, expandable memory breakdown card showing per-component allocation (OS Baseline, Active Model, llama.cpp Engine, Prompt Cache, Vision Engine, ColBERT, Kokoro TTS, Orchestrator, Total Allocated), manual refresh button, and service status indicator. Metrics auto-poll every 8 seconds.

### Chat Area
- **Header**: Active mode indicator badge, mode switcher tabs (Step-by-Step Socratic / Fast Ship and Direct Code), clear chat history button.
- **Messages Area**: Welcome message from Professor LowaCode with quick action chips. Custom markdown renderer with fenced code blocks, language labels, and copy-to-clipboard buttons. "Professor LowaCode is writing" animation with animated pen-nib stroke and pulsing dots.
- **Input Footer**: Multi-file attachment support (images, PDF, DOCX, source files) with preview strip, microphone button for offline voice input via Parakeet TDT, auto-expanding textarea, and send button.

### Design
- Cyber-dark theme with purple accent gradients, emerald green status indicators, amber warnings, and red error states.
- Google Fonts 'Outfit' typography with monospace code blocks.
- Glassmorphism sidebar with full-viewport responsive layout.
- Custom animations for tutor writing state, microphone recording pulse, and badge glow effects.

# Technical Report — Code Persona: An Offline Socratic Coding Tutor

**Team ID:** code-persona  
**Domain:** coding_assistants  
**Primary Model:** granite-4.0-h-tiny.i1-IQ4_XS.gguf (Single Resident LLM for Socratic Tutor & Ship Fast Modes)  

---

## Problem

For every computer science student, the crowded lecture hall and limited practical equipments always leave the student unfulfilled after every lecture. There is always a need to understand more and practicalize what they have learnt. LLMS are usually the next options in the mind of students, until they visit the LLM site and oops, poor internet connection becomes the next hindrance. Professor Lowacode is here to solve that by bring the tutoring capabilities of cloud LLMs on device for them serving as  home tutors on device for coding tasks and concepts.

Code Persona is an offline system that orchestrates specialized local models for speech transcription, intent routing, document retrieval, code reasoning, and spoken response generation — powered by a single resident **Granite 4.0 H Tiny iQ4_K_S** (also known as Professor Lowacode) modelrunning within a strict **6 GB systemd cgroup ceiling**, operating fully offline.

---

## Design Decisions

### Core LLM Selection

Many model architectures were reviewed in choosing the engine of Code Persona. Efficient architectures that do not require high CPU overhead or high RAM usage under long context windows were specifically explored.

We first explored one-bit ternary models, primarily Prism LM Ternary Bonsai models and Microsoft BitNet models. We immediately targeted Q4_K_M quantization as it balances both performance and accuracy. But the ternary Bonsai and BitNet modules were not good enough for our coding needs or needed long thinking sessions to achieve optimal performance

We also explored the LFM models powered by Liquid AI. These models are purpose-made for edge hardware with blazing fast inference speeds of 20 tokens/sec and above. However, Liquid AI specifically do not recommend LFM modules for code-related tasks due to their architecture. So the LFM models, despite their speed, could not serve as Code Persona's reasoning brain.

Through extensive benchmarking across Granite 4.0 H micro, Granite 4.0 H tiny, Granite 4.1 3B, Granite 3.1 3b A800M, Qwen 2.5 3b Coder, Gemma and Nvidia M=Nemotron models. We arrived at a **single-model architecture** powered by **Granite 4.0 H Tiny Q4_K_S** (`granite-4.0-h-tiny.i1-IQ4_XS.gguf`). Granite 4.0 H Tiny delivers exceptional code understanding and reasoning as well as tool calling while fitting within memory constraints when configured. It required careful tuning for optimal performance under memory constraints compared to the other granite and qwen model. Despite this, granite 4.0 h tiny stood out due to its exception coding perfromance and tool calling abilities with better inference speeds due to its MoE architecture. Both Socratic Tutor Mode and Build & Ship Fast Mode are served seamlessly by this single resident model via dynamic system-prompt persona switching, eliminating background model-swapping overhead.

A different setup was actually built in the feature/dual-model-setup branch in this repo which uses a dual model architecture but this setup was not choosen because of better generation speeds and model swapping lateency. That setup though is more memory efficient and functions smoothly under a 4g ram systemd cgroups memory limit.

Other architectures explored include Test Time Training (TTT), Google Griffin, subquadratic state spaces, and Liquid Neural Networks — but most were not yet deployable through `llama.cpp` at the time of building.

### Memory Strategy: mmap + mlock Over No-Mmap

The original submission used `--no-mmap` to prevent kernel memory mapping and reduce peak RSS. After further benchmarking, we switched to `--mmap --mlock` for the current architecture:

- **`--mmap`**: Memory-maps the GGUF model file into the process address space. The file is read directly from disk into RAM as pages are needed, rather than loading the full model upfront. This reduces cold-start time significantly.
- **`--mlock`**: Pins all mapped pages into physical RAM, preventing the Linux kernel from ever evicting model weight pages to swap. Once warm, the model is fully resident with zero paging stutter during inference.
- **`vm.swappiness=5`**: Configured system-wide to strongly prefer reclaiming page cache (including any non-locked file mappings) before touching anonymous pages (KV cache, Python heap). This protects inference latency from swap pressure.

This combination delivers faster warmup than `--no-mmap` while achieving the same RAM stability guarantee, with `--mlock` providing stronger protection than `--no-mmap` alone.

### Memory Ceiling: 6 GB Systemd Cgroup Enforcement

The memory ceiling was tightened from 7 GB to **6 GB** via systemd cgroup v2 enforcement:

```bash
systemd-run --scope --user -p MemoryMax=6G -p MemoryHigh=5.7G
```

This applies to the entire orchestrator scope, including the spawned `llama-server` subprocess (both processes share the same `cgroup.procs`). The cgroup `memory.stat` (`anon + file + shmem`) provides the authoritative total, and all memory accounting in `/api/metrics` is derived from this source.

### Voice Stack Selection

For speech-to-text, OpenAI Whisper large-v3-turbo was evaluated via `whisper.cpp` but found to be too slow for interactive voice sessions on the target hardware (AMD Ryzen 5 PRO 4650U). The reason is architectural: Whisper uses an **autoregressive encoder-decoder** that generates tokens sequentially, which is inherently higher latency than the **Transducer/CTC-based** approach used by NVIDIA's Parakeet and Nemotron models. Parakeet TDT and Nemotron 3.5 ASR achieve RTFx scores exceeding 3,000× on similar hardware — they process a 3-second utterance in well under 1 second — because they predict all output tokens in a single non-autoregressive pass.

Two STT models are used for different interaction modes:
- **Nemotron 3.5 ASR Streaming (0.6B)** for live interactive voice sessions — transcribes word-by-word in real time
- **Parakeet TDT v2 (0.6B)** for push-to-talk voice typing directly into the chat input box

For text-to-speech, `spd-say` was rejected immediately due to robotic voice quality. The LFM Audio vocoder was considered, but **Kokoro v1.0 (ONNX)** was selected for TTS due to its 82 MB footprint, near-real-time CPU inference, and natural-sounding voice output. Kokoro includes an African-cadence voice variant (`af_heart`) that is particularly well suited to this project's target user base.

### RAG and Intent Routing

A custom ONNX-quantized ColBERT retrieval model (AnswerAI `answerai-colbert-small-v1`) performs late-interaction semantic search over indexed documents — including computer science curricula, code files, and documentation — enabling the tutor to answer questions grounded in materials the student has actually studied, not just generic internet knowledge. Documents under 1,500 words load directly into the context window; larger documents are indexed on-the-fly in approximately 0.25 seconds. The orchestrator routes between **Socratic Tutor**, **Ship Fast Coder**, **RAG Document Query**, and **Auto** modes using ColBERT retrieval confidence scoring combined with lightweight intent pattern matching.

---

## Constraints

The target hardware as specified by the competition is 8 GB RAM, integrated GPU, and Ubuntu 22.04. This matches the typical profile of a budget student or developer laptop in an African context. Code Persona targets pure CPU inference via `llama.cpp` with C/C++ optimized backends.

The design with a **hard 4 GB systemd cgroup ceiling** (`MemoryMax=4G`) ensures the system operates with significant headroom below the 8 GB physical limit — leaving the remaining ~4 GB free for the OS, desktop environment, browser, and other student applications running alongside it.

Additional real-world constraints that shaped the design:
- **No stable internet** — all models run fully offline; zero external API calls during inference
- **Battery and power constraints** — the system uses `--mmap --mlock` and power-clamping techniques via RyzenAdj (22W limit, 83°C thermal ceiling) to limit CPU thermal output and preserve battery life
- **Broken or inaccessible keyboards** — voice-first design removes the dependency on physical keyboard quality
- **System persistence** — `setup_system_permanently.sh` configures `/dev/shm` (4 GB), swap (12 GB), `swappiness=5`, `vm.dirty_ratio=20`, and unlimited `memlock` limits persistently across reboots

---

## Benchmarks

Benchmarks vary based on the optimization techniques used. The key optimization targets were the `--mmap --mlock` flags in `llama.cpp` (to use memory-mapped loading while pinning weights into physical RAM) and CPU power clamping via RyzenAdj (to prevent thermal throttling on sustained inference loads).

We report two sets of numbers:

### 1. Current Architecture (Host Machine — `--mmap --mlock`, Hard 4 GB Cgroup)

Benchmarking the updated system my personal machine — an **HP EliteBook 845 G7** powered by an **AMD Ryzen 5 PRO 4650U** — under the hard 4 GB systemd cgroup ceiling (`MemoryMax=4G`, `MemoryHigh=3.7G`) with `--mmap --mlock` and 8-bit quantized KV cache:

| Component | Resident Memory | Notes |
| :--- | :--- | :--- |
| **Granite 4.1 3B** (active) | ~310–380 MB `RssAnon` | Physical heap only; excludes mmap'd file pages |
| **Qwen 2.5 Coder 3B** (active) | ~310–380 MB `RssAnon` | Physical heap only; excludes mmap'd file pages |
| **GGUF on Disk** | 1.96 GB | Both models `Q4_K_M` — same size |
| **KV Cache (Granite, 4k ctx)** | ~128–280 MB | `q8_0` quantized keys and values |
| **KV Cache (Qwen, 10k ctx)** | ~128–160 MB | 10k context stays under 160 MB with `q8_0` |
| **llama.cpp Engine** | ~5–30 MB | Thread pools, GGML context buffers |
| **ColBERT RAG (ONNX)** | ~200 MB | In-process via `acolbert.py` |
| **Orchestrator (FastAPI)** | ~40–60 MB | Python heap after ColBERT subtraction |
| **OS Baseline** | ~200–400 MB | Kernel, page tables, filesystem buffers |
| **Total (cgroup)** | **~1.5–1.7 GB** | Well under the 4 GB `MemoryMax` ceiling |

> [!NOTE]
> Memory reporting uses **`RssAnon`** (anonymous heap RAM from `/proc/PID/status`) rather than `VmRSS`. `VmRSS` incorrectly includes memory-mapped GGUF file pages and inflates the reading to nearly the full 1.96 GB disk size. `RssAnon` gives an accurate picture of what the process has actually allocated in physical RAM.

### 2. Previous Architecture (Docker — `--no-mmap`, 7.5 GB Cap)

Running the original Granite 4.0 H-Tiny model inside the ADTC Docker container (which enforces a **7.5 GB RAM memory ceiling**, uses `--no-mmap` to disable memory mapping, and clamps CPU load) on the same machine resulted in a peak RAM of **4.16 GB**, a time to first token of **32.72 seconds**, and a generation speed of **9.38 tokens per second**. No thermal throttling was observed, and peak CPU temperatures remained safe at **68.0°C**.

### Performance Metrics Comparison

| Metric | v1 — Granite 4.0 H-Tiny (Docker, `--no-mmap`) | Current — Granite 4.1 3B / Qwen 2.5 Coder 3B |
| :--- | :--- | :--- |
| **Machine** | HP EliteBook 845 G7 | HP EliteBook 845 G7 |
| **CPU** | AMD Ryzen 5 PRO 4650U | AMD Ryzen 5 PRO 4650U |
| **Optimizations** | `--no-mmap` + `--mlock` + 7.5 GB RAM cap | `--mmap` + `--mlock` + **4 GB cgroup ceiling** |
| **Peak RAM (cgroup total)** | ~4.16 GB (4160.79 MB) | **~1.5–1.7 GB** |
| **Memory Ceiling** | 7.5 GB | **4 GB** |
| **Time to First Token** | ~32.72 seconds (cold, `--no-mmap`) | ~3–8 seconds (mmap warm pages) |
| **Generation Speed** | ~9.38 tokens/sec | ~16–22 t/s (Granite) / ~9–14 t/s (Qwen) |
| **Context Window** | 4,096 tokens | 4,096 (Granite) / **10,240 (Qwen)** |
| **Thermal Behavior** | Peak 68.0°C / No Throttling | Peak 68–75°C / No Throttling |
| **Model Hot-Swap** | Not supported | Dynamic hot-swap (single `llama-server`) |

> [!NOTE]
> The `--mmap --mlock` combination recovers the large Time to First Token penalty of `--no-mmap` (~32 s cold start → ~3–8 s), while `--mlock` pins all model weight pages into physical RAM, giving the same swap-safety guarantee. The tightened 4 GB ceiling (down from 7.5 GB) leaves significantly more headroom for the student's OS, browser, and IDE running on the same 8 GB machine.

*Note: These are self-reported development benchmarks. Official scores are measured by the ADTC profiler on the standard evaluation machine.*
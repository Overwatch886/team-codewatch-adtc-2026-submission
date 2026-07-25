# Technical Report — Code Persona: An Offline Voice-Driven Pair Programmer

**Team ID:** code-persona  
**Domain:** coding_assistants  
**Model:** granite-4.0-h-tiny-Q4_K_M.gguf  

---

## Problem

For the average African programmer or technical student, the workflow always involves copying code problems from their device or screenshotting it and sending it all the way to cloud LLMs. This workflow is quite rigid and slows down the engineer's work process as well as restricts the capabilities of the models. Cloud models are also quite expensive to use for the average African, plus with issues such as poor network connectivity, the code project to be finished today might just be stopped in its tracks by bad weather or an exhausted API limit.

Code Persona aims to solve this problem by bringing a personal pair programmer to the laptops of the average African student and technician. Code Persona runs on budget hardware of 8 GB RAM with integrated graphics only, with **zero internet dependency**. It functions as both a coding tutor and a coding assistant simultaneously — it builds code alongside the student while explaining the logic behind every decision, so they learn while they ship.

Beyond the screen, Code Persona solves a second, often overlooked problem: **physical interaction constraints**. Many African students learn on second-hand or partially broken laptops where keyboards are unreliable, sticky, or missing keys. Code Persona is driven entirely by voice — students speak their logic and the assistant types, explains, and runs the code for them. This also benefits developers whose hands are occupied (working at a workbench, a lab, or a field environment) who cannot easily type but still need to interface with code.

Code Persona is a multi-agent system that dynamically orchestrates specialized local models for speech transcription, intent routing, document retrieval, code reasoning, and spoken response generation — all within a strict 8 GB RAM budget, running fully offline on CPU-only hardware.

---

## Design Decisions

### Core LLM Selection

Many model architectures were reviewed in choosing the engine of Code Persona. New architectures that do not require high CPU overhead or high RAM usage under long context windows were specifically explored.

We first explored one-bit ternary modules, majorly Prism LM Ternary Bonsai models and Microsoft BitNet models. We immediately targeted Q4_K_M quantization as it balances both performance and accuracy. But the ternary Bonsai and BitNet modules suffered high RAM usage on long context windows due to their transformer-based architecture — context window growth was quadratic, restricting workflows to short-context use cases only.

We also explored the LFM models powered by Liquid AI. These models are purpose-made for edge hardware with blazing fast inference speeds of 10 tokens/sec and above. However, Liquid AI specifically do not recommend LFM modules for code-related tasks due to their architecture. So the LFM models, despite their speed, could not serve as Code Persona's reasoning brain.

We also explored Granite 4.0 H micro, Granite 4.0 H tiny, Granite 4.1 3B, and Granite 4.1 8B, as well as Gemma E2B, Gemma E4B, Nemotron Nano 4B, Qwen 3.5 4B, and Qwen 2.5 1.5B/3B. The standout model was **Granite 4.0 H tiny** due to its Mixture of Experts (MoE) hybrid architecture combining transformer blocks with Mamba layers. This design keeps RAM usage stable under high context windows. Despite having 7 billion total parameters, only approximately 1 billion are active during any single inference pass — delivering 10–12 tokens/sec on CPU while maintaining IBM-validated code generation quality.

Other architectures explored include Test Time Training (TTT), Google Griffin, subquadratic state spaces, and Liquid Neural Networks — but most were not yet deployable through `llama.cpp` at the time of building.

### Voice Stack Selection

For speech-to-text, OpenAI Whisper large-v3-turbo was evaluated via `whisper.cpp` but found to be too slow for interactive voice sessions on the target hardware (AMD Ryzen 5 PRO 4650U). The reason is architectural: Whisper uses an **autoregressive encoder-decoder** that generates tokens sequentially, which is inherently higher latency than the **Transducer/CTC-based** approach used by NVIDIA's Parakeet and Nemotron models. Parakeet TDT and Nemotron 3.5 ASR achieve RTFx scores exceeding 3,000× on similar hardware — they process a 3-second utterance in well under 1 second — because they predict all output tokens in a single non-autoregressive pass.

Two STT models are used for different interaction modes:
- **Nemotron 3.5 ASR Streaming (0.6B)** for live interactive voice sessions — transcribes word-by-word in real time
- **Parakeet TDT v2 (0.6B)** for push-to-talk voice typing directly into the IDE/terminal

For text-to-speech, `spd-say` was rejected immediately due to robotic voice quality. The LFM Audio vocoder was considered, but **Kokoro v1.0 (ONNX)** was selected for TTS due to its 82 MB footprint, near-real-time CPU inference, and natural-sounding voice output. Kokoro includes an African-cadence voice variant (`af_heart`) that is particularly well suited to this project's target user base.

### RAG and Intent Routing

A custom ONNX-quantized semantic router (based on a GLiner-style embedding model) performs intent classification into four categories: `RAG`, `CODE`, `VISION`, and `GENERAL`. File path entities are extracted via regex. For RAG queries, a ColBERT ONNX retrieval model performs late-interaction semantic search over indexed documents — including computer science curricula, code files, and documentation — enabling the tutor to answer questions grounded in materials the student has actually studied, not just generic internet knowledge.

---

## Constraints

The target hardware as specified by the competition is 8 GB RAM, integrated GPU, and Ubuntu 22.04. This matches the typical profile of a budget student or developer laptop in an African context. Code Persona targets pure CPU inference via `llama.cpp` with C/C++ optimized backends.

The multi-agent orchestration design ensures that no two heavy models are loaded into RAM simultaneously. The speech model, reasoning model, and TTS model load and unload on demand — keeping peak memory usage within the 8 GB ceiling without crashing the system.

Additional real-world constraints that shaped the design:
- **No stable internet** — all models run fully offline; zero external API calls during inference
- **Battery and power constraints** — the system uses `--no-mmap` and power-clamping techniques to limit CPU thermal output and preserve battery life
- **Broken or inaccessible keyboards** — voice-first design removes the dependency on physical keyboard quality

---

## Benchmarks

Benchmarks vary based on the optimization techniques used. The key optimization targets were the `--no-mmap` flag in `llama.cpp` (to eliminate disk paging and reduce peak RSS) and CPU power clamping (to prevent thermal throttling on sustained inference loads).

We report two sets of numbers:

### 1. Standard Run (ADTC Profiler — Host Machine)
Benchmarking the model using the standard ADTC profiler directly on the host machine—an **HP EliteBook 845 G7** powered by an **AMD Ryzen 5 PRO 4650U**—resulted in a peak RAM usage of approximately **7.2 GB**, a time to first token of **6.28 seconds**, and a generation speed of **11.28 tokens per second**. However, thermal throttling was observed under sustained load as core temperatures peaked at 100°C.

### 2. Docker Run (ADTC Profiler — Containerized and Optimized)
Running the model inside the ADTC Docker container (which enforces a **7.5 GB RAM memory ceiling**, uses `--no-mmap` to disable memory mapping, and clamps CPU load) on the same machine resulted in a peak RAM of **4.16 GB**, a time to first token of **32.72 seconds**, and a generation speed of **9.38 tokens per second**. No thermal throttling was observed, and peak CPU temperatures remained safe at **68.0°C**.

> [!NOTE]
> The `--no-mmap` flag trades prompt processing latency (Time to First Token) for a 42% reduction in peak RAM usage — dropping from 7.22 GB to 4.16 GB. This is the correct trade-off for budget hardware: staying inside the memory ceiling matters more than fast cold-start latency, especially for a conversational tutor where the user is not waiting for a one-shot result but is engaged in a back-and-forth session.

### Performance Metrics Table

| Metric | Standard Run (Host Profiler) | Docker Run (Containerized) |
| :--- | :--- | :--- |
| **Machine** | HP EliteBook 845 G7 | HP EliteBook 845 G7 |
| **CPU** | AMD Ryzen 5 PRO 4650U | AMD Ryzen 5 PRO 4650U |
| **Optimizations** | Default `llama.cpp` settings | `--no-mmap` + `--mlock` + 7.5 GB RAM cap |
| **Peak RAM (RSS)** | ~7.22 GB (7218.62 MB) | ~4.16 GB (4160.79 MB) |
| **Time to First Token** | ~6.28 seconds (6280.34 ms) | ~32.72 seconds (32719.51 ms) |
| **Generation Speed** | ~11.28 tokens/sec | ~9.38 tokens/sec |
| **Thermal Behavior** | Peak 100°C / **Throttled** | Peak 68.0°C / **No Throttling** |

*Note: These are self-reported development benchmarks. Official scores are measured by the ADTC profiler on the standard evaluation machine.*

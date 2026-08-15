# Technical Report — Code Persona: An Offline Socratic Coding Tutor

**Team ID:** code-persona  
**Domain:** coding_assistants  
**Primary Model:** granite-4.0-h-tiny.i1-IQ4_XS.gguf (Single Resident LLM for Socratic Tutor & Ship Fast Modes)  

---

## Problem

For every computer science student, the crowded lecture hall and limited practical equipment always leave the student unfulfilled after every lecture. There is always a need to understand more and practicalize what they have learnt. LLMs are usually the next options in the mind of students, until they visit the LLM site and oops, poor internet connection becomes the next hindrance. Professor Lowacode is here to solve that by bringing the tutoring capabilities of cloud LLMs on device for them serving as home tutors on device for coding tasks and concepts.

Code Persona is an offline system that orchestrates specialized local models for speech transcription, intent routing, document retrieval, code reasoning, and spoken response generation — powered by a single resident **Granite 4.0 H Tiny IQ4_XS** (also known as Professor Lowacode) model running within a strict **6 GB systemd cgroup ceiling**, operating fully offline.

---

## Design Decisions

### Core LLM Selection

Many model architectures were reviewed in choosing the engine of Code Persona. Efficient architectures that do not require high CPU overhead or high RAM usage under long context windows were specifically explored.

We first explored one-bit ternary models, primarily Prism LM Ternary Bonsai models and Microsoft BitNet models. We immediately targeted Q4_K_M quantization as it balances both performance and accuracy. But the ternary Bonsai and BitNet modules were not good enough for our coding needs or needed long thinking sessions to achieve optimal performance.

We also explored the LFM models powered by Liquid AI. These models are purpose-made for edge hardware with blazing fast inference speeds of 20 tokens/sec and above. However, Liquid AI specifically do not recommend LFM modules for code-related tasks due to their architecture. So the LFM models, despite their speed, could not serve as Code Persona's reasoning brain.

Through extensive benchmarking across Granite 4.0 H micro, Granite 4.0 H tiny, Granite 4.1 3B, Granite 3.1 3b A800M, Qwen 2.5 3b Coder, Gemma and Nvidia Nemotron models, we arrived at a **single-model architecture** powered by **Granite 4.0 H Tiny IQ4_XS** (`granite-4.0-h-tiny.i1-IQ4_XS.gguf`). Granite 4.0 H Tiny delivers exceptional code understanding and reasoning as well as tool calling while fitting within memory constraints when configured. It required careful tuning for optimal performance under memory constraints compared to the other Granite and Qwen models. Despite this, Granite 4.0 H Tiny stood out due to its exceptional coding performance and tool calling abilities with better inference speeds due to its MoE architecture. Both Socratic Tutor Mode and Build & Ship Fast Mode are served seamlessly by this single resident model via dynamic system-prompt persona switching, eliminating background model-swapping overhead.

A different setup was actually built in the feature/dual-model-setup branch in this repo which uses a dual model architecture but this setup was not chosen because of better generation speeds and model swapping latency. That setup though is more memory efficient and functions smoothly under a 6 GB RAM systemd cgroups memory limit.

Other architectures explored include Test Time Training (TTT), Google Griffin, subquadratic state spaces, and Liquid Neural Networks — but most were not yet deployable through `llama.cpp` at the time of building.

### Memory Strategy

The setup dynamically uses `--load-mode mmap+mlock` (with fallback to `--load-mode mmap`) for the current architecture:

- **`--load-mode mmap+mlock`**: Memory-maps the GGUF model file into the process address space while using `mlock` to pin the mapped pages in physical RAM. This prevents the OS from evicting model pages under memory pressure, guaranteeing predictable inference latency. The orchestrator auto-detects system memlock limits (`resource.getrlimit(RLIMIT_MEMLOCK)`); when unlimited memlock is configured (via `setup_system_permanently.sh`), `--load-mode mmap+mlock` is enabled. In memlock-restricted environments (e.g. unprivileged containers), it safely falls back to `--load-mode mmap`.
- **`vm.swappiness=5`**: Configured system-wide to strongly prefer reclaiming page cache before touching anonymous pages (KV cache, Python heap). This protects inference latency from swap pressure.

This combination delivers fast warmup and guaranteed model page residence without risking swap-out latency during inference.

### Memory Ceiling: 6 GB Systemd Cgroup Enforcement

The memory ceiling was tightened to **6 GB** via systemd cgroup v2 enforcement to prevent out of memory crashes:

```bash
systemd-run --scope --user -p MemoryMax=6G -p MemoryHigh=5.5G
```


This applies to the entire orchestrator scope, including the spawned `llama-server` subprocess (both processes share the same `cgroup.procs`) meaning the whole model setup runs smoothly within 6 GB. The cgroup `memory.stat` (`anon + file + shmem`) provides the total, and all memory accounting in `/api/metrics` is derived from this source.

### Voice Stack Selection

For speech-to-text, OpenAI Whisper large-v3-turbo was evaluated via `whisper.cpp` but found to be too slow for interactive voice sessions on the target hardware. The reason is architectural: Whisper uses an **autoregressive encoder-decoder** that generates tokens sequentially, which is inherently higher latency than the **Transducer/CTC-based** approach used by NVIDIA's Parakeet and Nemotron models. Parakeet TDT and Nemotron 3.5 ASR achieve RTFx scores exceeding 3,000× on similar hardware — they process a 3-second utterance in well under 1 second — because they predict all output tokens in a single non-autoregressive pass.

Two STT models are used for different interaction modes:
- **Nemotron 3.5 ASR Streaming (0.6B)** for live interactive voice sessions — transcribes word-by-word in real time (The model is not shipped in this setup).
- **Parakeet TDT v2 (0.6B)** for push-to-talk voice typing directly into the chat input box

For text-to-speech, `spd-say` was rejected immediately due to robotic voice quality. The LFM Audio vocoder was considered, but **Kokoro v1.0 (ONNX)** was selected for TTS due to its 82 MB footprint, near-real-time CPU inference, and natural-sounding voice output. Kokoro includes an African-cadence voice variant (`af_heart`) that is particularly well suited to this project's target user base.

### RAG and Intent Routing

A custom ONNX-quantized ColBERT retrieval model (AnswerAI `answerai-colbert-small-v1`) performs late-interaction semantic search over indexed documents — including computer science curricula, code files, and documentation (the preindexed embeddings are not included in this setup but any document can be indexed on the fly or preindexed by the user from their study docs before use) — enabling the tutor to answer questions grounded in materials the student has actually studied, not just generic internet knowledge. Documents under 1,500 words load directly into the context window; larger documents are indexed on-the-fly in approximately 0.25 seconds.

The ColBERT model is also used for intent routing so the setup knows when to retrieve knowledge from the pre-indexed embeddings as well.

---

## Constraints

The target hardware as specified by the competition is 8 GB RAM, integrated GPU, and Ubuntu 22.04. This matches the typical profile of a budget student or developer laptop in an African context. Code Persona works via CPU or Integrated GPU optimized inference through `llama.cpp`.

### Why iGPU

Integrated GPUs are better and faster than CPUs with far better prompt processing speeds compared to CPU. This means that the user's core processing unit is able to focus on handling other user tasks and processing while the iGPU which the target hardware all have focuses on graphics rendering and model inference.

This is a choice though and users who prefer CPU inference can opt for a CPU build instead (building a CPU llama.cpp build manually rather than through our pre-written script).

### Memory Management

The design with a **hard 6 GB systemd cgroup ceiling** (`MemoryMax=6G`) ensures the system operates with significant headroom below the 8 GB physical limit -- leaving the remaining ~2 GB free alongside increased swap memory for the OS, desktop environment, browser, and other student applications running alongside it.

Additional real-world constraints that shaped the design:
- **No stable internet** — all models run fully offline; zero external API calls during inference
- **Battery and power constraints** — the system uses `--load-mode mmap+mlock` (with `--load-mode mmap` fallback) and power-clamping techniques via RyzenAdj (22W limit, 83°C thermal ceiling) to limit CPU thermal output and preserve battery life. Although I must admit that battery drain would still be quite high under sustained inference.
- **Broken or inaccessible keyboards** — voice-first design removes the dependency on physical keyboard quality and helps users voice type long prompts at better speed than keyboard typing.
- **System persistence** — `setup_system_permanently.sh` configures `/dev/shm` (4 GB), swap (12 GB), `swappiness=5`, `vm.dirty_ratio=20`, and unlimited `memlock` limits persistently across reboots

---

## Benchmarks

Benchmarks vary based on the optimization techniques used. The key optimization targets were the `--load-mode mmap+mlock` flag in `llama.cpp` (to use memory-mapped loading while pinning weights into physical RAM), CPU power clamping via RyzenAdj (to prevent thermal throttling on sustained inference loads), increased swap memory, unlimited memlock and swappiness optimizations. Benchmark results also vary based on CPU capacity, whether CPU or iGPU was used, power state of the PC (on battery or plugged in) and most importantly RAM speeds and number of RAM slots in use.

> **NOTE:**
> - Devices with faster RAM speeds and more RAM slots in use would have better and faster token generation speeds. My benchmark hardware contained 1 DDR4 RAM stick rated 3200MHz but with the slots for 2 meaning it could have double token generation speeds if a second stick is inserted.
> - On my device, the iGPU powered by the **AMD Radeon Vega 6 Graphics** delivers over 3x faster processing speeds around `150t/s` compared to my CPU **AMD Ryzen 5 4650U** with about `60t/s`. However fitting the model fully into RAM requires smaller quants or more RAM hence the setup only offloads 25 of 40 layers of the model to iGPU alongside increasing iGPU GTT memory allocation to 5096 MB (done by the setup script) yielding prompt processing speeds of `110t/s`.
> - CPU core temperature can exceed 85C during benchmarking if the setup script is not run before benchmarking as this limits power usage by the CPU and iGPU and lowers throttling temperature to 82C. In other words, before benchmarking ensure to run `setup_system_permanently.sh` to replicate my results.
> - Benchmarking while charging increases temperature spikes but with better inference speeds compared to benchmarking when running on battery.
> - Token generation speeds appear to increase when running while charging compared to running on battery and the iGPU is a lot more sensitive to this with token generation speeds increasing from 9t/s to 14t/s once the device is plugged in compared to CPUs from 12 to 14t/s.

We report two sets of numbers:

### 1. Current Architecture (Host Machine -- `--load-mode mmap+mlock`, Hard 6 GB Cgroup)

Performance metrics obtained from running the whole setup on my personal machine — an **HP EliteBook 845 G7** powered by an **AMD Ryzen 5 PRO 4650U** and **AMD Radeon Vega 6 Graphics** and single channel RAM at 3200MHz speed under the hard 6 GB systemd cgroup ceiling (MemoryMax=6G, MemoryHigh=5.5G) with --load-mode mmap+mlock and 8-bit quantized KV cache. Prompt processing speed not reported here as it varies based on length of prompt. Would be reported in llama-bench report.

| Component | Memory | Token Generation Speeds (CPU/iGPU)(t/s) | Notes |
| :--- | :--- | :--- | :--- |
| **Granite 4.0 H Tiny IQ4_XS** | 3.49 GB | 11 vs 8 | Speed drops majorly due to partial GPU offload to manage memory. Full iGPU speed reaches 14t/s |
| **KV Cache (Granite, 8192 ctx)** | ~280 MB | — | Estimated `q8_0` KV cache memory overhead. Hybrid architecture to thank here. |
| **llama.cpp Engine** | ~20 MB | — | Llama server memory overhead |
| **ColBERT RAG (ONNX)** | ~200 MB | — | In-process via `acolbert.py` needed for intent routing |
| **Orchestrator (FastAPI)** | ~50 MB | — | FastAPI server overhead |
| **OS Baseline** | ~200 MB | — | OS processes needed to manage the systemd cgroups |
| **Vision Model** | ~1.1 GB | — | Not always in RAM, only called via llama-cli for the moment it is needed |
| **Total (cgroup)** | **~4.2--5.3 GB** | — | Under the 6 GB `MemoryMax` ceiling |


### 2. Performance Metrics Comparison: Llama-bench VS the ADTC Profiler
This benchmark was run on my **HP EliteBook 845 G7** with an **AMD Ryzen 5 PRO 4650U** and an **AMD Radeon Vega 6 Graphics** iGPU with 1 RAM slot in use and RAM speeds of 3200MHz. The benchmark was run on **Granite 4.0 H Tiny with IQ4_XS** quantization. The benchmarks were also taken while running on battery not connected to a power source. All CPU runs were done on 6 physical CPU threads.

| Metric | Granite 4.0 H-Tiny via llama-bench CPU build | Granite 4.0 H-Tiny via llama-bench GPU (-ngl 25) build | Granite 4.0 H-Tiny via adtc-profiler llama-cpp-python (on CPU) |
| :--- | :--- | :--- | :--- |
| **Peak RAM** | ~3600 MB | ~3600 MB | ~3616 MB |
| **Time to First Token** | not measured | not measured | ~7.1s |
| **Prompt Processing (pp512)** | 48.94t/s | 107.96t/s | 9.5t/s |
| **Token Generation (tg128)** | 12.05t/s | 7.13t/s | 8.8t/s |
| **Thermal Behavior (with RyzenAdj power and thermal management)** | **Peak 87.0C** | Peak 73C / No Throttling | Peak 82.0C / No Throttling |
| **Accuracy (50 arc-easy benchmark)** | not measured | not measured | **0.86** |

### Limitations in Benchmarking
1. The profiler's own monitoring slows down the speed it measures

While adtc-profiler runs llama-bench, it also runs two background checks at the same time: one that checks memory use every 0.1 seconds, and one that checks CPU temperature every 0.5 seconds. Both of these run as Python threads inside the same process, on the same CPU cores that llama-bench is trying to use.

On a machine with a small number of cores, this is a problem. There's no spare core for the background checks to run on without taking cycles away from llama-bench itself. That competition for CPU time drags down the token generation speed the profiler reports.

We confirmed this by running the exact same model and settings two ways:

- Through the profiler: ~9 tokens/sec
- Running llama-bench on CPU build directly, with nothing else running: ~12 tokens/sec

That's roughly a 35% drop, just from the profiler watching itself work.

The idea behind checking memory and temperature while the model is running is correct. Peak memory use and peak temperature only show up under load, so you can't just measure before and after. The issue is how it's done, not whether it should be done. A leaner way to collect this data, for example reading it from the operating system directly instead of polling from inside Python, would avoid the slowdown. As it stands, this is a limitation of the measurement tool, not a mistake in how we set up or ran our model.

2. **CPU throttling depends highly on power management settings and the system itself and surrounding conditions.** In as much as our benchmarks using the ADTC profiler did not exceed 82C, we are not certain that it would consistently remain below it as factors from other background tasks, environmental temperature and employing thermal management are key factors that affect the measurements.

3. **The target hardware spec is missing two important details.**

The competition's listed target machine is:

- Intel Core i5, 10th to 12th generation
- 8 GB DDR4 RAM
- Intel integrated graphics, no discrete GPU
- Ubuntu 22.04

Two things aren't specified here, and both matter a lot for how fast a model runs on CPU:

- **How many CPU cores.** "10th to 12th gen i5" covers chips with anywhere from 4 to 10 cores, which is a big range for something CPU-bound like this.
- **How the RAM is set up.** 8 GB could be one stick or two. Two sticks (dual-channel) let the CPU read memory roughly twice as fast as one stick (single-channel). Since generating tokens on a CPU is mostly limited by how fast it can read memory rather than how fast it can compute, this difference alone could swing performance more than the core count does.

Since we don't have this information, we tested our model at different thread counts (`-t 2`, `-t 4`, `-t 6`, `-t 8`) to see how performance changes depending on how many cores are actually available.

*Please note that these measurements were taken while charging the device.*
```bash
| model                          |       size |     params | backend    | threads |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | ------: | --------------: | -------------------: |
| granitehybrid 7B.A1B IQ4_XS - 4.25 bpw |   3.49 GiB |     6.94 B | CPU        |       6 |           pp512 |         45.55 ± 9.50 |
| granitehybrid 7B.A1B IQ4_XS - 4.25 bpw |   3.49 GiB |     6.94 B | CPU        |       6 |           tg128 |         13.19 ± 0.49 |
```
```bash
| model                          |       size |     params | backend    | threads |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | ------: | --------------: | -------------------: |
| granitehybrid 7B.A1B IQ4_XS - 4.25 bpw |   3.49 GiB |     6.94 B | CPU        |       4 |           pp512 |         35.79 ± 2.87 |
| granitehybrid 7B.A1B IQ4_XS - 4.25 bpw |   3.49 GiB |     6.94 B | CPU        |       4 |           tg128 |         13.34 ± 0.39 |
```
```bash
| model                          |       size |     params | backend    | threads |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | ------: | --------------: | -------------------: |
| granitehybrid 7B.A1B IQ4_XS - 4.25 bpw |   3.49 GiB |     6.94 B | CPU        |       2 |           pp512 |         21.91 ± 0.36 |
| granitehybrid 7B.A1B IQ4_XS - 4.25 bpw |   3.49 GiB |     6.94 B | CPU        |       2 |           tg128 |         11.85 ± 0.08 |


```


This gives us a realistic range to expect, instead of assuming one specific setup and hoping it matches the real judging machine.

We'd also recommend the organizers publish exact core counts and RAM channel configuration for the audit machine, since it affects every CPU-only submission, not just ours.

---

## Estimated Scores
- S_acc: 86x 0.5 = 43
- S_perf: 100 x (8.8/15) = 58.67 x 0.3 = 17.6
- S_eff: 100 x (7 - 3.53)/7 = 49.57 x 0.2 = 9.91

- Total = 70.51
- Thermal throttling penalty situation uncertain, therefore, we would go with a cautious judgement of a worst case scenario. Estimated total score is 70.51-10 = **60.51**.

*Note: These are self-reported development benchmarks. Official scores are measured by the ADTC profiler on the standard evaluation machine.*
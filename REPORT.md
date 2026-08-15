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

Through extensive benchmarking across Granite 4.0 H micro, Granite 4.0 H tiny, Granite 4.1 3B, Granite 3.1 3b A800M, Qwen 2.5 3b Coder, Gemma and Nvidia Nemotron models. We arrived at a **single-model architecture** powered by **Granite 4.0 H Tiny Q4_K_S** (`granite-4.0-h-tiny.i1-IQ4_XS.gguf`). Granite 4.0 H Tiny delivers exceptional code understanding and reasoning as well as tool calling while fitting within memory constraints when configured. It required careful tuning for optimal performance under memory constraints compared to the other granite and qwen model. Despite this, granite 4.0 h tiny stood out due to its exception coding perfromance and tool calling abilities with better inference speeds due to its MoE architecture. Both Socratic Tutor Mode and Build & Ship Fast Mode are served seamlessly by this single resident model via dynamic system-prompt persona switching, eliminating background model-swapping overhead.

A different setup was actually built in the feature/dual-model-setup branch in this repo which uses a dual model architecture but this setup was not choosen because of better generation speeds and model swapping lateency. That setup though is more memory efficient and functions smoothly under a 6g ram systemd cgroups memory limit.

Other architectures explored include Test Time Training (TTT), Google Griffin, subquadratic state spaces, and Liquid Neural Networks — but most were not yet deployable through `llama.cpp` at the time of building.

### Memory Strategy: 

The setup using to `--mmap` for the current architecture:

- **`--mmap`**: Memory-maps the GGUF model file into the process address space. The file is read directly from disk into RAM as pages are needed, rather than loading the full model upfront. This reduces cold-start time significantly and helps better manage memory footprint at the cost of inference speeds.
- **`vm.swappiness=5`**: Configured system-wide to strongly prefer reclaiming page cache before touching anonymous pages (KV cache, Python heap). This protects inference latency from swap pressure.

This combination delivers faster warmup and better setup stability at the cost of inference speeds

### Memory Ceiling: 6 GB Systemd Cgroup Enforcement

The memory ceiling was tightened **6 GB** via systemd cgroup v2 enforcement to prevent out of memory crashes:

```bash
systemd-run --scope --user -p MemoryMax=6G -p MemoryHigh=5.5G
```

This applies to the entire orchestrator scope, including the spawned `llama-server` subprocess (both processes share the same `cgroup.procs`) meaning the whole model setup run smoothly within 6gb. The cgroup `memory.stat` (`anon + file + shmem`) provides the total, and all memory accounting in `/api/metrics` is derived from this source.

### Voice Stack Selection

For speech-to-text, OpenAI Whisper large-v3-turbo was evaluated via `whisper.cpp` but found to be too slow for interactive voice sessions on the target hardware. The reason is architectural: Whisper uses an **autoregressive encoder-decoder** that generates tokens sequentially, which is inherently higher latency than the **Transducer/CTC-based** approach used by NVIDIA's Parakeet and Nemotron models. Parakeet TDT and Nemotron 3.5 ASR achieve RTFx scores exceeding 3,000× on similar hardware — they process a 3-second utterance in well under 1 second — because they predict all output tokens in a single non-autoregressive pass.

Two STT models are used for different interaction modes:
- **Nemotron 3.5 ASR Streaming (0.6B)** for live interactive voice sessions — transcribes word-by-word in real time (The model is not shipped in this setup).
- **Parakeet TDT v2 (0.6B)** for push-to-talk voice typing directly into the chat input box

For text-to-speech, `spd-say` was rejected immediately due to robotic voice quality. The LFM Audio vocoder was considered, but **Kokoro v1.0 (ONNX)** was selected for TTS due to its 82 MB footprint, near-real-time CPU inference, and natural-sounding voice output. Kokoro includes an African-cadence voice variant (`af_heart`) that is particularly well suited to this project's target user base.

### RAG and Intent Routing

A custom ONNX-quantized ColBERT retrieval model (AnswerAI `answerai-colbert-small-v1`) performs late-interaction semantic search over indexed documents — including computer science curricula, code files, and documentation(the preindexed embeddings is not included in this setup but any document can be indxed on the fly or preindexed by the user from their study docs before use) — enabling the tutor to answer questions grounded in materials the student has actually studied, not just generic internet knowledge. Documents under 1,500 words load directly into the context window; larger documents are indexed on-the-fly in approximately 0.25 seconds. 

The colbert mode is also used for intent routing so the setup knows when to retrieve knowledge from the pre-indexed embedding as well.
---

## Constraints

The target hardware as specified by the competition is 8 GB RAM, integrated GPU, and Ubuntu 22.04. This matches the typical profile of a budget student or developer laptop in an African context. Code Persona works via CPU or Integrated GPU optimized inference through `llama.cpp`.

### Why iGPU:
Integrated GPUs are better and faster than CPUs with far better prompt processing speeds compared to CPU. This means that the users core processing unit is able to focus on handling other user task and processing while the iGPU which the target hardware all have focused on graphics rendering and model inference.
This is a choice though and users who prefer cpu inference can opt for a CPU build instead(building a cpu 
llama.cpp build manually rather than through our pre-written script).

### Memory Management
The design with a **hard 6 GB systemd cgroup ceiling** (`MemoryMax=6G`) ensures the system operates with significant headroom below the 8 GB physical limit — leaving the remaining ~2 GB free aongside side increased swap memory for the OS, desktop environment, browser, and other student applications running alongside it.

Additional real-world constraints that shaped the design:
- **No stable internet** — all models run fully offline; zero external API calls during inference
- **Battery and power constraints** — the system uses `--mmap --mlock` and power-clamping techniques via RyzenAdj (22W limit, 83°C thermal ceiling) to limit CPU thermal output and preserve battery life. Although I must admit that battery drain would still be quite high under sustained inference.
- **Broken or inaccessible keyboards** — voice-first design removes the dependency on physical keyboard quality and help users voice type long prompts at better speed than keyboard typing.
- **System persistence** — `setup_system_permanently.sh` configures `/dev/shm` (4 GB), swap (12 GB), `swappiness=5`, `vm.dirty_ratio=20`, and unlimited `memlock` limits persistently across reboots

---

## Benchmarks

Benchmarks vary based on the optimization techniques used. The key optimization targets were the `--mmap --mlock` flags in `llama.cpp` (to use memory-mapped loading while pinning weights into physical RAM), CPU power clamping via RyzenAdj (to prevent thermal throttling on sustained inference loads), increased swap memory, unlimited memlock and vswapiness optimizations. Benchmark results also vary based on cpu capacity, whether cpu or igpu was used, power state of the pc (on battery or plugged in) and most importantly 'RAM speeds and no of ram slots in use'.
### NOTE:
- Devices with faster ram speeds and more ram slots in use would have better and faster token generation speeds. My benchmarks hardware contained 1 DDR4 ram stick rated 3200Mhz but with the slots for 2 meaning it could have double token generation speeds if a second stick is inserted.
- On my device, the iGPU powered by the **AMD Raedon Vega 6 Graphics** delivers over 3x faster processing speeds around  `150t/s` compared to my cpu **AMD Ryzen 5 4650U** with about `60t/s`. However fitting the model fully into ram requires smaller quants or more ram hence the set up only offloads 25 of 40 layers of the model to iGPU alongside increasing iGPU gtt memory allocation to 5096mb (done by the setup script) yielding prompt processing speeds of `110t/s`.
- CPU core temperature can execeed 85c during benchmarking if the setup script is not ran before benchmarking as this limits power usage by the cpu and iGPU and lowers throttling temperature to 82c. In other words, before benchmarking ensure to run `setup_system_permanently.sh` to replicate my results.
- Benchmarking while charging increases temperature spike buts with better inference speeds compared to enchmarking when running on battery.
- Token generation speeds appear to increase when running while charging compared to running on battery and the iGPU is a lot more sensitive to this with token generation speeds incearing from 9t/s to 14t/s once the device is plugged in compared to CPUs from 12 to 14t/s



We report two sets of numbers:

### 1. Current Architecture (Host Machine — `--mmap`, Hard 6 GB Cgroup)

Performance metrics otained from running the whole setup on my personal machine — an **HP EliteBook 845 G7** powered by an **AMD Ryzen 5 PRO 4650U** and **AMD Raedon Vega 6 Graphics** and single channel use ram at 3200Mhz speed under the hard 6 GB systemd cgroup ceiling (MemoryMax=6G, MemoryHigh=5.7G) with --mmap and 8-bit quantized KV cache. Prompt Processing speed not reported here as it varies based on length of prompt. WOuld be reported in llama-bench report.

| Component | Memory | Token Generation Speeds (CPU/iGPU)(t/s)| Notes |
| :--- | :--- | :--- |
| **Granite 4.0 h tiny IQ4_XS**  | 3.49GB |  11 vs 8 |  |Speed drops majorly due to partial gpu offload to manage memory. Full iGPU speed reaches 14t/s |
| **KV Cache (Granite, 128k ctx)** | ~280 MB | "estimated" `q8_0` kv cache memory overhead. Hybird architecture to thank here. |
| **llama.cpp Engine** | ~20 MB | Llama server memory overhead |
| **ColBERT RAG (ONNX)** | ~200 MB | In-process via `acolbert.py` needed for intent routing|
| **Orchestrator (FastAPI)** | ~50 MB | Fast API server overhead |
| **OS Baseline** | ~200 MB | OS processes needed to manage the systemd croups |
| **Vision Model**| ~1.1GB | Not always in RAM, only called via llama-cli for the moment it is needed|
| **Total (cgroup)** | **~4.2–5.3 GB** | Under the 6 GB `MemoryMax` ceiling |



### Performance Metrics Comparison on Llama-bench VS the adtc profiler
This benchmark was ran on my **HP ELitebook 845 G7** with an **AMD Ryzen 5 PRO 4650U** and a **AMD Raedon Vega 6 Graphics** iGPU with 1 ram slot in use and ram seeds of 3200Mhz. The benchmark was ran on **Granite 4.0 h tiny with iQ4_XS** quantization. The benhcmarks were also taken while running on battery not connected to a power source. All CPU runs were done on 6 physical CPU threads.
| Metric | Granite 4.0 H-Tiny via llama-bench CPU build | Granite 4.0 H-Tiny via llama-bench GPU(-ngl 25) build| Granite 4.0 H-Tiny via adtc-profiler llama-cpp-python(on CPU)|
| :--- | :--- | :--- |
| **Peak RAM** | ~3600 MB  | ~3600 MB |  ~3616 MB |
| **Time to First Token** | not measured | not measured | ~7.1s |
| **Prompt Processing(pp512)** |  48.94t/s | 107.96t/s | 9.5t/s|
| **Token Generation (tg128)** | 12.05t/s | 7.13t/s | 8.8t/s|
| **Thermal Behavior-with ryzenadj power usage and thermal management** | **Peak 87.0°C** | Peak 73°C / No Throttling | Peak 82.0°C / No Throttling|
| **accuracy (50 arc-easy benchmark)** | not measured | not measured | **0.86** |

### Limitations in Benchmarking
1. The profiler's own monitoring slows down the speed it measures

While adtc-profiler runs llama-bench, it also runs two background checks at the same time: one that checks memory use every 0.1 seconds, and one that checks CPU temperature every 0.5 seconds. Both of these run as Python threads inside the same process, on the same CPU cores that llama-bench is trying to use.

On a machine with a small number of cores, this is a problem. There's no spare core for the background checks to run on without taking cycles away from llama-bench itself. That competition for CPU time drags down the token generation speed the profiler reports.

We confirmed this by running the exact same model and settings two ways:

Through the profiler: ~9 tokens/sec
Running llama-bench on cpu build directly, with nothing else running: ~12 tokens/sec

That's roughly a 35% drop, just from the profiler watching itself work.

The idea behind checking memory and temperature while the model is running is correct. Peak memory use and peak temperature only show up under load, so you can't just measure before and after. The issue is how it's done, not whether it should be done. A leaner way to collect this data, for example reading it from the operating system directly instead of polling from inside Python, would avoid the slowdown. As it stands, this is a limitation of the measurement tool, not a mistake in how we set up or ran our model.

2. CPU throttling dependds highly on power management settings and the system itself and surrounding conditions. In as much as our benchmarks using the adtc profiler did not exceed 82c, we are not certain that it would consistent main below it as factors from other background tasks, environmental temperature and employing thermal management are key factors that affect the measurements.

## Estimated Scores
S_acc: 86x 0.5 = 43
S_perf: 100 x (8.5/15) = 56.67 x 0.3 = 17
S_eff: 100 x (7 - 3.53)/7 = 49.57 x 0.2 = 9.91

Total = 69.91
Thermal throttling penalty situation uncertain, therefore, we would go with a cautios judgement of a worse case scenerio. Estimated total score is 69.91-10 = **59.91**.

*Note: These are self-reported development benchmarks. Official scores are measured by the ADTC profiler on the standard evaluation machine.*
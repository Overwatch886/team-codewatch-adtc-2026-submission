import os
import sys
import time
import json
import logging
import subprocess
import io
import queue
import threading
import re
import soundfile as sf
import psutil
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Ensure workspace is in python path for any workspace-relative imports
WORKSPACE_DIR = "/home/overwatch886/local_ai_workspace"
if WORKSPACE_DIR not in sys.path:
    sys.path.append(WORKSPACE_DIR)

LAST_VISION_ACTIVE_TIME = 0.0

# Import the sibling orchestrator module directly rather than via the `scripts.`
# package namespace. nemo_toolkit installs a top-level `scripts` package into
# site-packages that shadows this workspace's scripts/ folder, so `import
# scripts.orchestrator` resolves into NeMo's package and fails. Putting this
# file's own directory at the front of sys.path makes the sibling win.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import base64
import tempfile
import orchestrator

# Global TTS Settings & Lock
TTS_SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "scratch", "tts_settings.json")
tts_enabled = False
kokoro_instance = None
kokoro_lock = threading.Lock()

def load_tts_settings():
    global tts_enabled
    try:
        if os.path.exists(TTS_SETTINGS_FILE):
            with open(TTS_SETTINGS_FILE, "r") as f:
                data = json.load(f)
                tts_enabled = data.get("tts_enabled", False)
                print(f"[ServerSettings] Loaded TTS Enabled: {tts_enabled}")
    except Exception as e:
        print(f"[ServerSettings] Failed to load TTS settings: {e}")

def save_tts_settings():
    try:
        os.makedirs(os.path.dirname(TTS_SETTINGS_FILE), exist_ok=True)
        with open(TTS_SETTINGS_FILE, "w") as f:
            json.dump({"tts_enabled": tts_enabled}, f)
            print(f"[ServerSettings] Saved TTS Enabled: {tts_enabled}")
    except Exception as e:
        print(f"[ServerSettings] Failed to save TTS settings: {e}")

def get_kokoro():
    global kokoro_instance
    if kokoro_instance is None:
        with kokoro_lock:
            if kokoro_instance is None:
                import onnxruntime as rt
                from kokoro_onnx import Kokoro
                model_path = os.path.join(WORKSPACE_DIR, "models/audio/kokoro/kokoro-v1.0.onnx")
                if not os.path.exists(model_path):
                    model_path = os.path.join(WORKSPACE_DIR, "models/audio/kokoro/kokoro-v1.0.int8.onnx")
                voices_path = os.path.join(WORKSPACE_DIR, "models/audio/kokoro/voices-v1.0.bin")
                if not os.path.exists(model_path) or not os.path.exists(voices_path):
                    print(f"[ServerTTS Error] Kokoro model or voices missing. Path: {model_path}", file=sys.stderr)
                    return None
                opts = rt.SessionOptions()
                opts.intra_op_num_threads = 6
                opts.inter_op_num_threads = 1
                session = rt.InferenceSession(model_path, sess_options=opts, providers=['CPUExecutionProvider'])
                kokoro_instance = Kokoro.from_session(session, voices_path)
                print("[ServerTTS] Kokoro model initialized successfully.")
    return kokoro_instance

# ---- Code-aware TTS helpers ----
# Ordered so multi-character operators are matched before their single-char parts.
_CODE_SYMBOL_SPEECH = [
    ("==", " is equal to "),
    ("!=", " is not equal to "),
    (">=", " greater than or equal to "),
    ("<=", " less than or equal to "),
    ("->", " arrow "),
    ("=>", " arrow "),
    ("&&", " and "),
    ("||", " or "),
    ("**", " to the power of "),
    ("//", " double slash "),
    ("(", " open paren "),
    (")", " close paren "),
    ("{", " open brace "),
    ("}", " close brace "),
    ("[", " open bracket "),
    ("]", " close bracket "),
    ("=", " equals "),
    ("+", " plus "),
    ("-", " minus "),
    ("*", " times "),
    ("/", " slash "),
    ("%", " percent "),
    ("<", " less than "),
    (">", " greater than "),
    (":", " colon "),
    (";", " semicolon "),
    (",", " comma "),
    (".", " dot "),
    ("_", " "),
    ("#", " hash "),
    ("@", " at "),
    ("&", " ampersand "),
    ("|", " pipe "),
    ("\\", " backslash "),
    ('"', " "),
    ("'", " "),
    ("`", " "),
]


def verbalize_code_for_speech(code: str) -> str:
    """Turn a code block into something a TTS voice can read aloud sensibly,
    e.g. 'def add(a, b):' -> 'def add open paren a comma b close paren colon'."""
    lines = code.split("\n")
    # Drop a leading language identifier line (e.g. the "python" after ```).
    if lines and lines[0].strip() and len(lines[0].strip()) <= 12 \
            and re.match(r'^[A-Za-z0-9+#]+$', lines[0].strip()) and len(lines) > 1:
        lines = lines[1:]

    spoken_lines = []
    for line in lines:
        s = line
        for sym, word in _CODE_SYMBOL_SPEECH:
            s = s.replace(sym, word)
        s = re.sub(r'\s+', ' ', s).strip()
        if s:
            spoken_lines.append(s)

    if not spoken_lines:
        return ""
    # Join lines with a pause so each statement is spoken distinctly.
    body = ". ".join(spoken_lines)
    return "Code block. " + body


def split_prose_sentences(buf: str):
    """Split completed sentences out of a prose buffer, keeping any trailing
    incomplete fragment. Returns (list_of_sentences, remainder)."""
    sentences = []
    last = 0
    for m in re.finditer(r'[.!?\n]', buf):
        end = m.end()
        chunk = buf[last:end].strip()
        if chunk:
            sentences.append(chunk)
        last = end
    return sentences, buf[last:]


def segment_for_tts(text: str):
    """Split a full response into ordered spoken chunks, verbalizing fenced
    code blocks and sentence-splitting the surrounding prose."""
    chunks = []
    idx = 0
    for m in re.finditer(r'```([^\n`]*)\n?([\s\S]*?)```', text):
        prose = text[idx:m.start()]
        sents, tail = split_prose_sentences(prose)
        chunks.extend(sents)
        if tail.strip():
            chunks.append(tail.strip())
        spoken_code = verbalize_code_for_speech(m.group(2))
        if spoken_code:
            chunks.append(spoken_code)
        idx = m.end()
    trailing = text[idx:]
    sents, tail = split_prose_sentences(trailing)
    chunks.extend(sents)
    if tail.strip():
        chunks.append(tail.strip())
    return [c for c in chunks if c.strip()]


class ServerTTSPlayer:
    def __init__(self):
        self.sentence_queue = queue.Queue()
        self.playback_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.tts_thread = None
        self.playback_thread = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.tts_thread is None:
                self.stop_event.clear()
                # Drain any leftover items
                while not self.sentence_queue.empty():
                    try:
                        self.sentence_queue.get_nowait()
                    except queue.Empty:
                        break
                while not self.playback_queue.empty():
                    try:
                        self.playback_queue.get_nowait()
                    except queue.Empty:
                        break
                self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
                self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
                self.tts_thread.start()
                self.playback_thread.start()
                print("[ServerTTS] Background threads started.")

    def stop(self):
        with self.lock:
            if self.tts_thread is not None:
                self.stop_event.set()
                self.sentence_queue.put("[DONE]")
                self.playback_queue.put("[DONE]")
                self.tts_thread.join(timeout=1)
                self.playback_thread.join(timeout=1)
                self.tts_thread = None
                self.playback_thread = None
                print("[ServerTTS] Background threads stopped.")

    def play_sentence(self, sentence: str):
        if not tts_enabled:
            return
        self.start()
        self.sentence_queue.put(sentence)

    def interrupt(self):
        # Stop any active playback immediately
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        # Drain queues
        while not self.sentence_queue.empty():
            try:
                self.sentence_queue.get_nowait()
            except queue.Empty:
                break
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break
        print("[ServerTTS] Interrupted playback and cleared queues.")

    def _tts_worker(self):
        while not self.stop_event.is_set():
            try:
                sentence = self.sentence_queue.get(timeout=1)
            except queue.Empty:
                continue
            if sentence == "[DONE]":
                break
            clean_sentence = re.sub(r'[*_`#\-]', ' ', sentence).strip()
            if not clean_sentence:
                continue
            try:
                kokoro = get_kokoro()
                if kokoro:
                    samples, sample_rate = kokoro.create(
                        clean_sentence,
                        voice="af_heart",
                        speed=1.0,
                        lang="en-us"
                    )
                    self.playback_queue.put((samples, sample_rate))
            except Exception as e:
                print(f"[ServerTTS Error] Generation failed: {e}", file=sys.stderr)

    def _playback_worker(self):
        try:
            import sounddevice as sd
        except Exception as e:
            print(f"[ServerTTS Error] sounddevice import failed: {e}", file=sys.stderr)
            return
        while not self.stop_event.is_set():
            try:
                audio_item = self.playback_queue.get(timeout=1)
            except queue.Empty:
                continue
            if audio_item == "[DONE]":
                break
            samples, sample_rate = audio_item
            try:
                sd.play(samples, samplerate=sample_rate, blocking=True)
            except Exception as e:
                print(f"[ServerTTS Error] Playback failed: {e}", file=sys.stderr)

# Instantiate global TTS player and load settings
tts_player = ServerTTSPlayer()
load_tts_settings()

def save_base64_image(base64_str: str) -> str:
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]
    img_data = base64.b64decode(base64_str)
    temp_dir = os.path.join(WORKSPACE_DIR, "scratch")
    os.makedirs(temp_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".jpg", dir=temp_dir, delete=False) as f:
        f.write(img_data)
        return f.name

def save_base64_doc(base64_str: str, filename: str) -> str:
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]
    doc_data = base64.b64decode(base64_str)
    temp_dir = os.path.join(WORKSPACE_DIR, "scratch")
    os.makedirs(temp_dir, exist_ok=True)
    suffix = os.path.splitext(filename)[1] if filename else ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, dir=temp_dir, delete=False) as f:
        f.write(doc_data)
        return f.name
    def sanitize_schema(schema: dict):
        if not isinstance(schema, dict):
            return
        
        # 1. Delete pattern, minLength, maxLength to avoid GBNF compiler recursion limits
        if "pattern" in schema:
            del schema["pattern"]
        if "minLength" in schema:
            del schema["minLength"]
        if "maxLength" in schema:
            del schema["maxLength"]

        # 2. Handle anyOf / oneOf / allOf
        for key in ["anyOf", "oneOf", "allOf"]:
            if key in schema and isinstance(schema[key], list):
                sub_schemas = schema[key]
                chosen_schema = None
                for sub in sub_schemas:
                    if isinstance(sub, dict):
                        # Find the first schema in the list that is not a null type
                        if sub.get("type") != "null" and sub.get("type") is not None:
                            chosen_schema = sub
                            break
                if chosen_schema:
                    del schema[key]
                    schema.update(chosen_schema)
                else:
                    del schema[key]
                    schema["type"] = "null"

        # 3. Handle const (convert to enum)
        if "const" in schema:
            schema["enum"] = [schema["const"]]
            del schema["const"]

        # Recurse
        for k, v in list(schema.items()):
            if isinstance(v, dict):
                sanitize_schema(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        sanitize_schema(item)
                        
    for tool in tools:
        if isinstance(tool, dict) and "function" in tool:
            func = tool["function"]
            if isinstance(func, dict) and "parameters" in func:
                sanitize_schema(func["parameters"])

app = FastAPI(title="Local AI Orchestrator Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = os.path.join(WORKSPACE_DIR, "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Web Interface not found. Please create static/index.html</h1>")

def read_gpu_resident_mb(pid):
    """Sum a process's physically-resident GPU memory (VRAM + GTT) from amdgpu fdinfo.

    On an APU (e.g. Renoir iGPU) the model weights offloaded via Vulkan live in the
    GTT domain — system DRAM mapped for the GPU — which never shows up in the
    process's VmRSS. This is the honest "real allocation" number for the Vulkan path.

    fdinfo repeats the same drm-resident-* keys once per open fd with identical
    values, so we take the MAX per key across fds rather than summing (summing would
    multiply the footprint by the fd count). Returns 0.0 on CPU-only builds or when
    the driver doesn't expose these keys.
    """
    if not pid:
        return 0.0
    max_vram_kib = 0.0
    max_gtt_kib = 0.0
    fdinfo_dir = f"/proc/{pid}/fdinfo"
    try:
        for fd in os.listdir(fdinfo_dir):
            try:
                with open(os.path.join(fdinfo_dir, fd), "r") as f:
                    for line in f:
                        if line.startswith("drm-resident-vram:"):
                            max_vram_kib = max(max_vram_kib, float(line.split()[1]))
                        elif line.startswith("drm-resident-gtt:"):
                            max_gtt_kib = max(max_gtt_kib, float(line.split()[1]))
            except Exception:
                continue
    except Exception:
        return 0.0
    return (max_vram_kib + max_gtt_kib) / 1024.0  # KiB -> MiB

@app.get("/api/metrics")
def get_metrics():
    try:
        import requests

        my_uid = os.getuid()
        my_pid = os.getpid()
        granite_pid = 0
        
        # Scan /proc to find pids and memory usage for our stack components and other processes
        os_baseline_mb = 0.0
        other_user_programs_mb = 0.0
        
        granite_rss_mb = 0.0
        kokoro_rss_mb = 0.0
        colbert_rss_mb = 0.0
        orchestrator_rss_mb = 0.0
        vision_rss_mb = 0.0
        
        for pid_dir in os.listdir("/proc"):
            if pid_dir.isdigit():
                pid = int(pid_dir)
                try:
                    cmdline = ""
                    if os.path.exists(f"/proc/{pid}/cmdline"):
                        with open(f"/proc/{pid}/cmdline", "rb") as f:
                            cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')
                            
                    rss = 0.0
                    uid = -1
                    if os.path.exists(f"/proc/{pid}/status"):
                        with open(f"/proc/{pid}/status", "r") as f:
                            for line in f:
                                if line.startswith("VmRSS:"):
                                    rss = int(line.split()[1]) / 1024.0  # KB to MB
                                elif line.startswith("Uid:"):
                                    uid = int(line.split()[1])
                                    
                    if rss == 0.0:
                        continue
                        
                    # Classify process
                    if pid == my_pid:
                        orchestrator_rss_mb += rss
                    elif "llama-server" in cmdline and ("8081" in cmdline or "port 8081" in cmdline):
                        granite_rss_mb += rss
                        granite_pid = pid
                    elif "acolbert.py" in cmdline or ("python" in cmdline and "8000" in cmdline):
                        colbert_rss_mb += rss
                    elif "LFM2.5-VL" in cmdline or "vision" in cmdline:
                        vision_rss_mb += rss
                    elif uid == my_uid:
                        other_user_programs_mb += rss
                    else:
                        os_baseline_mb += rss
                except Exception:
                    pass
                    
        # Add kernel memory allocations to OS Baseline
        kernel_mem_mb = 0.0
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("Slab:") or line.startswith("PageTables:") or line.startswith("KernelStack:"):
                        kernel_mem_mb += int(line.split()[1]) / 1024.0  # KB to MB
        except Exception:
            pass
        os_baseline_mb += kernel_mem_mb
        
        # Estimate in-process ColBERT memory if not running as separate server
        is_colbert_loaded = False
        try:
            import acolbert
            if acolbert.session is not None:
                is_colbert_loaded = True
        except Exception:
            pass

        if colbert_rss_mb == 0.0 and is_colbert_loaded:
            colbert_in_process_mb = 200.0  # Approximate ONNX model memory size
            orchestrator_rss_mb = max(40.0, orchestrator_rss_mb - colbert_in_process_mb)
            colbert_rss_mb = colbert_in_process_mb

        # Estimate in-process Kokoro TTS memory (lazy-loaded inside the orchestrator).
        # Stays 0 until the first TTS call loads the model. Sized from the actual
        # ONNX weights + voices pack on disk so fp32 vs int8 is reflected accurately.
        if kokoro_instance is not None:
            kokoro_in_process_mb = 0.0
            try:
                kokoro_dir = os.path.join(WORKSPACE_DIR, "models/audio/kokoro")
                fp32_path = os.path.join(kokoro_dir, "kokoro-v1.0.onnx")
                int8_path = os.path.join(kokoro_dir, "kokoro-v1.0.int8.onnx")
                model_file = fp32_path if os.path.exists(fp32_path) else int8_path
                if os.path.exists(model_file):
                    kokoro_in_process_mb += os.path.getsize(model_file) / 1024.0 / 1024.0
                voices_file = os.path.join(kokoro_dir, "voices-v1.0.bin")
                if os.path.exists(voices_file):
                    kokoro_in_process_mb += os.path.getsize(voices_file) / 1024.0 / 1024.0
            except Exception:
                pass
            if kokoro_in_process_mb == 0.0:
                kokoro_in_process_mb = 340.0  # Fallback: fp32 weights + voices
            orchestrator_rss_mb = max(40.0, orchestrator_rss_mb - kokoro_in_process_mb)
            kokoro_rss_mb = kokoro_in_process_mb
            
        # Get Granite prompt cache tokens
        n_prompt_tokens_cache = 0
        try:
            slots_res = requests.get("http://127.0.0.1:8081/slots", timeout=0.3)
            if slots_res.status_code == 200:
                slots_data = slots_res.json()
                for slot in slots_data:
                    n_prompt_tokens_cache += slot.get("n_prompt_tokens_cache", 0)
        except Exception:
            pass
            
        prompt_cache_mb = n_prompt_tokens_cache * 0.03125
        
        # Get actual model path from /props to determine exact weight size on disk
        model_path = ""
        model_name = "Granite"
        disk_size_gb = 4.1
        try:
            props_res = requests.get("http://127.0.0.1:8081/props", timeout=0.3)
            if props_res.status_code == 200:
                props_data = props_res.json()
                model_path = props_data.get("model_path", "")
                if model_path:
                    base_name = os.path.basename(model_path)
                    clean_name = base_name.replace(".gguf", "")
                    clean_name = re.sub(r'[-_]Q[0-9]_[A-Za-z0-9_]+', '', clean_name)
                    clean_name = clean_name.replace("-", " ").replace("_", " ").title()
                    model_name = clean_name
                    if os.path.exists(model_path):
                        disk_size_gb = round(os.path.getsize(model_path) / 1024 / 1024 / 1024, 1)
        except Exception:
            pass
            
        # Real GPU-resident weight memory (Vulkan/iGPU path). On an APU this is GTT —
        # system DRAM the process's VmRSS can't see — so it's the honest "where did the
        # weights actually go" number. ~0 on a CPU-only build (weights sit in VmRSS instead).
        granite_gpu_mb = read_gpu_resident_mb(granite_pid)

        # Distribute Granite server memory between weights, cache, and engine overhead
        granite_weights_mb = 0.0
        llama_cpp_overhead_mb = 0.0
        if granite_rss_mb > 0.0 or granite_gpu_mb > 0.0:
            llama_cpp_overhead_mb = min(120.0, granite_rss_mb) if granite_rss_mb > 0 else 30.0
            granite_weights_mb = max(0.0, granite_rss_mb - prompt_cache_mb - llama_cpp_overhead_mb)
        else:
            model_name = "None"
            disk_size_gb = 0.0

        # Total simulated used memory (sum of all parsed processes + kernel baseline).
        # granite_gpu_mb is added because on the Vulkan/iGPU path the offloaded weights
        # live in GTT (real DRAM) that VmRSS omits; on CPU it's ~0 so nothing is double-counted.
        total_used_mb = (os_baseline_mb + granite_rss_mb + granite_gpu_mb +
                         kokoro_rss_mb + colbert_rss_mb + orchestrator_rss_mb +
                         vision_rss_mb + other_user_programs_mb)
        used_gb = total_used_mb / 1024.0
        total_gb = round(psutil.virtual_memory().total / 1024.0 / 1024.0 / 1024.0, 2)
        available_gb = max(0.0, total_gb - used_gb)

        vision_status_str = "Active (CPU - 0 VRAM)" if (time.time() - LAST_VISION_ACTIVE_TIME < 60) else "Idle (CPU - 0 VRAM)"

        return {
            "total_gb": total_gb,
            "used_gb": round(used_gb, 2),
            "available_gb": round(available_gb, 2),
            "granite_rss_mb": round(granite_rss_mb, 2),
            "breakdown": {
                "os_baseline_mb": round(os_baseline_mb, 1),
                "model_name": model_name,
                "model_disk_gb": disk_size_gb,
                "model_weights_mb": round(granite_weights_mb, 1),
                "granite_gpu_mb": round(granite_gpu_mb, 1),
                "llama_cpp_overhead_mb": round(llama_cpp_overhead_mb, 1),
                "prompt_cache_mb": round(prompt_cache_mb, 1),
                "colbert_rss_mb": round(colbert_rss_mb, 1),
                "kokoro_rss_mb": round(kokoro_rss_mb, 1),
                "orchestrator_rss_mb": round(orchestrator_rss_mb, 1),
                "vision_rss_mb": round(vision_rss_mb, 1),
                "vision_status": vision_status_str,
                "other_user_programs_mb": round(other_user_programs_mb, 1),
                "total_used_mb": round(total_used_mb, 1)
            },
            "status": "Healthy"
        }
    except Exception as e:
        return {"error": str(e), "status": "Error"}

@app.get("/v1/models")
@app.get("/models")
def get_models():
    try:
        import requests
        response = requests.get("http://localhost:8081/v1/models", timeout=2)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
CURRENT_LOADED_MODEL_KEY = "granite"
FORCED_MODEL_OVERRIDE = None  # None (Auto), "granite", or "qwen"

@app.post("/api/switch-model")
async def switch_model_endpoint(request: Request):
    global FORCED_MODEL_OVERRIDE
    try:
        body = await request.json()
        target = body.get("model", "auto").lower()

        if target in ("granite", "granite-3.1-3b-a800m-instruct"):
            FORCED_MODEL_OVERRIDE = "granite"
            ensure_model_loaded("granite")
            return {"status": "ok", "active_model": "Granite 3.1 3B A800M Instruct", "override": "granite"}
        elif target in ("qwen", "qwen2.5-coder-3b-instruct"):
            FORCED_MODEL_OVERRIDE = "qwen"
            ensure_model_loaded("qwen")
            return {"status": "ok", "active_model": "Qwen 2.5 Coder 3B Instruct", "override": "qwen"}
        else:
            FORCED_MODEL_OVERRIDE = None
            return {"status": "ok", "active_model": "Auto (Smart Intent Routing)", "override": "auto"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def ensure_model_loaded(target_key: str):
    global CURRENT_LOADED_MODEL_KEY
    if CURRENT_LOADED_MODEL_KEY == target_key:
        return

    import requests
    print(f"[Server] 🔄 Swapping resident model to: {target_key}...")
    subprocess.run(["fuser", "-k", "8081/tcp"], capture_output=True)
    time.sleep(1)

    LLAMA_SERVER_BIN = "/home/overwatch886/local_ai_workspace/software/llama.cpp/build/bin/llama-server"

    if target_key == "qwen":
        model_path = "/home/overwatch886/local_ai_workspace/models/qwen/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
        alias_name = "qwen2.5-coder-3b-instruct"
        ngl_flag = "99"
    else:
        model_path = "/home/overwatch886/local_ai_workspace/models/granite-3.1-3b-a800m-instruct-IQ4_XS.gguf"
        alias_name = "granite-3.1-3b-a800m-instruct"
        ngl_flag = "99"

    cmd = [
        LLAMA_SERVER_BIN,
        "-m", model_path,
        "-c", "4096", "-b", "2048", "-ub", "512", "-t", "4",
        "--port", "8081", "--threads-http", "2", "--parallel", "1", "--cache-ram", "128",
        "-ctk", "q8_0", "-ctv", "q8_0",
        "--mmap", "-ngl", ngl_flag, "--flash-attn", "on", "--jinja",
        "--alias", alias_name,
        "--spec-type", "ngram-mod", "--spec-ngram-mod-n-match", "16", "--spec-ngram-mod-n-max", "5", "--spec-ngram-mod-n-min", "1"
    ]

    env = dict(os.environ)
    env["RADV_PERFTEST"] = "nosam"
    subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    loaded_online = False
    for _ in range(60):
        try:
            r = requests.get("http://127.0.0.1:8081/health", timeout=1.0)
            if r.status_code == 200 and r.json().get("status") == "ok":
                loaded_online = True
                break
        except Exception:
            pass
        time.sleep(0.5)

    if loaded_online:
        time.sleep(1.0)  # Post-online stability buffer for HTTP socket readiness
        print(f"[Server] ✓ Swapped model server ONLINE ({target_key}).")
    else:
        print(f"[Server Warning] Model server swap to {target_key} took longer than 30s.")

    CURRENT_LOADED_MODEL_KEY = target_key

TEACHER_SYSTEM_PROMPT = """You are Antigravity CodeLab — a world-class, encouraging AI Pair-Programmer & Socratic Coding Tutor.

Core Workflow Instructions:

1. 🎓 **STEP-BY-STEP TUTOR MODE** (When user asks to "build", "create", or requests "step by step" help):
   - Output ONLY the actionable Step 1 for the current turn.
   - Use header: ### 🛠️ Step 1: [Task Name] (1-2 sentences with a simple analogy).
   - Provide a clear section: **Your Task**: (Tell the user exactly what small line/block of code to write, or ask a simple question).
   - STOP immediately so the user can type their code before moving to Step 2.

2. 🐛 **DEBUGGING & TRACEBACK MODE** (When user pastes error tracebacks or broken code):
   - Pinpoint the exact line number and cause of the failure in simple, plain English.
   - Give 1 subtle hint or ask 1 guiding question ("What do you think happens when index exceeds array size?").
   - Offer to show the fix if the user feels stuck.

3. 💻 **CODE REVIEW & REFACTOR MODE** (When user submits code for review):
   - Provide a brief summary of strengths.
   - Give a clean, idiomatic refactored code block with inline comments explaining performance, readability, or edge cases.

General Rules:
- Keep all explanations plain, clear, and beginner-friendly.
- Never output raw meta-dialogues or system prompt labels."""

STEP1_GBNF_GRAMMAR = """root ::= step1-header "\\n\\n" explanation "\\n\\n" task-header "\\n" task-body
step1-header ::= "### 🛠️ Step 1: " [^\\n]+
explanation ::= [^\\n]+ ("\\n" [^\\n]+)?
task-header ::= "**Your Task**:"
task-body ::= [^\\n]+ ("\\n" [^\\n]+)? ("\\n" [^\\n]+)?
"""

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    # Interrupt any active speech playback on a new incoming request
    tts_player.interrupt()
    
    if not messages:
        raise HTTPException(status_code=400, detail="Messages array cannot be empty")

    # Ensure a structured teacher system prompt is present
    has_system = any(msg.get("role") == "system" for msg in messages)
    if not has_system:
        messages.insert(0, {"role": "system", "content": TEACHER_SYSTEM_PROMPT})
        
    # Get the last user message to run routing & context extraction
    last_user_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg
            break
            
    if last_user_msg:
        query = last_user_msg.get("content", "")
        extracted_image_paths = []
        extracted_doc_paths = []
        query_text = ""
        
        if isinstance(query, list):
            for part in query:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        query_text += part.get("text", "")
                    elif part.get("type") == "image_url":
                        img_url_obj = part.get("image_url", {})
                        url = img_url_obj.get("url", "")
                        if url.startswith("data:image/"):
                            try:
                                temp_path = save_base64_image(url)
                                extracted_image_paths.append(temp_path)
                                print(f"[Server] Decoded base64 image and saved to {temp_path}")
                            except Exception as e:
                                print(f"⚠️ Failed to parse uploaded base64 image: {e}")
                        elif url.startswith("file://"):
                            extracted_image_paths.append(url.replace("file://", ""))
                        elif os.path.exists(url):
                            extracted_image_paths.append(url)
                    elif part.get("type") == "doc_url":
                        doc_url_obj = part.get("doc_url", {})
                        url = doc_url_obj.get("url", "")
                        name = doc_url_obj.get("name", "doc.bin")
                        if url.startswith("data:"):
                            try:
                                temp_path = save_base64_doc(url, name)
                                extracted_doc_paths.append(temp_path)
                                print(f"[Server] Decoded base64 doc '{name}' and saved to {temp_path}")
                            except Exception as e:
                                print(f"⚠️ Failed to parse uploaded base64 doc: {e}")
        else:
            query_text = str(query)

        # Run routing
        print(f"[Server] Analyzing query: {query_text!r}")
        intent, entities, scores = orchestrator.analyze_query(query_text)
        image_paths = orchestrator.extract_image_paths(query_text, entities)
        # Merge both sources of image paths (regex mentions + direct uploads)
        image_paths = list(set(image_paths + extracted_image_paths))
        text_entities = orchestrator.extract_text_file_entities(entities)
        if extracted_doc_paths:
            text_entities.extend([{"label": "FILE_PATH", "text": p} for p in extracted_doc_paths])
        
        prompt_context = ""
        vision_context = ""
        
        if intent == "RAG":
            print("[Server] Intent is RAG. Performing local ColBERT retrieval...")
            prompt_context = orchestrator.build_rag_context(query_text, entities)
        elif text_entities:
            print("[Server] Loading local file context...")
            prompt_context = orchestrator.build_file_context(text_entities, query_text)
            
        if (intent == "VISION" or image_paths) and image_paths:
            print("[Server] Vision active. Describing image...")
            try:
                global LAST_VISION_ACTIVE_TIME
                LAST_VISION_ACTIVE_TIME = time.time()
                vision_context = orchestrator.build_vision_context(query_text, image_paths)
            except Exception as e:
                print(f"[Server] Vision failed: {e}")
                
        # Construct the context injections
        injected_text = ""
        if prompt_context:
            injected_text += f"\nRelevant Context:\n{prompt_context}\n"
        if vision_context:
            injected_text += f"\nVision Context:\n{vision_context}\n"
            
        if injected_text:
            if isinstance(query, list):
                query.insert(0, {"type": "text", "text": injected_text})
            else:
                last_user_msg["content"] = f"{injected_text}\nUser Question: {query}"
            print("[Server] Context successfully injected into user message.")

        # --- CONTEXT PRUNING MIDDLEWARE ---
        # 1. Prune the system prompt
        for msg in messages:
            if msg.get("role") == "system":
                original_sys = msg.get("content", "")
                if original_sys:
                    msg["content"] = orchestrator.prune_system_prompt_with_colbert(query_text, original_sys, max_additional_blocks=3)
                    print(f"[DEBUG] Pruned System Prompt:\n{msg['content']}\n[DEBUG] End of System Prompt")

        # 2. Prune the tools list in the request body
        if "tools" in body:
            tool_names = [t.get("function", {}).get("name", "") for t in body["tools"]]
            print(f"[Server] Incoming tools: {tool_names}")
            body["tools"] = orchestrator.prune_tools_with_colbert(query_text, body["tools"])
            sanitize_tool_patterns(body["tools"])
        else:
            print("[Server] No tools parameter found in the request body.")

    # Call llama.cpp directly on port 8081 with intent & difficulty-based dynamic model target or user override
    try:
        if FORCED_MODEL_OVERRIDE == "qwen":
            model_name = orchestrator.EXPERT_CODE_MODEL
            print("[Server] User Forced Override: Qwen 2.5 Coder 3B...")
            ensure_model_loaded("qwen")
        elif FORCED_MODEL_OVERRIDE == "granite":
            model_name = orchestrator.DEFAULT_MENTOR_MODEL
            print("[Server] User Forced Override: Granite 3.1 3B...")
            ensure_model_loaded("granite")
        elif intent == "CODE" and orchestrator.is_complex_code_task(query_text):
            model_name = orchestrator.EXPERT_CODE_MODEL
            print("[Server] Intent is CODE & Complexity is HIGH. Swapping to Qwen 2.5 Coder 3B...")
            ensure_model_loaded("qwen")
        else:
            model_name = orchestrator.DEFAULT_MENTOR_MODEL
            if intent == "CODE":
                print("[Server] Intent is CODE but task is basic/conceptual. Remaining on Granite 3.1 3B (30 t/s)...")
            ensure_model_loaded("granite")
            
        body["model"] = model_name
        print(f"[Server] Dynamic model target set & verified loaded: {model_name} (Intent: {intent})")
            
        # Clean messages by stripping image_url blocks so the text-only model server doesn't crash
        clean_messages = []
        for msg in messages:
            cleaned_msg = {"role": msg["role"]}
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                cleaned_msg["content"] = "\n".join(text_parts)
            else:
                cleaned_msg["content"] = str(content)
            clean_messages.append(cleaned_msg)
            
        stop_sequences = body.get("stop", ["<|end_of_text|>", "<|end_of_role|>", "<|role_start|>", "<|role_end|>"])
        if isinstance(stop_sequences, str):
            stop_sequences = [stop_sequences]

        max_toks = int(body.get("max_tokens", 1024))
        
        call_args = {
            "model": model_name,
            "messages": clean_messages,
            "stream": stream,
            "temperature": body.get("temperature", 0.2),
            "max_tokens": max_toks,
            "stop": stop_sequences
        }

        if "step by step" in query_text.lower() or "guide me" in query_text.lower() or "step-by-step" in query_text.lower():
            # Use strict GBNF grammar constraint instead of fragile string stop sequences
            call_args["grammar"] = STEP1_GBNF_GRAMMAR
            if "max_tokens" not in body or body.get("max_tokens") == 1024:
                call_args["max_tokens"] = 280

        if "grammar" in body:
            call_args["grammar"] = body["grammar"]
        
        # Forward penalty parameters if present
        for penalty in ["frequency_penalty", "presence_penalty", "repeat_penalty"]:
            if penalty in body:
                call_args[penalty] = body[penalty]
        
        # Forward tools and other parameters if present
        if "tools" in body:
            call_args["tools"] = body["tools"]
            
        if intent == "CODE" and "tools" in body:
            print("[Server] Intent is CODE. Setting tool_choice to 'required' to guarantee tool utilization.")
            call_args["tool_choice"] = "required"
        elif "tool_choice" in body:
            call_args["tool_choice"] = body["tool_choice"]
        if "response_format" in body:
            call_args["response_format"] = body["response_format"]

        # Package non-standard llama.cpp extension parameters into extra_body for OpenAI SDK
        extra_body = {}
        if "grammar" in call_args:
            extra_body["grammar"] = call_args.pop("grammar")
        if extra_body:
            call_args["extra_body"] = extra_body

        llm_response = orchestrator.client.chat.completions.create(**call_args)
    except Exception as e:
        print(f"[Server Error] Model server completion failed: {e}")
        try:
            fail_dump_path = os.path.join(WORKSPACE_DIR, "scratch", "last_failed_request.json")
            with open(fail_dump_path, "w", encoding="utf-8") as df:
                json.dump(body, df, indent=2)
            print(f"[Server] Logged failed request payload to {fail_dump_path}")
        except Exception as dump_err:
            print(f"[Server] Failed to log failed request payload: {dump_err}")
        raise HTTPException(status_code=500, detail=f"Model server completion failed: {e}")

    if stream:
        def event_generator():
            # Code-aware TTS state: buffer prose sentence-by-sentence, but hold a
            # fenced code block until it closes so it can be verbalized as code.
            tts_pending = ""
            tts_in_code = False
            try:
                for chunk in llm_response:
                    try:
                        chunk_json = chunk.model_dump_json()
                    except AttributeError:
                        chunk_json = json.dumps(chunk, default=lambda o: o.__dict__)
                    yield f"data: {chunk_json}\n\n"

                    if tts_enabled:
                        try:
                            delta_content = ""
                            if hasattr(chunk, 'choices') and chunk.choices:
                                delta = chunk.choices[0].delta
                                delta_content = getattr(delta, 'content', '') or ''
                            elif isinstance(chunk, dict) and 'choices' in chunk and chunk['choices']:
                                delta_content = chunk['choices'][0].get('delta', {}).get('content', '') or ''

                            if delta_content:
                                tts_pending += delta_content
                                # Drain complete units (prose sentences / closed code blocks).
                                while True:
                                    if not tts_in_code:
                                        fence = tts_pending.find("```")
                                        if fence == -1:
                                            sents, tts_pending = split_prose_sentences(tts_pending)
                                            for s in sents:
                                                if len(s) > 2:
                                                    tts_player.play_sentence(s)
                                            break
                                        # Flush prose before the opening fence, then enter code.
                                        prose = tts_pending[:fence]
                                        sents, tail = split_prose_sentences(prose)
                                        for s in sents:
                                            if len(s) > 2:
                                                tts_player.play_sentence(s)
                                        if tail.strip():
                                            tts_player.play_sentence(tail.strip())
                                        tts_pending = tts_pending[fence + 3:]
                                        tts_in_code = True
                                    else:
                                        fence = tts_pending.find("```")
                                        if fence == -1:
                                            break  # wait for the closing fence
                                        spoken_code = verbalize_code_for_speech(tts_pending[:fence])
                                        if spoken_code:
                                            tts_player.play_sentence(spoken_code)
                                        tts_pending = tts_pending[fence + 3:]
                                        tts_in_code = False
                        except Exception as e:
                            print(f"[ServerTTS Stream Error] {e}")

                # Flush whatever is left when the stream ends.
                if tts_enabled and tts_pending.strip():
                    if tts_in_code:
                        spoken_code = verbalize_code_for_speech(tts_pending)
                        if spoken_code:
                            tts_player.play_sentence(spoken_code)
                    else:
                        tts_player.play_sentence(tts_pending.strip())

                yield "data: [DONE]\n\n"
            except Exception as e:
                print(f"[Server] Streaming error: {e}")
                
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"X-Model-Used": model_name})
    else:
        try:
            resp_dict = llm_response.model_dump() if hasattr(llm_response, 'model_dump') else llm_response
            if tts_enabled:
                try:
                    content = ""
                    if isinstance(resp_dict, dict) and 'choices' in resp_dict and resp_dict['choices']:
                        content = resp_dict['choices'][0].get('message', {}).get('content', '') or ''
                    if content.strip():
                        for s in segment_for_tts(content):
                            tts_player.play_sentence(s)
                except Exception as tts_err:
                    print(f"[ServerTTS Non-Stream Error] {tts_err}")
            return resp_dict
        except Exception as e:
            return llm_response

def unload_kokoro_instance():
    global kokoro_instance
    if kokoro_instance is not None:
        print("[Server] 🧹 Unloading Kokoro TTS ONNX model from memory...")
        kokoro_instance = None
        import gc
        gc.collect()
        print("[Server] ✓ Kokoro TTS model unloaded (340 MB RAM freed).")

@app.get("/api/settings")
def get_settings():
    return {"tts_enabled": tts_enabled}

@app.post("/api/settings")
async def update_settings(request: Request):
    global tts_enabled
    body = await request.json()
    if "tts_enabled" in body:
        tts_enabled = bool(body["tts_enabled"])
        save_tts_settings()
        if not tts_enabled:
            tts_player.interrupt()
            unload_kokoro_instance()
    return {"tts_enabled": tts_enabled}

@app.post("/v1/audio/speech")
@app.post("/audio/speech")
async def audio_speech(request: Request):
    body = await request.json()
    input_text = body.get("input", "")
    voice = body.get("voice", "af_heart")
    voice_map = {
        "alloy": "af_heart",
        "echo": "am_adam",
        "fable": "af_bella",
        "onyx": "am_michael",
        "nova": "af_heart",
        "shimmer": "af_bella"
    }
    voice_style = voice_map.get(voice, voice)
    response_format = body.get("response_format", "mp3")
    speed = float(body.get("speed", 1.0))

    if not input_text:
        raise HTTPException(status_code=400, detail="Input text cannot be empty")

    try:
        kokoro = get_kokoro()
        if not kokoro:
            raise HTTPException(status_code=500, detail="Kokoro model not initialized")
        
        samples, sample_rate = kokoro.create(
            input_text,
            voice=voice_style,
            speed=speed,
            lang="en-us"
        )
        
        out_buf = io.BytesIO()
        sf.write(out_buf, samples, sample_rate, format='WAV', subtype='PCM_16')
        audio_data = out_buf.getvalue()
        
        media_type = "audio/wav"
        if response_format == "mp3":
            media_type = "audio/mpeg"
        elif response_format == "wav":
            media_type = "audio/wav"
        elif response_format == "flac":
            media_type = "audio/flac"
            
        return Response(content=audio_data, media_type=media_type)
    except Exception as e:
        print(f"[Speech API Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)

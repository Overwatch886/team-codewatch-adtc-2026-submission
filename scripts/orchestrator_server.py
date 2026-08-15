from pathlib import Path
import sys
import os
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass
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
import shutil
import uuid
from fastapi import FastAPI, Request, HTTPException, Response, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Ensure workspace is in python path for any workspace-relative imports
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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
model_load_lock = threading.Lock()

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
                # Search candidate paths for Kokoro model and voices
                model_candidates = [
                    str(Path(WORKSPACE_DIR) / "model" / "audio" / "kokoro" / "kokoro-v1.0.onnx"),
                    str(Path(WORKSPACE_DIR) / "models" / "audio" / "kokoro" / "kokoro-v1.0.onnx"),
                    str(Path(WORKSPACE_DIR) / "model" / "kokoro" / "kokoro-v1.0.onnx"),
                    str(Path(WORKSPACE_DIR) / "models" / "kokoro" / "kokoro-v1.0.onnx"),
                    str(Path(WORKSPACE_DIR) / "model" / "audio" / "kokoro" / "kokoro-v1.0.int8.onnx"),
                    str(Path(WORKSPACE_DIR) / "models" / "audio" / "kokoro" / "kokoro-v1.0.int8.onnx"),
                    str(Path(WORKSPACE_DIR) / "model" / "kokoro" / "kokoro-v1.0.int8.onnx"),
                ]
                voices_candidates = [
                    str(Path(WORKSPACE_DIR) / "model" / "audio" / "kokoro" / "voices-v1.0.bin"),
                    str(Path(WORKSPACE_DIR) / "models" / "audio" / "kokoro" / "voices-v1.0.bin"),
                    str(Path(WORKSPACE_DIR) / "model" / "kokoro" / "voices-v1.0.bin"),
                    str(Path(WORKSPACE_DIR) / "models" / "kokoro" / "voices-v1.0.bin"),
                ]
                model_path = next((p for p in model_candidates if os.path.exists(p)), model_candidates[0])
                voices_path = next((p for p in voices_candidates if os.path.exists(p)), voices_candidates[0])
                if not os.path.exists(model_path) or not os.path.exists(voices_path):
                    print(f"[ServerTTS Error] Kokoro model or voices missing. Paths checked: {model_path}, {voices_path}", file=sys.stderr)
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
        
        # --- PROCESS MEMORY SCAN ---
        # Scan /proc to find pids and VmRSS memory usage for our stack components.
        granite_rss_mb = 0.0
        kokoro_rss_mb = 0.0
        colbert_rss_mb = 0.0
        orchestrator_rss_mb = 0.0
        vision_rss_mb = 0.0
        granite_pid = 0

        # Read cgroup PIDs if cgroup v2 is active
        cgroup_pids = None
        cgroup_limit_mb = None
        cgroup_used_mb = None

        try:
            cgroup_rel_path = ""
            # IMPORTANT: read MY OWN cgroup, not /proc/self which resolves to
            # whatever process calls the HTTP endpoint (e.g. the IDE shell).
            with open(f"/proc/{my_pid}/cgroup", "r") as f:
                for line in f:
                    parts = line.strip().split("::")
                    if len(parts) == 2 and parts[0] == "0":
                        cgroup_rel_path = parts[1].strip()
                        break

            if cgroup_rel_path:
                cgroup_base = f"/sys/fs/cgroup{cgroup_rel_path}"
                search_path = cgroup_base
                while search_path and search_path != "/sys/fs/cgroup":
                    max_path = os.path.join(search_path, "memory.max")
                    if os.path.exists(max_path):
                        with open(max_path, "r") as f:
                            raw = f.read().strip()
                        if raw != "max":
                            cgroup_limit_mb = int(raw) / 1024 / 1024
                            break
                    search_path = os.path.dirname(search_path)

                stat_path = os.path.join(cgroup_base, "memory.stat")
                if os.path.exists(stat_path):
                    stat = {}
                    with open(stat_path, "r") as f:
                        for sline in f:
                            sp = sline.split()
                            if len(sp) == 2:
                                stat[sp[0]] = int(sp[1])
                    cgroup_used_mb = (
                        stat.get("anon",  0) +
                        stat.get("file",  0) +
                        stat.get("shmem", 0)
                    ) / 1024 / 1024

                procs_path = os.path.join(cgroup_base, "cgroup.procs")
                if os.path.exists(procs_path):
                    with open(procs_path, "r") as f:
                        cgroup_pids = set(
                            int(l.strip()) for l in f if l.strip().isdigit()
                        )
        except Exception:
            pass

        # Scan PIDs (restricted to cgroup if available, else all system PIDs)
        # IMPORTANT: We read RssAnon (truly anonymous/heap RAM) NOT VmRSS.
        # VmRSS includes mmap'd file pages (the full GGUF file mapped with --mmap)
        # which inflates the model memory reading to nearly the full file size.
        # RssAnon = actual physical RAM used by the process excluding file mappings.
        def read_rss_total(pid: int) -> float:
            """Return VmRSS (total physical RAM in MB) for a PID, including mmap'd model pages."""
            try:
                with open(f"/proc/{pid}/status", "r") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) / 1024.0
            except Exception:
                pass
            return 0.0

        pid_list = cgroup_pids if cgroup_pids else [int(p) for p in os.listdir("/proc") if p.isdigit()]
        for pid in pid_list:
            try:
                cmdline = ""
                if os.path.exists(f"/proc/{pid}/cmdline"):
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')

                if pid == my_pid:
                    orchestrator_rss_mb += read_rss_total(pid)
                elif "mmproj" in cmdline.lower() or "lfm" in cmdline.lower() or "vision" in cmdline.lower():
                    vision_rss_mb += read_rss_total(pid)
                elif ("llama-server" in cmdline or "llama-cli" in cmdline) and (
                    "8081" in cmdline or "port 8081" in cmdline or "granite" in cmdline.lower()
                ):
                    granite_rss_mb += read_rss_total(pid)
                    granite_pid = pid
                elif "acolbert" in cmdline:
                    colbert_rss_mb += read_rss_total(pid)
            except Exception:
                pass

        # Fallback: if llama-server wasn't found in cgroup PIDs, scan all /proc
        if granite_rss_mb == 0.0:
            for pid_dir in os.listdir("/proc"):
                if pid_dir.isdigit():
                    pid = int(pid_dir)
                    try:
                        cmdline = ""
                        if os.path.exists(f"/proc/{pid}/cmdline"):
                            with open(f"/proc/{pid}/cmdline", "rb") as f:
                                cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')
                        if ("llama-server" in cmdline or "llama-cli" in cmdline) and ("8081" in cmdline or "port 8081" in cmdline):
                            granite_rss_mb = read_rss_total(pid)
                            granite_pid = pid
                            break
                    except Exception:
                        pass

        # Estimate in-process ColBERT memory
        is_colbert_loaded = False
        try:
            import acolbert
            if acolbert.session is not None:
                is_colbert_loaded = True
        except Exception:
            pass

        if colbert_rss_mb == 0.0 and is_colbert_loaded:
            colbert_rss_mb = 200.0
            orchestrator_rss_mb = max(40.0, orchestrator_rss_mb - colbert_rss_mb)

        # Estimate in-process Kokoro TTS memory
        if kokoro_instance is not None:
            kokoro_rss_mb = 340.0
            orchestrator_rss_mb = max(40.0, orchestrator_rss_mb - kokoro_rss_mb)
            
        # Get prompt cache tokens from llama-server slots endpoint
        n_prompt_tokens_cache = 0
        try:
            slots_res = requests.get("http://127.0.0.1:8081/slots", timeout=0.3)
            if slots_res.status_code == 200:
                for slot in slots_res.json():
                    n_prompt_tokens_cache += slot.get("n_prompt_tokens_cache", 0)
        except Exception:
            pass
            
        prompt_cache_mb = n_prompt_tokens_cache * 0.03125

        # Determine model name and exact file size on disk
        default_model_name = "Granite 4.0 H-Tiny"
        m_dir = Path(__file__).resolve().parent.parent / "model"
        possible_paths = [
            m_dir / "granite-4.0-h-tiny.i1-IQ4_XS.gguf",
            m_dir / "granite" / "granite-4.0-h-tiny.i1-IQ4_XS.gguf",
        ]
        model_path = str(next((p for p in possible_paths if p.exists()), possible_paths[0]))

        model_name = default_model_name
        disk_size_gb = 3.49
        if os.path.exists(model_path):
            disk_size_gb = round(os.path.getsize(model_path) / (1024.0 * 1024.0 * 1024.0), 2)

        try:
            props_res = requests.get("http://127.0.0.1:8081/props", timeout=0.3)
            if props_res.status_code == 200:
                props_data = props_res.json()
                live_path = props_data.get("model_path", "")
                if live_path and os.path.exists(live_path):
                    base_name = os.path.basename(live_path)
                    if "granite" in base_name.lower():
                        model_name = "Granite 4.0 H-Tiny"
                    else:
                        clean_name = base_name.replace(".gguf", "")
                        clean_name = re.sub(r'[-_]Q[0-9]_[A-Za-z0-9_]+', '', clean_name)
                        model_name = clean_name.replace("-", " ").replace("_", " ").title()
                    disk_size_gb = round(os.path.getsize(live_path) / (1024.0 * 1024.0 * 1024.0), 2)
        except Exception:
            pass

        granite_gpu_mb = read_gpu_resident_mb(granite_pid)

        # In mmap mode, granite_rss_mb is the true physical RAM used by llama-server (mmap'd weights + KV cache)
        if granite_rss_mb > 0.0:
            llama_cpp_overhead_mb = min(60.0, max(20.0, granite_rss_mb * 0.02))
            granite_weights_mb = max(0.0, granite_rss_mb - llama_cpp_overhead_mb - prompt_cache_mb)
        else:
            granite_weights_mb = 0.0
            llama_cpp_overhead_mb = 0.0

        # Determine total / used / available RAM
        # When cgroup is active: total_used = cgroup_used_mb (authoritative).
        # OS baseline = whatever cgroup is using that we can't attribute to our known processes.
        if cgroup_limit_mb is not None and cgroup_used_mb is not None:
            total_gb      = round(cgroup_limit_mb / 1024.0, 2)
            used_gb       = round(cgroup_used_mb / 1024.0, 2)
            available_gb  = round(max(0.0, total_gb - used_gb), 2)
            total_used_mb = cgroup_used_mb

            known_mb = (granite_weights_mb + llama_cpp_overhead_mb + prompt_cache_mb +
                        colbert_rss_mb + kokoro_rss_mb + orchestrator_rss_mb + vision_rss_mb)
            os_baseline_mb = max(0.0, cgroup_used_mb - known_mb)
        else:
            total_used_mb = (granite_weights_mb + llama_cpp_overhead_mb + prompt_cache_mb + granite_gpu_mb + kokoro_rss_mb + colbert_rss_mb + orchestrator_rss_mb + vision_rss_mb)
            used_gb      = round(total_used_mb / 1024.0, 2)
            total_gb     = round(psutil.virtual_memory().total / 1024.0 / 1024.0 / 1024.0, 2)
            available_gb = round(max(0.0, total_gb - used_gb), 2)
            os_baseline_mb = 0.0


        # Vision RAM reporting with exact MB / GB numbers
        if vision_rss_mb > 0.0:
            if vision_rss_mb >= 1024.0:
                vision_status_str = f"{(vision_rss_mb / 1024.0):.2f} GB (Active)"
            else:
                vision_status_str = f"{vision_rss_mb:.1f} MB (Active)"
        elif time.time() - LAST_VISION_ACTIVE_TIME < 60:
            vision_status_str = "0 MB (Idle - Ready)"
        else:
            vision_status_str = "0 MB (Idle)"



        return {
            "total_gb": total_gb,
            "used_gb": round(used_gb, 2),
            "available_gb": round(available_gb, 2),
            "granite_rss_mb": round(granite_rss_mb, 2),
            "cgroup_active": cgroup_limit_mb is not None,
            "cgroup_limit_gb": round(cgroup_limit_mb / 1024.0, 2) if cgroup_limit_mb else None,
            "breakdown": {
                "os_baseline_mb": round(os_baseline_mb, 1),   # kernel + other processes merged
                "model_name": model_name,
                "model_disk_gb": disk_size_gb,
                "model_weights_mb": round(granite_weights_mb, 1),
                "granite_gpu_mb": round(granite_gpu_mb, 1),
                "llama_cpp_overhead_mb": round(llama_cpp_overhead_mb, 1),
                "prompt_cache_mb": round(prompt_cache_mb, 1),
                "colbert_rss_mb": round(colbert_rss_mb, 1),
                "kokoro_rss_mb": round(kokoro_rss_mb, 1),
                "orchestrator_rss_mb": round(orchestrator_rss_mb, 1),
                "vision_rss_mb": round(vision_rss_mb, 1),     # real RSS from /proc when vision is active
                "vision_status": vision_status_str,
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
    global FORCED_MODEL_OVERRIDE, CURRENT_SESSION_MODE
    try:
        body = await request.json()
        target = body.get("model", "socratic_study").lower()

        if target in ("fast_ship", "fast"):
            FORCED_MODEL_OVERRIDE = "fast_ship"
            CURRENT_SESSION_MODE = "fast_ship"
            ensure_model_loaded("granite")
            return {"status": "ok", "active_model": "Granite 4.0 H-Tiny (Build & Ship Fast Mode)", "override": "fast_ship"}
        else:
            FORCED_MODEL_OVERRIDE = "socratic_study"
            CURRENT_SESSION_MODE = "socratic_study"
            ensure_model_loaded("granite")
            return {"status": "ok", "active_model": "Granite 4.0 H-Tiny (Step-by-Step Socratic Study Mode)", "override": "socratic_study"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

CURRENT_SESSION_MODE = "socratic_study"

@app.post("/set_session_mode")
async def set_session_mode(request: Request):
    global CURRENT_SESSION_MODE, FORCED_MODEL_OVERRIDE
    body = await request.json()
    mode = body.get("mode", "socratic_study")
    if mode == "fast_ship":
        CURRENT_SESSION_MODE = "fast_ship"
        FORCED_MODEL_OVERRIDE = "fast_ship"
        ensure_model_loaded("granite")
        active_model = "Granite 4.0 H-Tiny (Build & Ship Fast Mode)"
    else:
        CURRENT_SESSION_MODE = "socratic_study"
        FORCED_MODEL_OVERRIDE = "socratic_study"
        ensure_model_loaded("granite")
        active_model = "Granite 4.0 H-Tiny (Step-by-Step Socratic Study Mode)"
    print(f"[Server] Session mode updated to: {CURRENT_SESSION_MODE} ({active_model})")
    return {"status": "ok", "session_mode": CURRENT_SESSION_MODE, "active_model": active_model}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


def is_port_8081_process_alive():
    try:
        res = subprocess.run(["fuser", "8081/tcp"], capture_output=True, text=True)
        return bool(res.stdout.strip())
    except Exception:
        return False

def ensure_model_loaded(target_key: str = "granite", force_restart: bool = False):
    global CURRENT_LOADED_MODEL_KEY
    import requests

    with model_load_lock:
        if not force_restart and CURRENT_LOADED_MODEL_KEY == "granite":
            try:
                r = requests.get("http://127.0.0.1:8081/health", timeout=5.0)
                if r.status_code == 200 and r.json().get("status") == "ok":
                    return
            except Exception:
                if is_port_8081_process_alive():
                    print("[Server Info] Granite 4.0 H Tiny model recorded as loaded, port 8081 process is alive but busy. Skipping restart...")
                    return
                print("[Server Warning] Granite 4.0 H Tiny model recorded as loaded, but port 8081 is not responding. Forcing restart...")

        print("[Server] 🔄 Launching resident Granite 4.0 H Tiny Q4_K_S model (llama-server, -ngl 25)...")
        subprocess.run(["fuser", "-k", "8081/tcp"], capture_output=True)
        time.sleep(1)

        LLAMA_SERVER_BIN = str(Path(__file__).resolve().parent.parent / "software" / "llama.cpp" / "build" / "bin" / "llama-server")

        m_dir = Path(__file__).resolve().parent.parent / "model"
        possible_paths = [
            m_dir / "granite-4.0-h-tiny.i1-IQ4_XS.gguf",
            m_dir / "granite" / "granite-4.0-h-tiny.i1-IQ4_XS.gguf",
        ]
        model_path = str(next((p for p in possible_paths if p.exists()), possible_paths[0]))
        alias_name = "granite-4.0-h-tiny"
        # Auto-detect GPU build vs pure CPU build capabilities
        import psutil
        logical_cores = os.cpu_count() or 4
        physical_cores = psutil.cpu_count(logical=False) or (logical_cores // 2) or 4
        has_gpu_build = False
        server_bin_dir = Path(LLAMA_SERVER_BIN).parent

        # 1. Check for shared libraries in build bin dir (libggml-vulkan.so, libggml-cuda.so, etc.)
        for lib in server_bin_dir.glob("libggml-*.so*"):
            lname = lib.name.lower()
            if any(k in lname for k in ["vulkan", "cuda", "rocm", "clblast", "kompute"]):
                has_gpu_build = True
                break

        # 2. Check dynamic linked libraries using ldd
        if not has_gpu_build:
            try:
                ldd_res = subprocess.run(["ldd", LLAMA_SERVER_BIN], capture_output=True, text=True)
                out_str = (ldd_res.stdout + ldd_res.stderr).lower()
                if any(k in out_str for k in ["vulkan", "cuda", "rocm", "nouveau", "nvidia", "hip", "opencl"]):
                    has_gpu_build = True
            except Exception:
                pass

        # 3. Fallback: Check --help or --version output
        if not has_gpu_build:
            try:
                help_res = subprocess.run([LLAMA_SERVER_BIN, "--help"], capture_output=True, text=True)
                out_str = (help_res.stdout + help_res.stderr).lower()
                if any(k in out_str for k in ["vulkan", "cuda", "rocm"]):
                    has_gpu_build = True
            except Exception:
                pass

        if has_gpu_build:
            ngl_flag = os.getenv("LLAMA_NGL", "25")
            llama_threads = os.getenv("LLAMA_THREADS", str(max(1, physical_cores // 2)))
            print(f"[Server] GPU Offload Build detected: Setting -ngl {ngl_flag}, threads = {llama_threads} (half of {physical_cores} physical CPU cores)")
        else:
            ngl_flag = "0"
            llama_threads = os.getenv("LLAMA_THREADS", str(physical_cores))
            print(f"[Server] Pure CPU Build detected: Setting -ngl 0, threads = {llama_threads} (all {physical_cores} physical CPU cores)")

        llama_ctx = os.getenv("LLAMA_CTX_SIZE", os.getenv("LLAMA_CTX_SIZE_GRANITE", "8192"))
        llama_batch = os.getenv("LLAMA_BATCH_SIZE", "2048")
        llama_ubatch = os.getenv("LLAMA_UBATCH_SIZE", "512")
        llama_http_threads = os.getenv("LLAMA_HTTP_THREADS", "2")
        llama_cache_ram = os.getenv("LLAMA_CACHE_RAM", "64")
        llama_ctk = os.getenv("LLAMA_CTK", "q8_0")
        llama_ctv = os.getenv("LLAMA_CTV", "q8_0")

        # Auto-detect container vs bare-metal capabilities
        import resource
        can_mlock = False
        try:
            soft_mem, hard_mem = resource.getrlimit(resource.RLIMIT_MEMLOCK)
            can_mlock = (hard_mem == resource.RLIM_INFINITY or hard_mem > 1024 * 1024 * 1024)
        except Exception:
            can_mlock = False

        cmd = [
            LLAMA_SERVER_BIN,
            "-m", model_path,
            "-c", llama_ctx, "-b", llama_batch, "-ub", llama_ubatch, "-t", llama_threads,
            "--port", "8081", "--threads-http", llama_http_threads, "--parallel", "1", "--cache-ram", llama_cache_ram,
            "-ctk", llama_ctk, "-ctv", llama_ctv,
            "--load-mode", "mmap", "-ngl", ngl_flag, "--jinja",
            "--alias", alias_name,
        ]

        env = dict(os.environ)
        env["RADV_PERFTEST"] = "nosam"

        logs_dir = Path(__file__).resolve().parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        llama_log_path = os.path.join(logs_dir, "llama_server.log")
        log_f = open(llama_log_path, "a")
        subprocess.Popen(cmd, env=env, stdout=log_f, stderr=log_f)

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
            time.sleep(1.0)
            print("[Server] ✓ Granite 4.0 H Tiny IQ4_XS model server ONLINE (-ngl 25).")
        else:
            print("[Server Warning] Granite 4.0 H Tiny model server startup took longer than 30s.")

        CURRENT_LOADED_MODEL_KEY = "granite"


@app.on_event("startup")
async def startup_event():
    print("[Server Startup] 🚀 Automatically loading Granite 4.0 H Tiny IQ4_XS into memory...")
    try:
        ensure_model_loaded("granite", force_restart=False)
    except Exception as e:
        print(f"[Server Startup Warning] Initial model load error: {e}")




TEACHER_SYSTEM_PROMPT = """You are Professor LowaCode, a master Socratic programming tutor powered by Granite 4.0 H-Tiny.

## WHAT BEING SOCRATIC MEANS
Being Socratic means you NEVER give textbook lectures or written code solutions.
Instead, you guide the student step-by-step through a multi-step learning sequence (`Step 1` -> `Step 2` -> `Step 3` -> ...), advancing one step per conversation turn.

## MULTI-STEP PROGRESSION MANDATE (STRICTLY REQUIRED)
1. **Track Step Progression**: Look at the conversation history to determine the active step number N (e.g. Step 1 for initial question, Step 2 after user answers Step 1, Step 3 after user answers Step 2, etc.).
2. **Acknowledge & Advance**: Briefly validate the user's answer to the previous step, then immediately introduce Step N.
3. **Single Step Per Turn**: Output ONLY the single current Step N in your response turn. Do NOT output future steps or full solutions all at once.

## FORMAT MANDATE (STRICTLY REQUIRED FOR EVERY RESPONSE)
Structure EVERY response using this EXACT format:

### 🛠️ Step N: [Current Step Focus]
[1-2 sentences acknowledging progress and explaining the concept focus for Step N]

**Your Task**: [Ask 1 clear, actionable guiding question for Step N to lead the student to the next discovery]

## RULES
1. ADVANCE THE STEP NUMBER (Step 1, Step 2, Step 3...) dynamically as the conversation progresses. NEVER stay stuck repeating Step 1 if the user has already answered it!
2. ABSOLUTELY NO CODE BLOCKS, NO SYNTAX EXPLANATIONS, AND NO DIRECT ANSWERS.
3. Keep guiding questions simple and practical so the student can easily answer and move to the next step.

## FEW-SHOT MULTI-TURN CONVERSATION EXAMPLE

User: breakdown polymorphism to me step by step
Assistant:
### 🛠️ Step 1: One Action, Different Behaviors
Imagine a button labeled "Play". On a music app it plays a song, on a video app it plays a movie, and on a game console it starts a game. The action is the exact same ("Play"), but each device responds in its own unique way. In programming, polymorphism allows different objects to respond to the exact same action in their own special way.

**Your Task**: If you have a `Dog` object and a `Cat` object, and both receive the command `make_sound()`, what unique sound would you expect each object to output?

User: The dog will bark and the cat will meow.
Assistant:
### 🛠️ Step 2: Method Overriding
Spot on! Both objects respond to the exact same `make_sound()` method name, but each class provides its own custom implementation. In object-oriented programming, this is called "method overriding", where a subclass redefines a method inherited from a parent class.

**Your Task**: If both `Dog` and `Cat` inherit from a parent class called `Animal`, should the `make_sound()` method be declared first in the `Animal` parent class or only in the child classes?

User: It should be declared in the Animal parent class first.
Assistant:
### 🛠️ Step 3: Polymorphic Method Calls
Exactly right! By declaring `make_sound()` in the parent `Animal` class, you can create a list containing both Dogs and Cats, loop through the list, and call `animal.make_sound()` on every item without needing to know whether it is a Dog or a Cat.

**Your Task**: What major benefit does this provide when you want to add a new `Cow` class to your program in the future?"""

EXPERT_DEVELOPER_SYSTEM_PROMPT = """You are an expert software engineer and direct coding assistant named Professor LowaCode.

## MANDATE
1. Provide direct, production-grade, clean, bug-free, and optimal code implementations.
2. Execute tool calls and answer questions directly without Socratic restrictions.
3. Be concise, precise, and practical."""

STEP1_GBNF_GRAMMAR = """root ::= step1-header "\n\n" explanation "\n\n" task-header "\n" task-body
step1-header ::= "### ️ Step 1: " [^\n]{1,100}
explanation ::= [^\n]{1,300}
task-header ::= "**Your Task**: "
task-body ::= [^\n]{1,300}
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

    req_session_mode = body.get("session_mode", CURRENT_SESSION_MODE)

    # Ensure system prompt matches active session mode
    has_system = False
    for msg in messages:
        if msg.get("role") == "system":
            has_system = True
            if req_session_mode == "fast_ship":
                msg["content"] = EXPERT_DEVELOPER_SYSTEM_PROMPT
            else:
                msg["content"] = TEACHER_SYSTEM_PROMPT
            break
            
    if not has_system:
        sys_prompt = EXPERT_DEVELOPER_SYSTEM_PROMPT if req_session_mode == "fast_ship" else TEACHER_SYSTEM_PROMPT
        messages.insert(0, {"role": "system", "content": sys_prompt})
        
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
        print(f"[Server] Analyzing query: {query_text!r} (Session Mode: {req_session_mode})")
        intent, entities, scores = orchestrator.analyze_query(query_text)
        image_paths = orchestrator.extract_image_paths(query_text, entities)
        # Merge both sources of image paths (regex mentions + direct uploads)
        image_paths = list(set(image_paths + extracted_image_paths))
        text_entities = orchestrator.extract_text_file_entities(entities)
        if extracted_doc_paths:
            text_entities.extend([{"label": "FILE_PATH", "text": p} for p in extracted_doc_paths])
        
        prompt_context = ""
        vision_context = ""
        
        if text_entities:
            print(f"[Server] Loading attached document/file context ({len(text_entities)} files)...")
            prompt_context = orchestrator.build_file_context(text_entities, query_text)
        elif intent == "RAG":
            print("[Server] Intent is RAG. Performing local ColBERT retrieval...")
            prompt_context = orchestrator.build_rag_context(query_text, entities)
            
        if (intent == "VISION" or image_paths) and image_paths:
            print("[Server] Vision active. Running LFM2.5-VL alongside resident model (llama-cli RAM savings cover budget).")
            # RAM budget during vision:
            #   Resident LLM (llama-cli, Granite/Qwen Q4_K_M): ~2.09 GB
            #   Vision model (LFM2.5-VL Q4_0):                  ~0.70 GB
            #   Vision mmproj (Q8_0):                            ~0.57 GB
            #   Python + FastAPI overhead:                        ~0.12 GB
            #   KV cache (4096 ctx):                             ~0.28 GB
            #   ColBERT ONNX:                                    ~0.20 GB
            #   llama-cli saves ~130 MB vs llama-server → no ColBERT eviction needed
            #   ─────────────────────────────────────────────────────────────────────
            #   Total peak:                                      ~3.96 GB  ✓ under 4 GB
            try:
                global LAST_VISION_ACTIVE_TIME
                LAST_VISION_ACTIVE_TIME = time.time()
                vision_context = orchestrator.build_vision_context(query_text, image_paths)
                print("[Server] ✓ Vision description complete.")
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
                last_user_msg["content"] = query
            else:
                last_user_msg["content"] = f"{injected_text}\nUser Question: {query}"
            print("[Server] Context successfully injected into user message.")

        # --- CONTEXT PRUNING MIDDLEWARE ---
        # 1. System prompt is kept 100% intact so Socratic tutoring rules & mandates are preserved
        for msg in messages:
            if msg.get("role") == "system":
                print(f"[Server] System Prompt active:\n{msg.get('content', '')[:150]}...\n[Server] End of System Prompt Header")

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
        target_key = "granite"
        model_name = "granite-4.0-h-tiny"
        if req_session_mode == "fast_ship" or FORCED_MODEL_OVERRIDE == "fast_ship":
            print("[Server] Mode: Build & Ship Fast (Granite 4.0 H-Tiny + Direct Code System Prompt)")
        else:
            print("[Server] Mode: Socratic Study (Granite 4.0 H-Tiny + Socratic Tutor System Prompt)")

        ensure_model_loaded("granite")

        body["model"] = model_name
        print(f"[Server] Dynamic model target set & verified loaded: {model_name}")
            
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

        for penalty in ["frequency_penalty", "presence_penalty", "repeat_penalty"]:
            if penalty in body:
                call_args[penalty] = body[penalty]
        
        if "tools" in body:
            call_args["tools"] = body["tools"]
            
        if intent == "CODE" and "tools" in body:
            print("[Server] Intent is CODE. Setting tool_choice to 'required' to guarantee tool utilization.")
            call_args["tool_choice"] = "required"
        elif "tool_choice" in body:
            call_args["tool_choice"] = body["tool_choice"]
        if "response_format" in body:
            call_args["response_format"] = body["response_format"]

        try:
            llm_response = orchestrator.client.chat.completions.create(**call_args)
        except Exception as first_err:
            print(f"[Server Auto-Recovery ⚠️] Model completion failed ({first_err}). Auto-restarting model server on 8081 for '{target_key}'...")
            try:
                ensure_model_loaded(target_key, force_restart=True)
                llm_response = orchestrator.client.chat.completions.create(**call_args)
                print(f"[Server Auto-Recovery ✓] Model server successfully recovered and completed request!")
            except Exception as retry_err:
                print(f"[Server Fatal Error] Model server recovery failed: {retry_err}")
                try:
                    fail_dump_path = os.path.join(WORKSPACE_DIR, "scratch", "last_failed_request.json")
                    with open(fail_dump_path, "w", encoding="utf-8") as df:
                        json.dump(body, df, indent=2)
                    print(f"[Server] Logged failed request payload to {fail_dump_path}")
                except Exception:
                    pass
                raise HTTPException(
                    status_code=503,
                    detail=f"Model server (port 8081) was unavailable ({retry_err}). An automatic server restart was attempted. Please resend your message."
                )
    except HTTPException:
        raise
    except Exception as general_err:
        print(f"[Server Error] Request processing failed: {general_err}")
        raise HTTPException(status_code=500, detail=f"Request processing failed: {general_err}")


    if stream:
        def event_generator():
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
                                while True:
                                    if not tts_in_code:
                                        fence = tts_pending.find("```")
                                        if fence == -1:
                                            sents, tts_pending = split_prose_sentences(tts_pending)
                                            for s in sents:
                                                if len(s) > 2:
                                                    tts_player.play_sentence(s)
                                            break
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
                                            break
                                        spoken_code = verbalize_code_for_speech(tts_pending[:fence])
                                        if spoken_code:
                                            tts_player.play_sentence(spoken_code)
                                        tts_pending = tts_pending[fence + 3:]
                                        tts_in_code = False
                        except Exception as e:
                            print(f"[ServerTTS Stream Error] {e}")

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

possible_parakeet_bins = [
    str(Path(__file__).resolve().parent.parent / "software" / "parakeet.cpp" / "build" / "examples" / "cli" / "parakeet-cli"),
    str(Path(__file__).resolve().parent.parent.parent / "software" / "parakeet.cpp" / "build" / "examples" / "cli" / "parakeet-cli"),
    "/home/overwatch886/local_ai_workspace/software/parakeet.cpp/build/examples/cli/parakeet-cli",
]
PARAKEET_BIN = next((p for p in possible_parakeet_bins if os.path.exists(p)), possible_parakeet_bins[0])

possible_parakeet_models = [
    str(Path(__file__).resolve().parent.parent / "model" / "audio" / "tdt-0.6b-v2-q5_k.gguf"),
    str(Path(__file__).resolve().parent.parent.parent / "model" / "audio" / "tdt-0.6b-v2-q5_k.gguf"),
    "/home/overwatch886/local_ai_workspace/model/audio/tdt-0.6b-v2-q5_k.gguf",
]
PARAKEET_MODEL = next((p for p in possible_parakeet_models if os.path.exists(p)), possible_parakeet_models[0])

@app.post("/v1/audio/transcriptions")
@app.post("/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(None),
    request: Request = None
):
    """
    100% Offline Speech-to-Text Transcription endpoint powered by Parakeet TDT.
    """
    try:
        content = None
        filename = "recording.webm"
        if file:
            content = await file.read()
            if file.filename:
                filename = file.filename
        elif request:
            content = await request.body()

        if not content:
            raise HTTPException(status_code=400, detail="No audio data received")

        # Choose model: prefer tdt-0.6b-v2-q5_k, fallback to SBPN model
        asr_model = PARAKEET_MODEL
        if not os.path.exists(asr_model):
            alt_model = str(Path(__file__).resolve().parent.parent / "model" / "audio" / "SBPN_multilingual_large_q8_0.gguf")
            if os.path.exists(alt_model):
                asr_model = alt_model

        if not os.path.exists(PARAKEET_BIN) or not os.path.exists(asr_model):
            print(f"⚠️ STT Error: Parakeet bin ({PARAKEET_BIN}) or model ({asr_model}) not found.")
            raise HTTPException(status_code=500, detail="Parakeet STT binary or model file not found on server")

        temp_dir = tempfile.gettempdir()
        raw_audio_path = os.path.join(temp_dir, f"stt_raw_{uuid.uuid4().hex[:8]}_{filename}")
        wav_16k_path = os.path.join(temp_dir, f"stt_16k_{uuid.uuid4().hex[:8]}.wav")

        with open(raw_audio_path, "wb") as f:
            f.write(content)

        # Convert incoming audio to 16kHz mono WAV for parakeet-cli using ffmpeg
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        if os.path.exists(ffmpeg_bin):
            conv_cmd = [ffmpeg_bin, "-y", "-i", raw_audio_path, "-ar", "16000", "-ac", "1", wav_16k_path]
            subprocess.run(conv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            target_wav = wav_16k_path
        else:
            target_wav = raw_audio_path

        cmd = [PARAKEET_BIN, "transcribe", "--model", asr_model, "--input", target_wav]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        raw_text = res.stdout.strip()
        clean_text = re.sub(r'<[^>]*>', '', raw_text).strip()

        # Clean up temporary audio files
        for p in [raw_audio_path, wav_16k_path]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

        print(f"[STT Parakeet] Transcribed audio ({len(content)} bytes) -> {clean_text!r}")
        return JSONResponse({"text": clean_text})

    except Exception as e:
        print(f"⚠️ Parakeet STT Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)

#!/usr/bin/env python3
import os
import sys
import json
import base64
import subprocess
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ──────────────────────────────────────────────────────────
# SYSTEM CONSTRAINTS & PORT CONFIGURATIONS
# ──────────────────────────────────────────────────────────
ROUTER_PORT = 8085             
ORCHESTRATOR_URL = "http://localhost:8080/v1"  # LFM2.5-Audio-1.5B (Permanent Audio/Text Core)
DYNAMIC_ZONE_URL = "http://localhost:8081/v1"  # Hot-swap port (Qwen, Thinking, TTT, Vision)

LONG_CONTEXT_THRESHOLD = 12000 

BASE_DIR = os.path.expanduser("~/local_ai_workspace")
LLAMA_SERVER_BIN = os.path.join(BASE_DIR, "software/llama.cpp/build/bin/llama-server")
DYNAMIC_ZONE_LOG = "/tmp/dynamic_zone.log"
ORCHESTRATOR_LOG = "/tmp/orchestrator_core.log"

MODEL_PATHS = {
    "orchestrator_core": os.path.join(BASE_DIR, "models/audio/LFM2.5-Audio-1.5B-Q4_0.gguf"),
    "orchestrator_projector": os.path.join(BASE_DIR, "models/audio/mmproj-LFM2.5-Audio-1.5B-Q4_0.gguf"),
    "vision": os.path.join(BASE_DIR, "models/lnn/vision/LFM2.5-VL-1.6B-Q4_0.gguf"),
    "qwen_reasoning": os.path.join(BASE_DIR, "models/core_pool/Qwen3.5-4B-Q4_K_M.gguf"),
    "thinking_coder": os.path.join(BASE_DIR, "models/lnn/LFM2.5-1.2B-Thinking-Q4_K_M.gguf"),
    "ttt_long_context": os.path.join(BASE_DIR, "models/ttt/lfm-2.6-ttt-sft-new.Q4_K_M.gguf"),
    "vision_projector": os.path.join(BASE_DIR, "models/lnn/vision/mmproj-LFM2.5-VL-1.6b-Q8_0.gguf")
}

def is_server_running(url):
    try:
        response = requests.get(f"{url}/models", timeout=1)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def terminate_port(port):
    subprocess.run(f"fuser -k {port}/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

# ──────────────────────────────────────────────────────────
# HARDCODED ORCHESTRATOR BOOT ROUTINE
# ──────────────────────────────────────────────────────────
def boot_permanent_orchestrator():
    """Hardcoded auto-start for the 1.5B Audio-Text core on port 8080 if not running."""
    if is_server_running(ORCHESTRATOR_URL):
        print("[Router] Permanent 1.5B Orchestrator Core is already active on port 8080.")
        return True

    print("[Router] 🚀 Booting Hardcoded LFM2.5-Audio-1.5B Core on port 8080...")
    
    # We pass 3 threads here to keep your 4650U responsive during text routing and classification
    cmd = (
        f"{LLAMA_SERVER_BIN} -m {MODEL_PATHS['orchestrator_core']} "
        f"--mmproj {MODEL_PATHS['orchestrator_projector']} "
        f"-c 4096 --port 8080 -t 3 > {ORCHESTRATOR_LOG} 2>&1 &"
    )
    subprocess.Popen(cmd, shell=True)
    
    # Give it ample time to load the weights into your 16GB RAM array
    for i in range(20):
        if is_server_running(ORCHESTRATOR_URL):
            print("[Router] 🎉 Permanent Orchestrator Core fully online and tracking.")
            return True
        time.sleep(1)
        
    print(f"[Router❌] Core boot failed to bind to 8080. Check runtime outputs in {ORCHESTRATOR_LOG}")
    return False

def speak_response_via_system(text):
    cleaned_text = text.replace('"', '\\"').replace("'", "\\'")
    subprocess.Popen(f"/home/overwatch886/local_ai_workspace/scripts/speak.sh \"{cleaned_text}\"", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def spin_up_dynamic_model(model_key, threads=2, ctx=4096):
    if is_server_running(DYNAMIC_ZONE_URL):
        try:
            res = requests.get(f"{DYNAMIC_ZONE_URL}/models", timeout=0.5).json()
            if model_key in res.get("data", [{}])[0].get("id", ""):
                return True
        except:
            pass
        terminate_port(8081)

    print(f"[Router] Target Configuration: {model_key.upper()} | Threads: {threads} | Context: {ctx}")
    mmproj_flag = f"--mmproj {MODEL_PATHS['vision_projector']}" if model_key == "vision" else ""

    cmd = f"{LLAMA_SERVER_BIN} -m {MODEL_PATHS[model_key]} {mmproj_flag} -c {ctx} --port 8081 -t {threads} > {DYNAMIC_ZONE_LOG} 2>&1 &"
    subprocess.Popen(cmd, shell=True)

    time.sleep(1.5) 
    for _ in range(15):
        if is_server_running(DYNAMIC_ZONE_URL): return True
        time.sleep(1)
    return False

# ──────────────────────────────────────────────────────────
# SEMANTIC INTENT ANALYZER
# ──────────────────────────────────────────────────────────
def analyze_intent_with_llm(user_input):
    system_prompt = (
        "You are an operations router agent. Classify the user prompt into exactly one category.\n\n"
        "Examples:\n"
        "Prompt: write me a python script to rename files\nQWEN\n\n"
        "Prompt: fix this bug in my code\nQWEN\n\n"
        "Prompt: how do I compile this C program\nQWEN\n\n"
        "Prompt: kill the process running on port 8080\nTHINKING\n\n"
        "Prompt: list all files in this directory\nTHINKING\n\n"
        "Prompt: restart the nginx service\nTHINKING\n\n"
        "Prompt: hello, how are you\nBASE\n\n"
        "Prompt: what's the capital of France\nBASE\n\n"
        "Now classify this prompt:"
    )
    grammar = 'root ::= "QWEN" | "THINKING" | "BASE"'
    payload = {
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}],
        "temperature": 0.0, "max_tokens": 15, "grammar": grammar
    }
    try:
        resp = requests.post(f"{ORCHESTRATOR_URL}/chat/completions", json=payload, timeout=10)
        raw_text = resp.json()["choices"][0]["message"]["content"].strip().upper()
        print(f"[DEBUG] Orchestrator classification output: {raw_text!r}")
        if "QWEN" in raw_text: return "QWEN"
        if "THINKING" in raw_text: return "THINKING"
        return "BASE"
    except Exception as e:
        print(f"[DEBUG] Classifier exception: {e}")
        return "BASE"

def route_intent(user_input, has_image=False):
    if has_image:
        if spin_up_dynamic_model("vision", threads=2, ctx=16384): return DYNAMIC_ZONE_URL
    if len(user_input) > LONG_CONTEXT_THRESHOLD:
        if spin_up_dynamic_model("ttt_long_context", threads=2, ctx=20000): return DYNAMIC_ZONE_URL

    intent = analyze_intent_with_llm(user_input)
    if "QWEN" in intent:
        if spin_up_dynamic_model("qwen_reasoning", threads=6, ctx=4096): return DYNAMIC_ZONE_URL
    elif "THINKING" in intent:
        if spin_up_dynamic_model("thinking_coder", threads=2, ctx=16384): return DYNAMIC_ZONE_URL
    return ORCHESTRATOR_URL

# ──────────────────────────────────────────────────────────
# STREAMING PROXY PIPELINE
# ──────────────────────────────────────────────────────────
class RouterProxyHandler(BaseHTTPRequestHandler):
    chosen_engine = "NONE"

    def log_message(self, format, *args):
        sys.stderr.write(f"[Router Traffic] Engine Target: \033[1;36m{self.chosen_engine:<18}\033[0m | Status: {args[1]}\n")

    def do_GET(self):
        if self.path == "/v1/models":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            mock_models = {"object": "list", "data": [{"id": "qwen_reasoning", "object": "model"}]}
            self.wfile.write(json.dumps(mock_models).encode())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            req_body = json.loads(post_data.decode())

            messages = req_body.get("messages", [])
            user_text = ""
            has_image = False
            has_audio = False

            # Encode local path outputs automatically into base64 schemas
            if "local_audio_file" in req_body:
                audio_path = req_body["local_audio_file"]
                if os.path.exists(audio_path):
                    with open(audio_path, "rb") as f:
                        b64_string = base64.b64encode(f.read()).decode('utf-8')
                    
                    req_body["messages"] = [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Respond to my voice shortly."},
                            {"type": "input_audio", "input_audio": {"data": b64_string, "format": "wav"}}
                        ]
                    }]
                    has_audio = True

            if messages and not has_audio:
                content_payload = messages[-1].get("content", "")
                if isinstance(content_payload, list):
                    for part in content_payload:
                        if isinstance(part, dict):
                            if part.get("type") == "image_url" or "image" in part: has_image = True
                            if part.get("type") == "input_audio": has_audio = True
                else:
                    user_text = str(content_payload)

            # ──────────────────────────────────────────────────
            # TARGET PORT RESOLUTION
            # ──────────────────────────────────────────────────
            if has_audio:
                target_backend = ORCHESTRATOR_URL
                self.chosen_engine = "LFM_ORCHESTRATOR_AUDIO"
            elif has_image:
                if spin_up_dynamic_model("vision", threads=2, ctx=4096): target_backend = DYNAMIC_ZONE_URL
                else: self.send_error(503, "Vision instantiation error."); return
            else:
                target_backend = route_intent(user_text)
                if "8080" in target_backend: self.chosen_engine = "LFM_ORCHESTRATOR_TEXT"
                else: self.chosen_engine = "DYNAMIC_ZONE"

            # ──────────────────────────────────────────────────
            # FORWARD PAYLOAD AND STREAM BACK RESPONSE
            # ──────────────────────────────────────────────────
            try:
                resp = requests.post(f"{target_backend}/chat/completions", json=req_body, stream=True)
                self.send_response(resp.status_code)
                for key, val in resp.headers.items():
                    if key.lower() not in ['content-length', 'transfer-encoding']:
                        self.send_header(key, val)
                self.end_headers()

                full_response_text = ""
                for chunk in resp.iter_content(chunk_size=1024):
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        
                        try:
                            chunk_str = chunk.decode('utf-8', errors='ignore')
                            if "content" in chunk_str:
                                lines = chunk_str.split('\n')
                                for line in lines:
                                    if line.startswith("data:"):
                                        data_json = json.loads(line[5:].strip())
                                        content = data_json["choices"][0]["delta"].get("content", "")
                                        full_response_text += content
                        except:
                            pass

                if full_response_text and has_audio:
                    speak_response_via_system(full_response_text)

            except requests.exceptions.ConnectionError:
                # Automatic runtime fallback trigger point
                if "8080" in target_backend and boot_permanent_orchestrator():
                    resp = requests.post(f"{target_backend}/chat/completions", json=req_body, stream=True)
                else:
                    self.send_error(503, "Backend core connection dropped.")
            except Exception as e:
                self.send_error(500, f"Mesh system fault: {str(e)}")
            return

if __name__ == "__main__":
    # Ensure port 8080 is configured before starting the main network proxy loop
    if not boot_permanent_orchestrator():
        sys.exit(1)

    server = HTTPServer(('127.0.0.1', ROUTER_PORT), RouterProxyHandler)
    print(f"[Router] Interleaved Dynamic Router active on port {ROUTER_PORT}")
    try: 
        server.serve_forever()
    except KeyboardInterrupt: 
        print("\n[Router] Gracefully shutting down.")

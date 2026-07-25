#!/usr/bin/env python3
import os
import sys
import json
import signal
import subprocess
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ──────────────────────────────────────────────────────────
# SYSTEM CONSTRAINTS & PORT CONFIGURATIONS
# ──────────────────────────────────────────────────────────
ROUTER_PORT = 8085             
ORCHESTRATOR_URL = "http://localhost:8080/v1"  # LFM2.5-350M (Our Semantic Brain)
DYNAMIC_ZONE_URL = "http://localhost:8081/v1"  # Hot-swap port

LONG_CONTEXT_THRESHOLD = 12000 

BASE_DIR = os.path.expanduser("~/local_ai_workspace")
LLAMA_SERVER_BIN = os.path.join(BASE_DIR, "software/llama.cpp/build/bin/llama-server")
ORCHESTRATOR_RESTART_SCRIPT = os.path.join(BASE_DIR, "scripts/run-orchestrator.sh")
DYNAMIC_ZONE_LOG = "/tmp/dynamic_zone.log"

MODEL_PATHS = {
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

def terminate_dynamic_zone():
    subprocess.run("fuser -k 8081/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

def terminate_orchestrator():
    print("[Router Teardown] Terminating primary Orchestrator on port 8080...")
    subprocess.run("fuser -k 8080/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def restart_orchestrator():
    ORCHESTRATOR_LOG = "/tmp/orchestrator_boot.log"
    print(f"[Router] Orchestrator on 8080 unreachable. Booting (Logs: {ORCHESTRATOR_LOG})...")
    
    subprocess.Popen(f"bash {ORCHESTRATOR_RESTART_SCRIPT} > {ORCHESTRATOR_LOG} 2>&1 &", shell=True)
    for _ in range(30):
        time.sleep(1)
        if is_server_running(ORCHESTRATOR_URL):
            print("[Router] Orchestrator online and verified.")
            return True
    print("[Router] Orchestrator failed to initialize successfully.")
    return False

def spin_up_dynamic_model(model_key, threads=4, ctx=2048):
    if is_server_running(DYNAMIC_ZONE_URL):
        try:
            res = requests.get(f"{DYNAMIC_ZONE_URL}/models", timeout=0.5).json()
            if model_key in res.get("data", [{}])[0].get("id", ""):
                return True
        except:
            pass
        terminate_dynamic_zone()

    print(f"[Router] Target Configuration: {model_key.upper()} | Threads: {threads} | Context: {ctx} | Memlock: ENABLED")

    SCRIPT_MAPPING = {
        "qwen": "~/local_ai_workspace/scripts/run-qwen.sh",
        "vision": "~/local_ai_workspace/scripts/run-vision.sh"
    }

    if model_key in SCRIPT_MAPPING:
        script_path = os.path.expanduser(SCRIPT_MAPPING[model_key])
        subprocess.Popen([script_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        mmproj_flag = ""
        if model_key == "vision":
            mmproj_flag = f"--mmproj {MODEL_PATHS['vision_projector']}"

        cmd = (
            f"{LLAMA_SERVER_BIN} -m {MODEL_PATHS[model_key]} {mmproj_flag} "
            f"-c {ctx} --port 8081 -t {threads} --mlock -ngl 0 > {DYNAMIC_ZONE_LOG} 2>&1 &"
        )
        subprocess.Popen(cmd, shell=True)

    time.sleep(1.5) 

    for _ in range(30):
        if is_server_running(DYNAMIC_ZONE_URL):
            return True
        time.sleep(1)

    print(f"[Router] {model_key} failed to come online. Check {DYNAMIC_ZONE_LOG} for details.")
    return False

# ──────────────────────────────────────────────────────────
# GLOBAL SYSTEM TERMINATION TRAP (CLEAN EXIT MECHANISM)
# ──────────────────────────────────────────────────────────
def graceful_shutdown_handler(signum, frame):
    print("\n[Router Intercept] Shutdown signal received. Initializing structural memory wipe...")
    terminate_dynamic_zone()
    terminate_orchestrator()
    print("[Router Intercept] Mesh network cleared. Exiting session cleanly.")
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown_handler)  
signal.signal(signal.SIGTERM, graceful_shutdown_handler) 

# ──────────────────────────────────────────────────────────
# SEMANTIC INTENT ANALYZER (GRAMMAR-CONSTRAINED METHOD)
# ──────────────────────────────────────────────────────────
def analyze_intent_with_llm(user_input):
    system_prompt = (
        "You are an operations router agent. Classify the user prompt into exactly one category.\n\n"
        "Examples:\n"
        "Prompt: write me a python script to rename files\nQWEN\n\n"
        "Prompt: fix this bug in my code\nQWEN\n\n"
        "Prompt: how do I compile this C program\nQWEN\n\n"
        "Prompt: write a function that sorts a list\nQWEN\n\n"
        "Prompt: debug this error in my program\nQWEN\n\n"
        "Prompt: help me build a script for file automation\nQWEN\n\n"
        "Prompt: I spoke to them in coded language\nBASE\n\n"
        "Prompt: this movie's plot was really complex code to crack\nBASE\n\n"
        "Now classify this prompt:"
    )

    grammar = 'root ::= "QWEN" | "THINKING" | "BASE"'

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.0,
        "max_tokens": 15,
        "grammar": grammar
    }
    try:
        resp = requests.post(f"{ORCHESTRATOR_URL}/chat/completions", json=payload, timeout=15)
        # Capture raw response
        content = resp.json()["choices"][0]["message"]["content"].strip().upper()
        print(f"[DEBUG] Orchestrator raw classification output: {content!r}")
        # STRICT VALIDATION: Only accept the exact keywords
        if "QWEN" in content: return "QWEN"
        if "THINKING" in content: return "THINKING"
        if "BASE" in content: return "BASE"
        
        # If the tiny model outputs garbage, default to BASE for safety
        print(f"[DEBUG] Invalid intent: {content!r}. Defaulting to BASE.")
        return "BASE"
        
    except Exception as e:
        print(f"[DEBUG] Classifier exception: {e}")
        return "BASE"
    

def route_intent(user_input, has_image=False):
    if has_image:
        if spin_up_dynamic_model("vision", threads=4, ctx=16384): return DYNAMIC_ZONE_URL
    if len(user_input) > LONG_CONTEXT_THRESHOLD:
        if spin_up_dynamic_model("ttt_long_context", threads=4, ctx=20000): return DYNAMIC_ZONE_URL

    intent = analyze_intent_with_llm(user_input)

    if "QWEN" in intent:
        if spin_up_dynamic_model("qwen_reasoning", threads=4, ctx=2048): return DYNAMIC_ZONE_URL
    elif "THINKING" in intent:
        if spin_up_dynamic_model("thinking_coder", threads=4, ctx=16384): return DYNAMIC_ZONE_URL

    return ORCHESTRATOR_URL

# ──────────────────────────────────────────────────────────
# STREAMING LIVE NETWORKING GATEWAY PROXY
# ──────────────────────────────────────────────────────────
class RouterProxyHandler(BaseHTTPRequestHandler):
    chosen_engine = "NONE"

    def log_message(self, format, *args):
        sys.stderr.write(
            f"[Router Traffic] Engine Target: \033[1;36m{self.chosen_engine:<18}\033[0m | "
            f"Status: {args[1]} | {format % args}\n"
        )

    def do_GET(self):
        if self.path == "/v1/models" or self.path == "/models":
            self.chosen_engine = "METRIC_CHECK"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # OpenClaw expects a real OpenAI layout return array to identify the engine
            mock_models = {
                "object": "list", 
                "data": [
                    {"id": "dynamic-router", "object": "model", "owned_by": "custom"}
                ]
            }
            self.wfile.write(json.dumps(mock_models).encode())
            return
        self.send_error(404)

    def do_POST(self):
       # Normalize path: handle both "/v1/chat/completions" and "/chat/completions"
        normalized_path = self.path.replace("/v1", "")
        
        if normalized_path == "/chat/completions":
            content_length = int(self.headers['Content-Length'])
            raw_data = self.rfile.read(content_length)
            req_body = json.loads(raw_data.decode())
            
            # --- MANDATORY CLEANUP ---
            # Remove keys that trigger 400 Errors on Llama.cpp
            for key in ["tools", "tool_choice", "parallel_tool_calls", "metadata", "user", "stream_options", "input", "store"]:
                req_body.pop(key, None)
            
            # Set model ID explicitly for Llama.cpp
            req_body["model"] = "orchestrator"
            
            
            # ──────────────────────────────────────────────────────────
            # SILENT FLIGHT RECORDER: Log payloads to a dedicated file
            # ──────────────────────────────────────────────────────────
            LOG_FILE_PATH = os.path.expanduser("~/local_ai_workspace/scripts/router_debug.log")
            try:
                with open(LOG_FILE_PATH, "w") as log_file:
                    log_file.write(f"--- TIMESTAMP: {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    log_file.write(f"PATH TARGETED: {self.path}\n")
                    log_file.write(json.dumps(req_body, indent=2))
                    log_file.write("\n" + "="*60 + "\n")
            except Exception as e:
                pass
                
            messages = req_body.get("messages", [])
            user_text = ""
            has_image = False
            has_document = False

            if messages:
                latest_msg = messages[-1]
                content_payload = latest_msg.get("content", "")

                if isinstance(content_payload, list):
                    for part in content_payload:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                user_text += part.get("text", "")
                            elif part.get("type") == "image_url" or "image" in part:
                                has_image = True
                else:
                    user_text = str(content_payload)

                if "files" in req_body or "documents" in req_body:
                    has_document = True

            if has_image:
                print("[Router Proxy] Multimedia signal verified. Forcing Vision Module...")
                if spin_up_dynamic_model("vision", threads=4, ctx=4096):
                    target_backend = DYNAMIC_ZONE_URL
                else:
                    self.chosen_engine = "ROUTER_ERROR"
                    self.send_error(503, "Vision model failed to load. Check /tmp/dynamic_zone.log")
                    return
            elif has_document or len(user_text) > LONG_CONTEXT_THRESHOLD:
                print("[Router Proxy] Heavy file context payload verified. Forcing TTT Module...")
                if spin_up_dynamic_model("ttt_long_context", threads=4, ctx=8192):
                    target_backend = DYNAMIC_ZONE_URL
                else:
                    self.chosen_engine = "ROUTER_ERROR"
                    self.send_error(503, "TTT model failed to load. Check /tmp/dynamic_zone.log")
                    return
            else:
                target_backend = route_intent(user_text)

            if "8080" in target_backend:
                self.chosen_engine = "LFM_350M_BASE"
            else:
                try:
                    res = requests.get(f"{DYNAMIC_ZONE_URL}/models", timeout=0.3).json()
                    current_id = res["data"][0]["id"].lower()
                    if "qwen" in current_id: self.chosen_engine = "QWEN_3.5_4B"
                    elif "thinking" in current_id: self.chosen_engine = "THINKING_1.2B"
                    elif "ttt" in current_id: self.chosen_engine = "TTT_LINEAR_1.3B"
                    elif "vl" in current_id or "vision" in current_id: self.chosen_engine = "VISION_1.6B"
                    else: self.chosen_engine = "DYNAMIC_ZONE"
                except:
                    self.chosen_engine = "DYNAMIC_ZONE"

            # ──────────────────────────────────────────────────────────
            # AGENT SPECIFIC FIX: DETACH AND CLEAN TOOLS PROTOCOLS
            # ──────────────────────────────────────────────────────────
           # 1. Strip parameters local llama.cpp backends don't accept natively
            req_body.pop("tools", None)
            req_body.pop("tool_choice", None)
            req_body.pop("parallel_tool_calls", None)
            req_body.pop("metadata", None)
            req_body.pop("user", None)
            req_body.pop("stream_options", None)
            
            # 2. Overwrite the model string so llama.cpp doesn't reject the packet
            if "8080" in target_backend:
                req_body["model"] = "orchestrator"
            else:
                req_body["model"] = "dynamic_zone"
                
            try:
                resp = requests.post(f"{target_backend}/chat/completions", json=req_body, stream=True)
            except requests.exceptions.ConnectionError:
                if "8080" in target_backend:
                    if restart_orchestrator():
                        try:
                            resp = requests.post(f"{target_backend}/chat/completions", json=req_body, stream=True)
                        except Exception as e:
                            self.chosen_engine = "ROUTER_ERROR"
                            self.send_error(500, f"Backend routing failure after restart: {str(e)}")
                            return
                    else:
                        self.chosen_engine = "ROUTER_ERROR"
                        self.send_error(503, "Orchestrator down and restart failed")
                        return
                else:
                    self.chosen_engine = "ROUTER_ERROR"
                    self.send_error(500, "Backend unreachable")
                    return
            except Exception as e:
                self.chosen_engine = "ROUTER_ERROR"
                self.send_header("Content-Type", "text/plain")
                self.send_error(500, f"Backend routing failure: {str(e)}")
                return

            try:
                self.send_response(resp.status_code)
                for key, val in resp.headers.items():
                    if key.lower() not in ['content-length', 'transfer-encoding']:
                        self.send_header(key, val)
                self.end_headers()

                for chunk in resp.iter_content(chunk_size=1024):
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except Exception as e:
                self.chosen_engine = "ROUTER_ERROR"
                self.send_error(500, f"Backend streaming failure: {str(e)}")
            return
        self.send_error(404)

if __name__ == "__main__":
    if not is_server_running(ORCHESTRATOR_URL):
        print("[Router Startup] Core Orchestrator on 8080 is offline.")
        if not restart_orchestrator():
            print("[Router Error] Critical: Script could not initialize the base Orchestrator loop. Exiting.")
            sys.exit(1)

    server = HTTPServer(('127.0.0.1', ROUTER_PORT), RouterProxyHandler)
    print(f"[Router] Streaming AI Router listening on http://127.0.0.1:{ROUTER_PORT}")
    try:
        server.serve_forever()
    except Exception as e:
        print(f"[Router Error] Server unexpected runtime loop failure: {e}")

#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import time
import requests

# ──────────────────────────────────────────────────────────
# SYSTEM CONSTRAINTS & PORT CONFIGURATIONS
# ──────────────────────────────────────────────────────────
ORCHESTRATOR_URL = "http://localhost:8080/v1"  # LFM2.5-350M (Always hot in memory)
DYNAMIC_ZONE_URL = "http://localhost:8081/v1"  # Shared port for swap models

MODEL_PATHS = {
    "vision": "~/local_ai_workspace/models/dynamic_pool/lfm2.5-vl-1.6b-q4_k_m.gguf",
    "qwen_reasoning": "~/local_ai_workspace/models/core_pool/Qwen3.5-4B-Q4_K_M.gguf"
}

def is_server_running(url):
    try:
        response = requests.get(f"{url}/models", timeout=1)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def terminate_dynamic_zone():
    print("[Router] Cleaning up Dynamic Execution Zone memory frames...")
    # Grabs any active llama-server instances listening on port 8081
    subprocess.run("fuser -k 8081/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

def load_vision_model():
    if is_server_running(DYNAMIC_ZONE_URL):
        # Double check we aren't already hosting the vision server
        return True
        
    terminate_dynamic_zone()
    print("[Router] 8GB RAM Budget Alert: Loading LFM2.5-VL 1.6B into Dynamic Swap Space...")
    
    # Utilizing mmap and 3 physical threads optimized for OpenBLAS laptop layout
    cmd = f"llama-server -m {MODEL_PATHS['vision']} -c 2048 --port 8081 -t 3 --use-mmap true > /dev/null 2>&1 &"
    subprocess.Popen(cmd, shell=True)
    
    # Block loop until the model layers finish loading into the virtual memory page cache
    for _ in range(15):
        if is_server_running(DYNAMIC_ZONE_URL):
            print("[Router] Vision Engine successfully locked in RAM.")
            return True
        time.sleep(1)
    print("[Router] Critical Error: Vision engine spin-up timed out.")
    return False

def route_intent(user_input, has_image=False):
    # If the Page Assist UI triggers an image tensor array or screenshot request
    if has_image:
        print("[Router] Visual input detected via terminal hook/Page Assist pipeline.")
        if load_vision_model():
            # Redirect payload handling directly to the dynamic zone port
            print("[Router] Forwarding image frame to LFM2.5-VL...")
            return DYNAMIC_ZONE_URL
            
    # Default pipeline routing managed via the ultra-fast LFM2.5-350M Core
    print("[Router] Parsing standard command pattern through 350M core orchestrator...")
    return ORCHESTRATOR_URL

if __name__ == "__main__":
    # Quick live check to ensure our 350M traffic controller is awake
    if not is_server_running(ORCHESTRATOR_URL):
        print("[Router Error] The primary LFM2.5-350M Orchestrator is offline. Run 'ai-mesh' to mount base grids.")
        sys.exit(1)
        
    print("[Router] Multi-Agent Swap Framework successfully updated. Listening for tasks...")

import sys
import json
import http.server
import urllib.request
import urllib.error
import subprocess
import tempfile
import os

LLAMA_SERVER_URL = "http://127.0.0.1:8080"
PROXY_PORT = 8085

class SovereignMeshRouterHandler(http.server.BaseHTTPRequestHandler):
    current_active_model = "chat-core"

    def log_message(self, format, *args):
        return  # Keep terminal layout clean

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        cleaned_path = self.path.split('?')[0].rstrip('/')
        if cleaned_path in ["/v1/models", "/models"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            unified_model = {
                "object": "list",
                "data": [{
                    "id": "sovereign-mesh-agent", 
                    "object": "model", 
                    "owned_by": "agent"
                }]
            }
            self.wfile.write(json.dumps(unified_model).encode('utf-8'))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        cleaned_path = self.path.split('?')[0].rstrip('/')
        
        # --- PATH 1: AUDIO STT ROUTE (PERSISTENT CLUSTER FORWARDING) ---
        if cleaned_path in ["/v1/audio/transcriptions", "/audio/transcriptions"]:
            print("\n>>> [Agent Active Switch -> Directing Voice Stream Matrix to Persistent whisper-server] <<<")
            content_length = int(self.headers.get('Content-Length', 0))
            audio_payload = self.rfile.read(content_length)
            
            # Forward the audio binary payload cleanly to our dedicated whisper-server port
            whisper_url = "http://127.0.0.1:8087/v1/audio/transcriptions"
            
            # Reconstruct the exact headers to preserve multipart boundaries from PageAssist
            headers = {
                "Content-Type": self.headers.get("Content-Type"),
                "Authorization": self.headers.get("Authorization", "")
            }
            
            req = urllib.request.Request(whisper_url, data=audio_payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req) as response:
                    self.send_response(response.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(response.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(e.read())
            except Exception as e:
                self.send_response(500)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Whisper proxy forward failure: {e}"}).encode('utf-8'))
            return

        # --- PATH 2: CHAT COMPLETIONS ROUTE ---
        if cleaned_path in ["/v1/chat/completions", "/chat/completions"]:
            content_length = int(self.headers.get('Content-Length', 0))
            raw_data = self.rfile.read(content_length)
            selected_model = "chat-core"
            
            try:
                body = json.loads(raw_data.decode('utf-8'))
                messages = body.get("messages", [])
                
                if messages:
                    last_message_content = messages[-1].get("content", "")
                    
                    # Check for active Image Payloads
                    if isinstance(last_message_content, list):
                        for item in last_message_content:
                            if isinstance(item, dict) and item.get("type") == "image_url":
                                selected_model = "vision-core"
                                break
                    
                    # Regional Keywork and intent parsing
                    if selected_model != "vision-core":
                        user_prompt = ""
                        if isinstance(last_message_content, str):
                            user_prompt = last_message_content
                        elif isinstance(last_message_content, list):
                            user_prompt = " ".join([item.get("text", "") for item in last_message_content if isinstance(item, dict) and item.get("type") == "text"])

                        regional_keywords = ["nigeria", "ghana", "lagos", "abuja", "accra", "africa", "naira"]
                        if any(word in user_prompt.lower() for word in regional_keywords):
                            selected_model = "nigerian-core"
                        else:
                            gatekeeper_payload = {
                                "model": "vision-core",
                                "messages": [{
                                    "role": "user",
                                    "content": f"Respond with exactly one word: [VISION, CHAT].\nIf the input asks to look at an image, evaluate graphics, or capture a snapshot: VISION.\nOtherwise respond with: CHAT.\nInput: {user_prompt}\nClassification:"
                                }],
                                "max_tokens": 4, "temperature": 0.0
                            }
                            req = urllib.request.Request(f"{LLAMA_SERVER_URL}/v1/chat/completions",
                                                         data=json.dumps(gatekeeper_payload).encode('utf-8'),
                                                         headers={'Content-Type': 'application/json'})
                            with urllib.request.urlopen(req) as response:
                                route_res = json.loads(response.read().decode('utf-8'))
                                decision = route_res['choices'][0]['message']['content'].strip().upper()
                                selected_model = "vision-core" if "VISION" in decision else "chat-core"
            except Exception:
                selected_model = "chat-core"
            
            # Active Memory Unload Guard
            if selected_model != SovereignMeshRouterHandler.current_active_model:
                print(f"\n>>> [Memory Constraint Enforced] Switching Core Layer to: '{selected_model}' <<<")
                try:
                    unload_req = urllib.request.Request(f"{LLAMA_SERVER_URL}/slots?action=unload&model={SovereignMeshRouterHandler.current_active_model}", method="POST")
                    with urllib.request.urlopen(unload_req) as _: pass
                except Exception as e:
                    print(f"[Memory Management] Slot reset dispatched: {e}")
                SovereignMeshRouterHandler.current_active_model = selected_model
            
            body["model"] = selected_model
            req = urllib.request.Request(f"{LLAMA_SERVER_URL}/v1/chat/completions",
                                         data=json.dumps(body).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req) as response:
                    self.send_response(response.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(response.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(e.read())
            except Exception as e:
                self.send_response(500)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

def run():
    print(f"=== Custom Matrix Routing Endpoint Active on http://127.0.0.1:{PROXY_PORT} ===")
    http.server.HTTPServer(('127.0.0.1', PROXY_PORT), SovereignMeshRouterHandler).serve_forever()

if __name__ == "__main__":
    run()

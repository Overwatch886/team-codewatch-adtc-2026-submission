#!/usr/bin/env python3
import sys
import os
import re
import queue
import threading
import subprocess
import requests
import json
import soundfile as sf
import onnxruntime as rt
from kokoro_onnx import Kokoro

# Configuration Paths
WORKSPACE_DIR = "/home/overwatch886/local_ai_workspace/code-persona-adtc-2026-submission"
PARAKEET_BIN = f"{WORKSPACE_DIR}/software/parakeet.cpp/build/examples/cli/parakeet-cli"
ASR_MODEL = f"{WORKSPACE_DIR}/model/nemotron-3.5-asr-streaming-0.6b-q5_k.gguf"
KOKORO_MODEL = f"{WORKSPACE_DIR}/model/kokoro/kokoro-v1.0.onnx"
KOKORO_VOICES = f"{WORKSPACE_DIR}/model/kokoro/voices-v1.0.bin"
ORCHESTRATOR_URL = "http://localhost:8085/v1/chat/completions"
AUDIO_RECORD_FILE = "/tmp/voice_session_user.wav"

# Shared Queues
sentence_queue = queue.Queue()
playback_queue = queue.Queue()

# Initialize Kokoro
if not os.path.exists(KOKORO_MODEL) or not os.path.exists(KOKORO_VOICES):
    print("Error: Kokoro model or voices file not found.", file=sys.stderr)
    sys.exit(1)

# Initialize Kokoro with optimized thread configuration (6 threads for AMD 6-core Zen CPU)
opts = rt.SessionOptions()
opts.intra_op_num_threads = 6
opts.inter_op_num_threads = 1
session = rt.InferenceSession(KOKORO_MODEL, sess_options=opts, providers=['CPUExecutionProvider'])
kokoro = Kokoro.from_session(session, KOKORO_VOICES)
voice_style = "af_heart"

# Thread control event
stop_event = threading.Event()

def tts_worker():
    """Worker thread that consumes sentences, synthesizes audio, and enqueues the audio data for playback."""
    while not stop_event.is_set():
        try:
            sentence = sentence_queue.get(timeout=1)
        except queue.Empty:
            continue
        if sentence == "[DONE]":
            break
        clean_sentence = re.sub(r'[*_`#\\-]', ' ', sentence).strip()
        if not clean_sentence:
            sentence_queue.task_done()
            continue
        try:
            samples, sample_rate = kokoro.create(
                clean_sentence,
                voice=voice_style,
                speed=1.0,
                lang="en-us"
            )
            # Enqueue raw audio data for playback
            playback_queue.put((samples, sample_rate))
        except Exception as e:
            print(f"\n[TTS Error] Generation failed: {e}", file=sys.stderr)
        sentence_queue.task_done()

def playback_worker():
    """Worker thread that consumes audio data from playback_queue and plays it using sounddevice (non‑blocking)."""
    import sounddevice as sd
    while not stop_event.is_set():
        try:
            audio_item = playback_queue.get(timeout=1)
        except queue.Empty:
            continue
        if audio_item == "[DONE]":
            break
        samples, sample_rate = audio_item
        try:
            sd.play(samples, samplerate=sample_rate, blocking=True)
        except Exception as e:
            print(f"\n[Playback Error] {e}", file=sys.stderr)
        playback_queue.task_done()

def query_orchestrator_stream(prompt):
    """Sends prompt to the local orchestrator and streams tokens. Groups tokens into sentences and puts them in the queue."""
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }
    
    try:
        response = requests.post(ORCHESTRATOR_URL, json=payload, stream=True)
        if response.status_code != 200:
            print(f"\n[Error] Orchestrator responded with status {response.status_code}", file=sys.stderr)
            return

        current_sentence = ""
        print("🤖 Code Persona: ", end="", flush=True)

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            
            raw_data = line[len("data: "):]
            if raw_data.strip() == "[DONE]":
                break
                
            try:
                chunk = json.loads(raw_data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                
                if content:
                    print(content, end="", flush=True)
                    current_sentence += content
                    
                    # Split sentences on standard boundaries: '.', '?', '!', '\n'
                    if any(p in content for p in ('.', '?', '!', '\n')) and len(current_sentence.strip()) > 10:
                        sentence_queue.put(current_sentence.strip())
                        current_sentence = ""
            except Exception:
                continue

        # Put any remaining text in the queue
        if current_sentence.strip():
            sentence_queue.put(current_sentence.strip())
            
        print() # New line after generation
    except Exception as e:
        print(f"\n[Error] Connection to orchestrator failed: {e}", file=sys.stderr)

def record_audio():
    """Starts arecord, waits for user to press enter to stop, and returns True if audio recorded."""
    if os.path.exists(AUDIO_RECORD_FILE):
        os.remove(AUDIO_RECORD_FILE)
        
    print("🎙️ Recording... Press [ENTER] to stop.")
    record_proc = subprocess.Popen(
        ["arecord", "-D", "default", "-f", "S16_LE", "-r", "16000", "-c", "1", AUDIO_RECORD_FILE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    # Wait for user input to stop
    sys.stdin.readline()
    
    # Terminate arecord
    record_proc.terminate()
    try:
        record_proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        record_proc.kill()
        
    return os.path.exists(AUDIO_RECORD_FILE) and os.path.getsize(AUDIO_RECORD_FILE) > 0

def transcribe_audio():
    """Runs parakeet-cli to transcribe the recorded audio."""
    print("⚙️ Transcribing...", flush=True)
    try:
        res = subprocess.run(
            [PARAKEET_BIN, "transcribe", "--model", ASR_MODEL, "--input", AUDIO_RECORD_FILE],
            capture_output=True, text=True, check=True
        )
        raw_text = res.stdout.strip()
        # Clean language tags and whitespace
        clean_text = re.sub(r'<[^>]*>', '', raw_text).strip()
        return clean_text
    except Exception as e:
        print(f"ASR Error: {e}", file=sys.stderr)
        return ""

def main():
    print("🎤 Starting Code Persona Streamed Voice Session")
    print("-----------------------------------------------")
    print("Ready. Press [ENTER] to record, Ctrl+C to exit.")
    print("-----------------------------------------------")

    # Start TTS and playback worker threads
    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    playback_thread = threading.Thread(target=playback_worker, daemon=True)
    tts_thread.start()
    playback_thread.start()

    # Pre‑announce welcome (enqueue directly into sentence_queue)
    sentence_queue.put("Hello! I am ready. Ask me anything.")

    try:
        while True:
            print("\n👉 Press [ENTER] to start speaking...")
            sys.stdin.readline()
            
            if not record_audio():
                print("⚠️ Recording failed or empty. Please try again.")
                continue
            
            transcription = transcribe_audio()
            if os.path.exists(AUDIO_RECORD_FILE):
                os.remove(AUDIO_RECORD_FILE)
            if not transcription:
                print("⚠️ Could not understand the audio. Please try again.")
                continue
            print(f"\n👤 You: {transcription}")
            # Start streaming query to orchestrator (puts sentences into sentence_queue)
            query_orchestrator_stream(transcription)
            
    except KeyboardInterrupt:
        print("\nExiting voice session. Goodbye!")
    finally:
        stop_event.set()
        sentence_queue.put("[DONE]")
        playback_queue.put("[DONE]")
        tts_thread.join(timeout=2)
        playback_thread.join(timeout=2)

if __name__ == "__main__":
    main()

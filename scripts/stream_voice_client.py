#!/usr/bin/env python3
import sys, json, base64, subprocess, requests

AUDIO_FILE = sys.argv[1]
SAMPLE_RATE = 24000
BUFFER_CHUNKS = 30
BYTES_PER_SAMPLE = 4  # float32

with open(AUDIO_FILE, "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()

payload = {
    "messages": [
        {"role": "system", "content": "Respond with interleaved text and audio."},
        {"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}}
        ]}
    ],
    "stream": True,
    "max_tokens": 8192,
    "extra_body": {"reset_context": False}
}

player = subprocess.Popen(
    ["ffplay", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ch_layout", "mono",
     "-nodisp", "-i", "-"],
    stdin=subprocess.PIPE
)

pending = []
pipe_broke = False
total_bytes_written = 0

def flush_chunk(pcm_bytes):
    global pipe_broke, total_bytes_written
    try:
        player.stdin.write(pcm_bytes)
        player.stdin.flush()
        total_bytes_written += len(pcm_bytes)
    except BrokenPipeError:
        pipe_broke = True
        print(f"\n⚠️ pipe broke, ffplay exit code: {player.poll()}", flush=True)

print("🤖 ", end="", flush=True)
with requests.post("http://127.0.0.1:8087/v1/chat/completions", json=payload, stream=True) as r:
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: ") or pipe_broke:
            continue
        raw = line[len("data: "):]
        if raw.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(raw)
        except json.JSONDecodeError:
            continue
        delta = chunk.get("choices", [{}])[0].get("delta", {})
        if "content" in delta:
            print(delta["content"], end="", flush=True)
        if "audio_chunk" in delta:
            pcm_bytes = base64.b64decode(delta["audio_chunk"]["data"])
            pending.append(pcm_bytes)
            if len(pending) >= BUFFER_CHUNKS:
                for c in pending:
                    flush_chunk(c)
                pending.clear()

for c in pending:
    flush_chunk(c)

print()

if player.stdin and not pipe_broke:
    try:
        player.stdin.close()
    except BrokenPipeError:
        pass

# Give ffplay exactly as long as the audio actually runs, plus a little slack,
# then force it closed if it's still sitting there waiting for input.
audio_duration_sec = total_bytes_written / BYTES_PER_SAMPLE / SAMPLE_RATE
try:
    player.wait(timeout=audio_duration_sec + 2)
except subprocess.TimeoutExpired:
    player.terminate()
    try:
        player.wait(timeout=2)
    except subprocess.TimeoutExpired:
        player.kill()

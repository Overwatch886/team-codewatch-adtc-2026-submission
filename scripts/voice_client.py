#!/usr/bin/env python3
import sys, json, base64, subprocess, requests

AUDIO_FILE = sys.argv[1]
SAMPLE_RATE = 24000
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

print("🤖 (generating, please wait...) ", end="", flush=True)

all_audio = []
with requests.post("http://127.0.0.1:8087/v1/chat/completions", json=payload, stream=True) as r:
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
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
            all_audio.append(base64.b64decode(delta["audio_chunk"]["data"]))

print("\n🔊 playing full response...")

full_pcm = b"".join(all_audio)
player = subprocess.Popen(
    ["ffplay", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ch_layout", "mono",
     "-nodisp", "-autoexit", "-i", "-"],
    stdin=subprocess.PIPE
)
player.communicate(input=full_pcm)

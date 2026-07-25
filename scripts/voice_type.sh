#!/bin/bash
AUDIO_FILE="/tmp/system_voice_stream.wav"

# 1. Capture audio forcing 16kHz, Mono PCM
arecord -D default -f S16_LE -r 16000 -c 1 -d 4 "$AUDIO_FILE" 2>/dev/null

# 2. Stream to whisper-server's endpoint
TRANSCRIPT=$(curl -s -X POST "http://127.0.0.1:8087/inference" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@$AUDIO_FILE" \
  -F "response_format=json" | grep -oP '"text":\s*"\K[^"]+')

# 3. Inject text directly into the active textbox using Wayland-compatible wtype
if [ ! -z "$TRANSCRIPT" ] && [ "$TRANSCRIPT" != "null" ]; then
    # Strip leading spaces and type natively into the active cursor
    CLEAN_TEXT=$(echo "$TRANSCRIPT" | sed 's/^[ \t]*//')
    wtype "$CLEAN_TEXT"
fi

rm -f "$AUDIO_FILE"

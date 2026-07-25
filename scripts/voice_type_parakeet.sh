#!/bin/bash
AUDIO_FILE="/tmp/system_voice_stream.wav"
PID_FILE="/tmp/voice_type_parakeet.pid"

PARAKEET_BIN="/home/overwatch886/local_ai_workspace/software/parakeet.cpp/build/examples/cli/parakeet-cli"
ASR_MODEL="/home/overwatch886/local_ai_workspace/models/audio/SBPN_multilingual_large_q8_0.gguf"

if [ -f "$PID_FILE" ]; then
    # --- STOP RECORDING AND PROCESS ---
    PID=$(cat "$PID_FILE")
    rm -f "$PID_FILE"
    
    kill -2 "$PID" 2>/dev/null
    sleep 0.4

    if [ ! -s "$AUDIO_FILE" ]; then
        exit 1
    fi

    # 1. Transcribe audio to text
    RAW_TEXT=$("$PARAKEET_BIN" transcribe --model "$ASR_MODEL" --input "$AUDIO_FILE" 2>/dev/null | tr -d '\r\n')

    if [ ! -z "$RAW_TEXT" ]; then
        # 2. Scrub out <en-US> and trailing/leading whitespace
        CLEAN_TEXT=$(echo "$RAW_TEXT" | sed -E 's/<[^>]*>//g' | sed 's/^[ \t]*//;s/[ \t]*$//')
        
        if [ ! -z "$CLEAN_TEXT" ]; then
            # 3. Inject text natively via xdotool
            export DISPLAY=:0
            xdotool type "$CLEAN_TEXT "
        fi
    fi
    
    rm -f "$AUDIO_FILE"
else
    # --- START RECORDING ---
    echo -en "\a" # Single beep: listening
    rm -f "$AUDIO_FILE"
    arecord -D default -f S16_LE -r 16000 -c 1 "$AUDIO_FILE" 2>/dev/null &
    echo $! > "$PID_FILE"
fi

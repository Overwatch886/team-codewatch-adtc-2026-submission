#!/bin/bash
AUDIO_FILE="/tmp/system_voice_stream.wav"
PID_FILE="/tmp/voice_chat_record.pid"
JSON_PAYLOAD="/tmp/payload.json"
RAW_OUT="/tmp/server_raw.json"

if [ -f "$PID_FILE" ]; then
    # --- STOP RECORDING AND PROCESS ---
    PID=$(cat "$PID_FILE")
    rm -f "$PID_FILE"
    
    kill -2 "$PID" 2>/dev/null
    echo "Processing audio..."
    sleep 0.5

    if [ ! -s "$AUDIO_FILE" ]; then
        echo "❌ Recording file is empty!"
        /home/overwatch886/local_ai_workspace/scripts/speak.sh "Recording was empty."
        exit 1
    fi

    # 1. Safely build the massive JSON package inside a file instead of the command line
    echo -n '{"messages": [{"role": "user", "content": [{"type": "text", "text": "Respond to my voice shortly."}, {"type": "input_audio", "input_audio": {"data": "' > "$JSON_PAYLOAD"
    base64 -w 0 "$AUDIO_FILE" >> "$JSON_PAYLOAD"
    echo -n '", "format": "wav"}}]}], "temperature": 0.2}' >> "$JSON_PAYLOAD"

    # 2. Tell curl to pass the file directly (-d @filename). This never hits the argument limit!
    curl -s -X POST http://127.0.0.1:8087/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d @"$JSON_PAYLOAD" > "$RAW_OUT"

    # 3. Extract the text message response
    RESPONSE=$(cat "$RAW_OUT" | grep -oP '"content":\s*"\K[^"]+')

    if [ ! -z "$RESPONSE" ]; then
        echo -e "\n🤖 AI Response: $RESPONSE"
        /home/overwatch886/local_ai_workspace/scripts/speak.sh "$RESPONSE"
    else
        echo "❌ Server returned an error or unrecognized structure:"
        cat "$RAW_OUT"
        echo ""
        /home/overwatch886/local_ai_workspace/scripts/speak.sh "Error. Check terminal."
    fi
    
    # Clean up all temporary files
    rm -f "$AUDIO_FILE" "$JSON_PAYLOAD" "$RAW_OUT"
else
    # --- START RECORDING ---
    echo "Recording started..."
    /home/overwatch886/local_ai_workspace/scripts/speak.sh "Listening"
    arecord -D default -f S16_LE -r 16000 -c 1 "$AUDIO_FILE" 2>/dev/null &
    echo $! > "$PID_FILE"
fi

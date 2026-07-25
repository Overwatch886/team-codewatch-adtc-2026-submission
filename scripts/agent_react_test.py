import os
import re
import sys
import json
import subprocess
from openai import OpenAI

# 1. Connect to the local LiteLLM Proxy (which maps to VibeThinker-3B)
# Matches the configuration in scripts/orchestrator.py
client = OpenAI(
    api_key="sk-local-overwatch",
    base_url="http://127.0.0.1:8082/v1"
)

DEFAULT_CHAT_MODEL = "granite-tiny-core"
CHAT_MODEL = os.getenv("LITELLM_CHAT_MODEL", DEFAULT_CHAT_MODEL)

def execute_python_code(code_string: str) -> str:
    """Runs the provided Python code in a separate subprocess and captures output."""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code_string],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = ""
        if completed.stdout:
            output += completed.stdout
        if completed.stderr:
            if output:
                output += "\n"
            output += f"STDERR:\n{completed.stderr}"
        return output or "Success (no stdout/stderr)."
    except subprocess.TimeoutExpired:
        return "Error: Execution timed out (exceeded 30 seconds)."
    except Exception as e:
        return f"Error initiating execution: {str(e)}"

def run_agent(query: str, max_turns: int = 5):
    print("=" * 60)
    print(f"🚀 Starting ReAct Agent Loop for Query: {query!r}")
    print(f"Using Model: {CHAT_MODEL}")
    print("=" * 60)

    # VibeThinker is a reasoning model, so we instruct it to output thoughts first
    # and use standard python block syntax when it needs to interact with the environment.
    system_prompt = (
        "You are an expert Python coding assistant.\n"
        "To perform actions (such as reading/writing files or running commands), write a Python script in a ```python code block.\n"
        "Keep your internal thinking process extremely brief and direct, under 2 sentences.\n"
        "Once the task is complete, stop writing code blocks and summarize your results."
    )





    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    for turn in range(max_turns):
        print(f"\n[Turn {turn + 1} / {max_turns}] Generating response...", flush=True)
        try:
            response = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=2048,
                stream=True
            )
        except Exception as e:
            print(f"❌ API Call failed: {e}", flush=True)
            break

        print("-" * 40, flush=True)
        print("🤖 Assistant: ", end="", flush=True)
        content_chunks = []
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta is not None:
                print(delta, end="", flush=True)
                content_chunks.append(delta)
        print(flush=True)
        print("-" * 40, flush=True)
        content = "".join(content_chunks)


        # Append assistant response to history
        messages.append({"role": "assistant", "content": content})

        # Remove the <think>...</think> block before parsing code blocks
        clean_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

        # Check for Python code blocks in the cleaned content
        code_blocks = re.findall(r"```python\n(.*?)\n```", clean_content, re.DOTALL)
        
        if not code_blocks:
            print("\n✅ Agent decided to finish. Loop complete.", flush=True)
            break


        # Execute the first extracted code block
        code_to_run = code_blocks[0].strip()
        print(f"\n⚙️ Executing Python code block...")
        result = execute_python_code(code_to_run)
        print(f"📥 Execution Output:\n{result}")

        # Append execution feedback to history
        messages.append({
            "role": "user",
            "content": f"Execution Output:\n{result}"
        })

if __name__ == "__main__":
    test_query = "Write a file named 'hello_react.txt' containing 'Hello from the ReAct Agent!', then print the directory listing of the current directory to verify it."
    if len(sys.argv) > 1:
        test_query = " ".join(sys.argv[1:])
    run_agent(test_query)

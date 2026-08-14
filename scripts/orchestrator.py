import os
import re
import subprocess
import json
import sys
from typing import Dict, List, Tuple

# Ensure workspace is in python path to import acolbert
WORKSPACE_DIR = "/home/overwatch886/local_ai_workspace"
if WORKSPACE_DIR not in sys.path:
    sys.path.append(WORKSPACE_DIR)

import acolbert
import requests
from openai import OpenAI

ROUTER_URL = "http://127.0.0.1:5000/analyze"
RAG_URL = "http://127.0.0.1:8000/search"
RAG_TOP_K = 4
DEFAULT_MENTOR_MODEL = "granite-4.0-h-tiny"
EXPERT_CODE_MODEL = "granite-4.0-h-tiny"
CHAT_MODEL = os.getenv("LITELLM_CHAT_MODEL", DEFAULT_MENTOR_MODEL)
IMAGE_EXTENSION_PATTERN = re.compile(r"\.(png|jpe?g|webp|bmp|gif|tiff?)\b", re.IGNORECASE)
IMAGE_WORD_PATTERN = re.compile(r"\b(image|photo|picture|screenshot|diagram)\b", re.IGNORECASE)

LLAMA_CLI_BIN = os.getenv(
    "LLAMA_CLI_BIN",
    "/home/overwatch886/local_ai_workspace/software/llama.cpp/build/bin/llama-cli"
)
VISION_MODEL_PATH = os.getenv(
    "VISION_MODEL_PATH",
    "/home/overwatch886/local_ai_workspace/models/lnn/vision/LFM2.5-VL-1.6B-Q4_0.gguf"
)
VISION_MMPROJ_PATH = os.getenv(
    "VISION_MMPROJ_PATH",
    "/home/overwatch886/local_ai_workspace/models/lnn/vision/mmproj-LFM2.5-VL-1.6b-Q8_0.gguf"
)
VISION_CTX = int(os.getenv("VISION_CTX", "2048"))
VISION_THREADS = int(os.getenv("VISION_THREADS", "4"))
VISION_N_PREDICT = int(os.getenv("VISION_N_PREDICT", "256"))
VISION_DESC_MAX_CHARS = int(os.getenv("VISION_DESC_MAX_CHARS", "1500"))
VISION_TIMEOUT_SECONDS = int(os.getenv("VISION_TIMEOUT_SECONDS", "120"))

# Connect directly to llama.cpp (bypass LiteLLM — it adds overhead and is missing deps)
client = OpenAI(
    api_key="not-needed",
    base_url="http://127.0.0.1:8081/v1"
)

# Pre-encode intent descriptions using ColBERT
INTENT_DESCRIPTIONS = {
    "RAG": "The topic is about searching documentation, codebase retrieval, index search, and context lookup.",
    "VISION": "The topic is about describing images, analyzing photos, picture descriptions, and visual screenshots.",
    "CODE": "The topic is about writing code, programming, fixing bugs, scripting, and debugging.",
    "GENERAL": "The topic is about general conversation, questions, greetings, and chat."
}

encoded_intents = {}

def init_intent_embeddings():
    global encoded_intents
    if encoded_intents:
        return
    print("[Orchestrator] Pre-encoding ColBERT intent descriptions...")
    for intent, desc in INTENT_DESCRIPTIONS.items():
        encoded_intents[intent] = acolbert.encode(desc)
    print("[Orchestrator] Intent descriptions encoded successfully.")

def has_image_signal(text: str) -> bool:
    return bool(
        IMAGE_EXTENSION_PATTERN.search(text)
        or IMAGE_WORD_PATTERN.search(text)
    )

ALWAYS_KEEP_TOOLS = {
    "bash",
    "execute_command",
    "exec",
    "read",
    "write",
    "edit",
    "apply_patch",
    "web_search",
    "web_fetch"
}

def prune_tools_with_colbert(query: str, tools: List[Dict], top_k: int = 3) -> List[Dict]:
    if not tools:
        return tools
        
    try:
        init_intent_embeddings()
        
        query_vector = acolbert.encode(query)
        scored_tools = []
        
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            tool_text = f"Tool: {name}. Description: {desc}"
            
            tool_vector = acolbert.encode(tool_text)
            score = acolbert.maxsim(query_vector, tool_vector)
            scored_tools.append((score, tool))
            
        # Sort all tools by score descending
        scored_tools.sort(key=lambda x: x[0], reverse=True)
        
        # Get the top K most relevant tools
        top_k_tools = [item[1] for item in scored_tools[:top_k]]
        top_k_names = {t["function"]["name"] for t in top_k_tools}
        
        # Identify whitelisted tools present in the incoming payload
        always_kept = [t for t in tools if t.get("function", {}).get("name", "") in ALWAYS_KEEP_TOOLS]
        always_kept_names = {t["function"]["name"] for t in always_kept}
        
        # Dynamically append top-K tools that are not already in the whitelist
        dynamic_additions = [t for t in top_k_tools if t["function"]["name"] not in always_kept_names]
        
        # Combine whitelisted tools and dynamic additions
        final_tools = always_kept + dynamic_additions
        print(f"[Orchestrator] Pruned tools from {len(tools)} down to {len(final_tools)}. Whitelisted: {list(always_kept_names)}, Dynamic additions: {[t['function']['name'] for t in dynamic_additions]}")
        return final_tools
    except Exception as e:
        print(f"⚠️ Tool pruning failed: {e}. Returning original tool list.")
        return tools

def prune_system_prompt_with_colbert(query: str, system_content: str, max_additional_blocks: int = 6) -> str:
    if not system_content or len(system_content) < 4000:
        return system_content
        
    try:
        init_intent_embeddings()
        
        # Split system prompt by major headers (e.g. ## Workspace or ## System Info) or double newlines
        parts = re.split(r'\n(?=#+ )', system_content)
        if len(parts) <= 1:
            parts = system_content.split("\n\n")
            
        if len(parts) <= 2:
            return system_content
            
        # The first part is the core instructions/persona. We always keep it.
        core_persona = parts[0]
        candidate_blocks = parts[1:]
        
        query_vector = acolbert.encode(query)
        scored_blocks = []
        
        for block in candidate_blocks:
            if len(block.strip()) < 50:
                # Keep very short blocks as formatting/structure context
                scored_blocks.append((999.0, block))
                continue
                
            block_vector = acolbert.encode(block)
            score = acolbert.maxsim(query_vector, block_vector)
            scored_blocks.append((score, block))
            
        # Sort candidate blocks by score descending
        scored_blocks.sort(key=lambda x: x[0], reverse=True)
        
        # Keep the top blocks
        kept_blocks = []
        additional_count = 0
        for score, block in scored_blocks:
            if score == 999.0:
                kept_blocks.append(block)
            elif additional_count < max_additional_blocks:
                kept_blocks.append(block)
                additional_count += 1
                
        # Reconstruct system prompt keeping original block order for coherence
        final_blocks = [core_persona]
        for original_block in candidate_blocks:
            if original_block in kept_blocks:
                final_blocks.append(original_block)
                
        pruned_content = "\n".join(final_blocks)
        print(f"[Orchestrator] Pruned system prompt from {len(system_content)} chars down to {len(pruned_content)} chars.")
        return pruned_content
    except Exception as e:
        print(f"⚠️ System prompt pruning failed: {e}. Returning original system prompt.")
        return system_content

def analyze_query(query: str) -> Tuple[str, List[Dict[str, str]], Dict[str, float]]:
    try:
        init_intent_embeddings()
        
        # 1. Classify intent using ColBERT maxsim
        query_vector = acolbert.encode(query)
        
        scores = {}
        best_intent = "GENERAL"
        best_score = -9999.0
        
        # Gate vision: check if query contains image signal
        allowed_intents = ["VISION", "RAG", "CODE", "GENERAL"]
        image_signal = has_image_signal(query)
        if not image_signal:
            allowed_intents = [intent for intent in allowed_intents if intent != "VISION"]
            
        for intent in allowed_intents:
            doc_vector = encoded_intents[intent]
            score = acolbert.maxsim(query_vector, doc_vector)
            scores[intent] = score
            if score > best_score:
                best_score = score
                best_intent = intent
                
        print(f"[Orchestrator] Classified intent: {best_intent} | Scores: {scores}")
        
        # 2. Extract entities (file paths) via regex
        paths = re.findall(r'~?/[\w\.\-]+(?:/[\w\.\-]+)*', query)
        entities = [{"label": "FILE_PATH", "text": p} for p in paths]
        
        return best_intent, entities, scores
        
    except Exception as e:
        print(f"⚠️ ColBERT-based query routing failed: {e}. Falling back to GENERAL.")
        # Fallback regex extraction
        paths = re.findall(r'~?/[\w\.\-]+(?:/[\w\.\-]+)*', query)
        entities = [{"label": "FILE_PATH", "text": p} for p in paths]
        return "GENERAL", entities, {}


def read_file_content(path: str) -> str:
    path_lower = path.lower()
    if path_lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    # Clean control characters and PDF artifacts
                    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', page_text)
                    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
                    text_parts.append(cleaned.strip())
            parsed_text = "\n\n".join(text_parts)
            print(f"[Orchestrator] 📄 Parsed .pdf file ({len(parsed_text)} chars): {os.path.basename(path)}")
            return parsed_text
        except Exception as e:
            print(f"⚠️ Error parsing PDF file {path}: {e}")
            return ""
    elif path_lower.endswith(".docx"):
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(path) as z:
                xml_content = z.read('word/document.xml')
                tree = ET.fromstring(xml_content)
                paragraphs = []
                for p in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    texts = [node.text for node in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if node.text]
                    if texts:
                        paragraphs.append("".join(texts))
                print(f"[Orchestrator] 📄 Parsed .docx file ({len(paragraphs)} paragraphs): {os.path.basename(path)}")
                return "\n".join(paragraphs)
        except Exception as e:
            print(f"⚠️ Error parsing DOCX file {path}: {e}")
            return ""
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()


def build_file_context(entities: List[Dict[str, str]], query_text: str = "") -> str:
    prompt_context = ""
    MAX_DIRECT_CONTEXT_CHARS = 6000  # ~1500 tokens threshold

    def get_clean_doc_label(p: str) -> str:
        bname = os.path.basename(p)
        if bname.startswith("tmp") or "__" in bname:
            ext = os.path.splitext(bname)[1].lower().replace(".", "")
            ext_label = ext.upper() if ext else "FILE"
            return f"Uploaded Document ({ext_label})"
        return bname

    for entity in entities:
        raw_path = entity.get("text", "")
        path = os.path.expanduser(raw_path)
        if not path or not os.path.exists(path):
            continue

        doc_label = get_clean_doc_label(path)
        try:
            content = read_file_content(path)
            if not content:
                continue

            if len(content) <= MAX_DIRECT_CONTEXT_CHARS:
                print(f"[Orchestrator] 📄 Small file ({len(content)} chars): Direct context for {doc_label}")
                prompt_context += f"\n\n```document: {doc_label}\n{content.strip()}\n```\n"
            else:
                print(f"[Orchestrator] 📚 Large file ({len(content)} chars): ColBERT retrieval for {doc_label}")
                try:
                    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if workspace_dir not in sys.path:
                        sys.path.append(workspace_dir)
                    import acolbert
                    acolbert.index_file_on_the_fly(path, content)
                    rag_data = acolbert.local_search(query_text or "summarize key points", top_k=3, file_hints=[os.path.basename(path)])
                    rag_results = rag_data.get("results", [])
                    if rag_results:
                        prompt_context += f"\n\n[Attached Document Excerpts ({doc_label})]:\n"
                        for res in rag_results:
                            txt = res.get('text', '').strip()
                            if txt:
                                prompt_context += f"{txt}\n---\n"
                    else:
                        prompt_context += f"\n\n```document: {doc_label}\n{content[:MAX_DIRECT_CONTEXT_CHARS].strip()}\n```\n"
                except Exception as e:
                    print(f"⚠️ ColBERT indexing error: {e}. Falling back to preview.")
                    prompt_context += f"\n\n```document: {doc_label}\n{content[:MAX_DIRECT_CONTEXT_CHARS].strip()}\n```\n"
        except Exception as e:
            print(f"⚠️ Could not read file {path}: {e}")

    return prompt_context


def build_rag_context(query: str, entities: List[Dict[str, str]]) -> str:
    file_hints = [
        entity.get("text", "").strip()
        for entity in entities
        if entity.get("text")
    ]

    try:
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if workspace_dir not in sys.path:
            sys.path.append(workspace_dir)
        import acolbert
        
        rag_data = acolbert.local_search(query, top_k=RAG_TOP_K, file_hints=file_hints)
        rag_results = rag_data.get("results", [])
    except Exception as e:
        print(f"⚠️ Ephemeral ColBERT search failed: {e}")
        rag_results = []
        rag_data = {"message": f"Error loading index locally: {e}"}

    if not rag_results:
        return ""

    chunks = ["\n[Retrieved Reference Context]:\n"]
    for result in rag_results:
        source_file = os.path.basename(result.get('file', 'document'))
        text = result.get('text', '').strip()
        if text:
            chunks.append(f"```document: {source_file}\n{text}\n```")
    return "\n\n".join(chunks)


def extract_image_paths(
    text: str,
    entities: List[Dict[str, str]]
) -> List[str]:
    candidate_paths = re.findall(r'~?/[\w\.\-]+(?:/[\w\.\-]+)*', text)
    candidate_paths.extend(
        entity.get("text", "")
        for entity in entities
        if entity.get("text")
    )
    image_paths = []
    seen = set()
    for candidate in candidate_paths:
        expanded = os.path.expanduser(candidate)
        if (
            IMAGE_EXTENSION_PATTERN.search(expanded)
            and os.path.exists(expanded)
            and expanded not in seen
        ):
            image_paths.append(expanded)
            seen.add(expanded)
    return image_paths


def extract_text_file_entities(
    entities: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    text_entities = []
    for entity in entities:
        raw_path = entity.get("text", "")
        if not raw_path:
            continue
        expanded = os.path.expanduser(raw_path)
        if IMAGE_EXTENSION_PATTERN.search(expanded):
            continue
        text_entities.append(entity)
    return text_entities


def run_vision_cli_once(
    image_path: str,
    user_query: str
) -> str:
    prompt = (
        f"The user is asking: '{user_query}'. "
        "Analyze the provided image and extract ONLY the specific text, code snippets, error tracebacks, "
        "UI elements, or data required to answer this exact user question. "
        "Do not answer or solve the question yourself; strictly transcribe the relevant visual evidence."
    )

    env = dict(os.environ)
    env["GGML_VK_DISABLE"] = "1"
    env["GGML_VULKAN_DISABLE"] = "1"

    command = [
        LLAMA_CLI_BIN,
        "-m", VISION_MODEL_PATH,
        "--mmproj", VISION_MMPROJ_PATH,
        "--image", image_path,
        "-p", prompt,
        "-n", "256",
        "-c", "512",
        "-t", "2",
        "--single-turn",
        "--simple-io",
        "--no-display-prompt",
        "--jinja",
        "--mmap",
        "-ngl", "0"
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=VISION_TIMEOUT_SECONDS
    )

    stdout = completed.stdout
    clean_lines = []
    for line in stdout.splitlines():
        line_strip = line.strip()
        if not line_strip:
            continue
        if line_strip.startswith("llama_") or line_strip.startswith("system_info:") or line_strip.startswith("main:") or line_strip.startswith("load_"):
            continue
        if line_strip.startswith("[") and ("t/s" in line_strip or "tokens" in line_strip):
            continue
        if line_strip == "Exiting..." or line_strip.startswith("Log start"):
            continue
        clean_lines.append(line)

    description_clean = "\n".join(clean_lines).strip()
    return trim_to_sentence(
        description_clean,
        VISION_DESC_MAX_CHARS
    )


def trim_to_sentence(
    text: str,
    max_chars: int
) -> str:
    clean_text = " ".join(text.split())
    if len(clean_text) <= max_chars:
        return clean_text

    clipped = clean_text[:max_chars]
    sentence_end_positions = [
        clipped.rfind("."),
        clipped.rfind("!"),
        clipped.rfind("?")
    ]
    best_end = max(sentence_end_positions)

    if best_end > 60:
        return clipped[:best_end + 1].strip()
    return clipped.rstrip() + "..."


def run_vision_cli_directly(image_path: str, user_query: str):
    env = dict(os.environ)
    env["GGML_VK_DISABLE"] = "1"
    env["GGML_VULKAN_DISABLE"] = "1"

    command = [
        LLAMA_CLI_BIN,
        "-m", VISION_MODEL_PATH,
        "--mmproj", VISION_MMPROJ_PATH,
        "--image", image_path,
        "-p", user_query,
        "-n", "64",
        "-c", "512",
        "-t", "2",
        "--single-turn",
        "--simple-io",
        "--no-display-prompt",
        "--jinja",
        "--mmap",
        "-ngl", "0"
    ]
    subprocess.run(
        command,
        check=True,
        env=env,
        timeout=VISION_TIMEOUT_SECONDS
    )


def build_vision_context(query: str, image_paths: List[str]) -> str:
    descriptions = []

    for image_path in image_paths:
        description_text = run_vision_cli_once(
            image_path=image_path,
            user_query=query
        )
        descriptions.append(
            f"\n--- Vision Description ({image_path}) ---\n{description_text}\n"
        )
    return "\n".join(descriptions)

def is_complex_code_task(query_text: str) -> bool:
    query_lower = query_text.lower()
    
    # Heavy specialized complexity triggers requiring deep multi-file/compiler code specialization
    heavy_triggers = [
        "binary tree", "graph", "dynamic programming", "dijkstra",
        "rust", "assembly", "c++", "concurrency", "asyncio", "multi-thread",
        "sql cte", "partition by", "window function", "metaclass",
        "optimization", "leetcode", "human-eval"
    ]
    
    for trigger in heavy_triggers:
        if trigger in query_lower:
            return True
            
    # Very long code specifications or multi-file prompts (> 400 chars)
    if len(query_text) > 400 and ("code" in query_lower or "def " in query_lower or "class " in query_lower):
        return True
        
    # Everyday script debugging, syntax fixes, and standard code generation stay on Granite at 30 t/s!
    return False


def ask_pipeline(query: str):
    intent, entities, scores = analyze_query(query)
    image_paths = extract_image_paths(query, entities)
    text_entities = extract_text_file_entities(entities)

    if intent == "RAG":
        print("📂 Intent is RAG. Pulling retrieval chunks from ColBERT...")
        prompt_context = build_rag_context(query, entities)
    elif text_entities:
        print(f"📂 Intent is {intent}. Loading explicit file path context...")
        prompt_context = build_file_context(text_entities)
    else:
        prompt_context = ""

    if (intent == "VISION" or image_paths) and image_paths:
        print(f"🖼️ Vision flow active. Describing {len(image_paths)} image(s) first...")
        try:
            vision_context = build_vision_context(query, image_paths)
        except Exception as e:
            print(f"\n⚠️ Vision description failed: {e}. Proceeding without vision context.")
            vision_context = ""
    else:
        vision_context = ""

    score_text = ", ".join(
        f"{label}:{value:.4f}"
        for label, value in sorted(scores.items())
    ) or "n/a"

    final_prompt = f"""
You are a local AI assistant.
User Question: {query}

Detected Intent: {intent}
Intent Scores: {score_text}

Relevant Context:
{prompt_context if prompt_context else "No external context provided."}

Vision Context:
{vision_context if vision_context else "No vision context provided."}

Instructions:
- If context exists, use it first.
- If vision context exists, treat it as the image interpretation.
- If context is missing or incomplete, use your internal reasoning.
"""

    target_model = EXPERT_CODE_MODEL if intent == "CODE" else DEFAULT_MENTOR_MODEL
    print(f"🤖 Dispatching request to model target: {target_model}...")

    response = client.chat.completions.create(
        model=target_model,
        messages=[{"role": "user", "content": final_prompt}],
        stream=True
    )

    for chunk in response:
        if chunk.choices[0].delta.content is not None:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print("\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python scripts/orchestrator.py \"<your query>\""
        )
    ask_pipeline(" ".join(sys.argv[1:]))

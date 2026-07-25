import os
import json
import re
import ast
import numpy as np
import onnxruntime as ort
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer


# =====================================================
# CONFIG
# =====================================================

MODEL_DIR = "/home/overwatch886/local_ai_workspace/answerai-colbert-small-v1"
MODEL_FILE = "model_int8.onnx"

RETRIEVAL_DIR = "/home/overwatch886/local_ai_workspace/scripts"

INDEX_DIR = "/home/overwatch886/local_ai_workspace/colbert_index"

MAX_LENGTH = 256
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


os.makedirs(INDEX_DIR, exist_ok=True)


# =====================================================
# LOAD MODEL (LAZY INITIALIZATION)
# =====================================================

tokenizer = None
session = None

def load_model():
    global tokenizer, session
    if tokenizer is not None and session is not None:
        return

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_DIR
    )

    print("Loading ONNX model...")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 6
    options.inter_op_num_threads = 1

    session = ort.InferenceSession(
        os.path.join(
            MODEL_DIR,
            MODEL_FILE
        ),
        sess_options=options,
        providers=[
            "CPUExecutionProvider"
        ]
    )

    print("Model loaded")

    print("\nInputs:")
    for item in session.get_inputs():
        print(item.name, item.shape)

    print("\nOutputs:")
    for item in session.get_outputs():
        print(item.name, item.shape)




# =====================================================
# STORAGE
# =====================================================

documents = []
embeddings = []



# =====================================================
# FILE LOADING
# =====================================================

def extract_text_from_pdf(filepath):
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as e:
        print(f"Error reading PDF {filepath}: {e}")
        return ""

def load_directory(path):
    skip_extensions = {
        '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.ico',
        '.mp3', '.mp4', '.wav', '.avi', '.mov', '.flac', '.ogg', '.mkv',
        '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.xz',
        '.exe', '.dll', '.so', '.dylib', '.bin', '.out', '.app',
        '.pdf.lnk', '.desktop'
    }

    for root, _, files in os.walk(path):
        for filename in files:
            filepath = os.path.join(
                root,
                filename
            )

            _, ext = os.path.splitext(filename.lower())
            if ext in skip_extensions:
                continue

            try:
                text = ""
                if ext == ".pdf":
                    text = extract_text_from_pdf(filepath)
                else:
                    with open(
                        filepath,
                        "r",
                        encoding="utf-8",
                        errors="ignore"
                    ) as f:
                        text = f.read()

                if not text or len(text.strip()) == 0:
                    continue

                if filename.endswith(".py"):
                    chunk_records = chunk_python_code(
                        filepath,
                        text
                    )
                elif filename.endswith((".sh", ".bash")):
                    chunk_records = chunk_shell_code(
                        filepath,
                        text
                    )
                else:
                    chunk_records = [
                        {
                            "text": chunk_text
                        }
                        for chunk_text in split_text_with_overlap(
                            text,
                            CHUNK_SIZE,
                            CHUNK_OVERLAP
                        )
                    ]

                for chunk_record in chunk_records:
                    chunk_text = chunk_record["text"]
                    if len(chunk_text.strip()) <= 20:
                        continue

                    yield {
                        "file": filepath,
                        **chunk_record
                    }

            except Exception as e:
                print(
                    "Skipped:",
                    filepath,
                    e
                )


def split_text_with_overlap(
    text,
    chunk_size,
    overlap
):

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    if not text:
        return []

    chunks = []
    step = chunk_size - overlap

    for start in range(
        0,
        len(text),
        step
    ):
        chunk = text[start:start + chunk_size]
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(text):
            break

    return chunks


def chunk_python_code(
    filepath,
    text
):

    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    block_ranges = extract_python_top_level_ranges(
        filepath,
        text
    )

    if not block_ranges:
        return [
            {
                "text": chunk_text,
                "chunk_type": "text_window"
            }
            for chunk_text in split_text_with_overlap(
                text,
                CHUNK_SIZE,
                CHUNK_OVERLAP
            )
        ]

    records = []

    cursor_line = 1
    for start_line, end_line, symbol_name in block_ranges:
        if start_line > cursor_line:
            interstitial_text = "".join(lines[cursor_line - 1:start_line - 1])
            append_chunk_records(
                records=records,
                text=interstitial_text,
                base_record={
                    "chunk_type": "python_context",
                    "start_line": cursor_line,
                    "end_line": start_line - 1
                }
            )

        block_text = "".join(lines[start_line - 1:end_line])
        append_chunk_records(
            records=records,
            text=block_text,
            base_record={
                "chunk_type": "python_block",
                "symbol": symbol_name,
                "start_line": start_line,
                "end_line": end_line
            }
        )
        cursor_line = end_line + 1

    if cursor_line <= len(lines):
        tail_text = "".join(lines[cursor_line - 1:])
        append_chunk_records(
            records=records,
            text=tail_text,
            base_record={
                "chunk_type": "python_context",
                "start_line": cursor_line,
                "end_line": len(lines)
            }
        )

    return records


def extract_python_top_level_ranges(
    filepath,
    text
):

    try:
        tree = ast.parse(
            text,
            filename=filepath
        )
    except SyntaxError:
        return []

    ranges = []
    for node in tree.body:
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef
            )
        ):
            start_line = node.lineno
            decorator_list = getattr(node, "decorator_list", [])
            if decorator_list:
                start_line = min(
                    [start_line] + [decorator.lineno for decorator in decorator_list]
                )

            end_line = getattr(node, "end_lineno", None)
            if end_line is None:
                continue

            if isinstance(node, ast.ClassDef):
                symbol_name = f"class {node.name}"
            elif isinstance(node, ast.AsyncFunctionDef):
                symbol_name = f"async def {node.name}"
            else:
                symbol_name = f"def {node.name}"

            ranges.append(
                (
                    start_line,
                    end_line,
                    symbol_name
                )
            )

    ranges.sort(key=lambda item: item[0])
    return ranges


def append_chunk_records(
    records,
    text,
    base_record
):

    if not text.strip():
        return

    if len(text) <= CHUNK_SIZE:
        records.append(
            {
                "text": text,
                **base_record
            }
        )
        return

    sub_chunks = split_text_with_overlap(
        text,
        CHUNK_SIZE,
        CHUNK_OVERLAP
    )

    for sub_chunk_index, sub_chunk_text in enumerate(sub_chunks):
        records.append(
            {
                "text": sub_chunk_text,
                **base_record,
                "chunk_type": f"{base_record.get('chunk_type', 'chunk')}_window",
                "window_index": sub_chunk_index
            }
        )


def chunk_shell_code(
    filepath,
    text
):

    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    boundary_markers = []
    for idx, line in enumerate(lines):
        if re.match(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\))?\s*\{", line):
            function_match = re.match(
                r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\))?\s*\{",
                line
            )
            boundary_markers.append(
                (
                    idx,
                    {
                        "chunk_type": "shell_function",
                        "symbol": f"function {function_match.group(1)}"
                    }
                )
            )
        elif re.match(r"^\s*##\s+\S+", line) or re.match(r"^\s*#\s*[=-]{3,}", line):
            boundary_markers.append(
                (
                    idx,
                    {
                        "chunk_type": "shell_section"
                    }
                )
            )

    if not boundary_markers or boundary_markers[0][0] != 0:
        boundary_markers.insert(
            0,
            (
                0,
                {
                    "chunk_type": "shell_preamble"
                }
            )
        )

    deduped_markers = []
    seen_lines = set()
    for marker in sorted(boundary_markers, key=lambda item: item[0]):
        marker_line = marker[0]
        if marker_line in seen_lines:
            continue
        seen_lines.add(marker_line)
        deduped_markers.append(marker)

    records = []
    for marker_index in range(len(deduped_markers)):
        start_line_idx, marker_meta = deduped_markers[marker_index]
        if marker_index + 1 < len(deduped_markers):
            end_line_idx = deduped_markers[marker_index + 1][0]
        else:
            end_line_idx = len(lines)

        segment_text = "".join(lines[start_line_idx:end_line_idx])
        append_chunk_records(
            records=records,
            text=segment_text,
            base_record={
                **marker_meta,
                "start_line": start_line_idx + 1,
                "end_line": end_line_idx
            }
        )

    return records



# =====================================================
# COLBERT ENCODER
# =====================================================

def encode(text):
    load_model()

    tokens = tokenizer(
        text,
        padding="max_length",
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="np"
    )


    inputs = {
        "input_ids":
            tokens["input_ids"],

        "attention_mask":
            tokens["attention_mask"],

        "token_type_ids":
            tokens["token_type_ids"]
    }


    outputs = session.run(
        None,
        inputs
    )


    vectors = outputs[0][0]


    mask = tokens[
        "attention_mask"
    ][0]


    vectors = vectors[
        mask == 1
    ]


    vectors = vectors / (
        np.linalg.norm(
            vectors,
            axis=1,
            keepdims=True
        )
        + 1e-12
    )


    return vectors.astype(
        np.float32
    )



# =====================================================
# COLBERT MAXSIM
# =====================================================

def maxsim(
    query_vectors,
    document_vectors
):

    similarity = (
        query_vectors
        @
        document_vectors.T
    )


    scores = similarity.max(
        axis=1
    )


    return float(
        scores.sum()
    )



# =====================================================
# FASTAPI
# =====================================================

app = FastAPI()



class SearchRequest(BaseModel):

    query: str
    top_k: int = 5
    file_hints: List[str] = []



@app.get("/health")
def health():

    return {
        "status": "running",
        "indexed_chunks": len(documents)
    }



def append_embeddings_bin(filepath, emb_list):
    with open(filepath, "ab") as f:
        for emb in emb_list:
            n_tokens = emb.shape[0]
            f.write(np.int32(n_tokens).tobytes())
            f.write(emb.astype(np.float32).tobytes())

def load_embeddings_bin(filepath):
    emb_list = []
    if not os.path.exists(filepath):
        return emb_list
    with open(filepath, "rb") as f:
        while True:
            n_tokens_bytes = f.read(4)
            if not n_tokens_bytes:
                break
            n_tokens = np.frombuffer(n_tokens_bytes, dtype=np.int32)[0]
            data_bytes = f.read(n_tokens * 96 * 4)
            emb = np.frombuffer(data_bytes, dtype=np.float32).reshape((n_tokens, 96))
            emb_list.append(emb)
    return emb_list

@app.post("/index")
def build_index():
    global documents
    global embeddings

    documents = []
    embeddings = []

    print("Scanning:", RETRIEVAL_DIR)
    files = load_directory(RETRIEVAL_DIR)

    docs_path = os.path.join(INDEX_DIR, "documents.json")
    bin_embs_path = os.path.join(INDEX_DIR, "embeddings.bin")
    embs_path = os.path.join(INDEX_DIR, "embeddings.npy")

    # Clear old index files
    if os.path.exists(docs_path):
        os.remove(docs_path)
    if os.path.exists(bin_embs_path):
        os.remove(bin_embs_path)
    if os.path.exists(embs_path):
        os.remove(embs_path)

    batch_docs = []
    batch_embs = []
    BATCH_SIZE = 2000  # Stream to disk every 2000 chunks to protect memory bounds

    for idx, item in enumerate(files):
        if (idx + 1) % 100 == 0 or idx < 10:
            print(f"Embedding chunk {idx+1}...")
        vector = encode(item["text"])
        batch_docs.append(item)
        batch_embs.append(vector)

        if len(batch_docs) >= BATCH_SIZE:
            print(f"Writing batch of {len(batch_docs)} to disk...")
            all_docs = []
            if os.path.exists(docs_path):
                with open(docs_path, "r", encoding="utf-8") as f:
                    all_docs = json.load(f)
            all_docs.extend(batch_docs)
            with open(docs_path, "w", encoding="utf-8") as f:
                json.dump(all_docs, f, indent=2, ensure_ascii=False)

            append_embeddings_bin(bin_embs_path, batch_embs)
            batch_docs.clear()
            batch_embs.clear()

    if batch_docs:
        print(f"Writing final batch of {len(batch_docs)} to disk...")
        all_docs = []
        if os.path.exists(docs_path):
            with open(docs_path, "r", encoding="utf-8") as f:
                all_docs = json.load(f)
        all_docs.extend(batch_docs)
        with open(docs_path, "w", encoding="utf-8") as f:
            json.dump(all_docs, f, indent=2, ensure_ascii=False)

        append_embeddings_bin(bin_embs_path, batch_embs)
        batch_docs.clear()
        batch_embs.clear()

    load_index()

    return {
        "status": "saved",
        "chunks": len(documents),
        "index": INDEX_DIR
    }



@app.post("/search")
def search(
    request: SearchRequest
):

    if not embeddings:

        return {
            "error":
                "Index empty. Run /index first."
        }


    query_vector = encode(
        request.query
    )


    hints = [
        item.strip()
        for item in request.file_hints
        if item and item.strip()
    ]

    if hints:
        candidate_indices = [
            idx
            for idx, doc in enumerate(documents)
            if any(hint in doc["file"] for hint in hints)
        ]
    else:
        candidate_indices = list(range(len(documents)))

    if not candidate_indices:
        return {
            "query": request.query,
            "results": [],
            "message": "No indexed chunks matched provided file_hints."
        }

    results = []


    for idx in candidate_indices:

        doc_vector = embeddings[idx]

        score = maxsim(
            query_vector,
            doc_vector
        )


        results.append(
            {
                "score": score,

                "file":
                    documents[idx]["file"],

                "text":
                    documents[idx]["text"]
            }
        )


    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    return {

        "query":
            request.query,

        "results":

        [
            {
                "rank": i + 1,

                "score":
                    round(
                        item["score"],
                        4
                    ),

                "file":
                    item["file"],

                "text":
                    item["text"][:500]
            }

            for i, item in enumerate(
                results[:request.top_k]
            )
        ]

    }


def load_index():
    global documents, embeddings
    if documents and len(embeddings) > 0:
        return True
    docs_path = os.path.join(INDEX_DIR, "documents.json")
    embs_path = os.path.join(INDEX_DIR, "embeddings.npy")
    bin_embs_path = os.path.join(INDEX_DIR, "embeddings.bin")
    
    if os.path.exists(docs_path):
        print("Loading ColBERT index from disk...")
        try:
            with open(docs_path, "r", encoding="utf-8") as f:
                documents = json.load(f)
            
            if os.path.exists(bin_embs_path):
                embeddings = load_embeddings_bin(bin_embs_path)
            elif os.path.exists(embs_path):
                embeddings = list(np.load(embs_path, allow_pickle=True))
            
            print(f"Loaded {len(documents)} chunks from index.")
            return True
        except Exception as e:
            print(f"Failed to load index from disk: {e}")
    return False

def local_search(query: str, top_k: int = 5, file_hints: List[str] = []):
    load_index()
    if not embeddings:
        return {
            "error": "Index empty and no saved index found on disk."
        }
    query_vector = encode(query)

    hints = [
        item.strip()
        for item in file_hints
        if item and item.strip()
    ]

    if hints:
        candidate_indices = [
            idx
            for idx, doc in enumerate(documents)
            if any(hint in doc["file"] for hint in hints)
        ]
    else:
        candidate_indices = list(range(len(documents)))

    if not candidate_indices:
        return {
            "query": query,
            "results": [],
            "message": "No indexed chunks matched provided file_hints."
        }

    results = []
    for idx in candidate_indices:
        doc_vector = embeddings[idx]
        score = maxsim(query_vector, doc_vector)
        results.append({
            "score": score,
            "file": documents[idx]["file"],
            "text": documents[idx]["text"]
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": query,
        "results": [
            {
                "rank": i + 1,
                "score": round(item["score"], 4),
                "file": item["file"],
                "text": item["text"]
            }
            for i, item in enumerate(results[:top_k])
        ]
    }

def index_file_on_the_fly(path: str, content: str):
    load_model()
    load_index()
    global documents, embeddings
    
    if documents is None:
        documents = []
        
    filename = os.path.basename(path)
    existing = any(doc.get("file") == filename for doc in documents if isinstance(doc, dict))
    if existing:
        return
        
    print(f"[ColBERT] ⚡ On-The-Fly indexing large file: {filename}...")
    chunk_size = CHUNK_SIZE
    step = CHUNK_SIZE - CHUNK_OVERLAP
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), step if step > 0 else chunk_size)]
    if not chunks:
        return
        
    new_embeddings = []
    for chunk in chunks:
        emb = encode_document(chunk)
        documents.append({"file": filename, "text": chunk})
        new_embeddings.append(emb)
        
    if new_embeddings:
        if embeddings is None or len(embeddings) == 0:
            embeddings = np.array(new_embeddings, dtype=object)
        else:
            embeddings = list(embeddings) + new_embeddings
            
    print(f"[ColBERT] ✓ On-the-fly indexed {len(chunks)} chunks for {filename}.")


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":

    import uvicorn


    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )

import os
import json
import requests

# Hitting your native llama-server embedding engine on Port 8082
SERVER_URL = "http://127.0.0.1:8082/embeddings"
HEADERS = {"Content-Type": "application/json"}

def get_colbert_matrices_batched(texts_list):
    """Sends a batch of chunks to llama-server in a single network socket pass."""
    if not texts_list:
        return []
        
    # Standard llama-server accepts single strings or lists of strings natively
    payload = {"content": texts_list}
    try:
        response = requests.post(SERVER_URL, json=payload, headers=HEADERS)
        response.raise_for_status()
        result = response.json()
        
        # Unpack the list of embeddings returned by llama-server
        # Each item corresponds to the token matrix of a chunk
        return [item["embedding"] for item in result]
    except Exception as e:
        print(f"❌ Batch request failed: {e}. Falling back to single processing...")
        # Fallback to process one-by-one if the batch payload gets rejected
        fallback_list = []
        for t in texts_list:
            try:
                r = requests.post(SERVER_URL, json={"content": t}, headers=HEADERS)
                fallback_list.append(r.json()[0]["embedding"])
            except:
                fallback_list.append(None)
        return fallback_list

_HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = str(_HERE / "scripts")
output_file = str(_HERE / "colbert_index" / "index.json")
meta_file = str(_HERE / "colbert_index" / "index_meta.json")

# Load caches
if os.path.exists(output_file):
    with open(output_file, 'r') as f:
        try: index_db = json.load(f)
        except: index_db = {}
else:
    index_db = {}

if os.path.exists(meta_file):
    with open(meta_file, 'r') as f:
        try: file_meta = json.load(f)
        except: file_meta = {}
else:
    file_meta = {}

new_meta = {}
chunks_to_process = []
chunk_metadata = []
changes_made = False

print(f"🚀 Scanning workspace for folder updates: {SCRIPTS_DIR}")

for root, _, files in os.walk(SCRIPTS_DIR):
    for filename in files:
        if filename.endswith(('.py', '.sh', '.bash', '.json', '.ini')):
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, SCRIPTS_DIR)
            
            mtime = os.path.getmtime(full_path)
            new_meta[rel_path] = mtime
            
            # Skip completely matching synchronized files
            if rel_path in file_meta and file_meta[rel_path] == mtime:
                continue
                
            changes_made = True
            print(f"    Staging updated file: '{rel_path}'")
            
            # Scrub previous entries for this file
            keys_to_remove = [k for k in index_db.keys() if k.startswith(f"{rel_path}_chunk_")]
            for k in keys_to_remove:
                del index_db[k]
                
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            chunks = [content[i:i+600] for i in range(0, len(content), 400)]
            for idx, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                chunks_to_process.append(chunk)
                chunk_metadata.append({"rel_path": rel_path, "idx": idx, "text": chunk})

# Step 2: Fire chunks over the network interface in batches
BATCH_SIZE = 8  # Groups 8 code windows into a single network packet
if chunks_to_process:
    print(f"\n⚡ Batch computing embeddings for {len(chunks_to_process)} snippets over network...")
    for i in range(0, len(chunks_to_process), BATCH_SIZE):
        batch_texts = chunks_to_process[i:i+BATCH_SIZE]
        batch_meta = chunk_metadata[i:i+BATCH_SIZE]
        
        matrices = get_colbert_matrices_batched(batch_texts)
        
        for meta, matrix in zip(batch_meta, matrices):
            if matrix:
                chunk_id = f"{meta['rel_path']}_chunk_{meta['idx']}"
                index_db[chunk_id] = {
                    "file_name": meta["rel_path"],
                    "text": meta["text"],
                    "matrix": matrix
                }

if changes_made:
    with open(output_file, 'w') as f:
        json.dump(index_db, f)
    with open(meta_file, 'w') as f:
        json.dump(new_meta, f)
    print(f"\n✅ Synced! Deep index compilation complete. Total items stored: {len(index_db)}")
else:
    print("\n✨ Index completely synchronized. Zero changes detected.")

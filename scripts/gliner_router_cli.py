#!/usr/bin/env python3
import os
import sys
import json
import re
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

# Keep terminal clean
os.environ["ONNX_LOG_LEVEL"] = "3"

class LocalSemanticRouter:
    def __init__(self, model_dir):
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.encoder = ort.InferenceSession(
            os.path.join(model_dir, "encoder.onnx"),
            providers=["CPUExecutionProvider"]
        )

    def _encode_text(self, text):
        enc = self.tokenizer.encode(text)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)
        
        outputs = self.encoder.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask
        })
        last_hidden_state = outputs[0]
        
        mask_expanded = np.expand_dims(attention_mask, axis=-1)
        sum_embeddings = np.sum(last_hidden_state * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        mean_pooled = sum_embeddings / sum_mask
        
        norm = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
        return mean_pooled / norm

    def classify_intent(self, query, intents):
        query_vec = self._encode_text(query)
        best_intent = None
        best_score = -2.0
        results = {}
        
        for intent in intents:
            intent_vec = self._encode_text(f"The topic is about {intent.lower()}")
            score = np.dot(query_vec, intent_vec.T)[0][0]
            results[intent] = float(score)
            
            if score > best_score:
                best_score = score
                best_intent = intent
                
        return best_intent, results

IMAGE_EXTENSION_PATTERN = re.compile(r"\.(png|jpe?g|webp|bmp|gif|tiff?)\b", re.IGNORECASE)
IMAGE_WORD_PATTERN = re.compile(r"\b(image|photo|picture|screenshot|diagram)\b", re.IGNORECASE)

def has_image_signal(text: str) -> bool:
    return bool(
        IMAGE_EXTENSION_PATTERN.search(text)
        or IMAGE_WORD_PATTERN.search(text)
    )

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No query provided"}))
        sys.exit(1)
        
    query = sys.argv[1]
    intents = ["VISION", "RAG", "CODE", "GENERAL"]
    
    # 1. Gate vision
    allowed_intents = list(intents)
    image_signal = has_image_signal(query)
    if not image_signal:
        allowed_intents = [
            intent for intent in allowed_intents
            if str(intent).upper() != "VISION"
        ]
        
    if not allowed_intents:
        allowed_intents = ["GENERAL"]
        
    # 2. Run classification
    model_path = os.path.expanduser("~/local_ai_workspace/models/gliner2_quantized")
    router = LocalSemanticRouter(model_path)
    best_intent, scores = router.classify_intent(query, allowed_intents)
    
    # 3. Extract entities (file paths) via regex
    paths = re.findall(r'~?/[\w\.\-]+(?:/[\w\.\-]+)*', query)
    
    result = {
        "intent": best_intent,
        "scores": scores,
        "entities": [{"label": "FILE_PATH", "text": p} for p in paths]
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()

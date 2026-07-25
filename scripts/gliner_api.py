import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
import re
from fastapi import FastAPI
from pydantic import BaseModel

# Keep terminal clean
os.environ["ONNX_LOG_LEVEL"] = "3"

app = FastAPI(title="Overwatch Semantic Router")

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

# Initialize the router once on startup
print("🧠 Booting Custom ONNX Semantic Router API...")
model_path = os.path.expanduser("~/local_ai_workspace/models/gliner2_quantized")
router = LocalSemanticRouter(model_path)
print("✓ API active and listening on Port 5000!")

# Define the expected JSON payload
class QueryPayload(BaseModel):
    text: str
    intents: list


IMAGE_EXTENSION_PATTERN = re.compile(r"\.(png|jpe?g|webp|bmp|gif|tiff?)\b", re.IGNORECASE)
IMAGE_WORD_PATTERN = re.compile(r"\b(image|photo|picture|screenshot|diagram)\b", re.IGNORECASE)


def has_image_signal(text: str) -> bool:
    return bool(
        IMAGE_EXTENSION_PATTERN.search(text)
        or IMAGE_WORD_PATTERN.search(text)
    )


@app.post("/analyze")
def analyze(payload: QueryPayload):
    allowed_intents = list(payload.intents)
    image_signal = has_image_signal(payload.text)
    if not image_signal:
        allowed_intents = [
            intent for intent in allowed_intents
            if str(intent).upper() != "VISION"
        ]

    if not allowed_intents:
        allowed_intents = ["GENERAL"]

    # 1. Get Intent
    best_intent, scores = router.classify_intent(payload.text, allowed_intents)
    
    # 2. Get Entities (using your fast regex)
    # This keeps your setup modular: Semantic math for meaning, Regex for explicit paths.
    paths = re.findall(r'~?/[\w\.\-]+(?:/[\w\.\-]+)*', payload.text)
    
    return {
        "intent": best_intent,
        "scores": scores,
        "entities": [{"label": "FILE_PATH", "text": p} for p in paths]
    }

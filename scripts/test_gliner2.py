import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
import re

# Keep terminal clean
os.environ["ONNX_LOG_LEVEL"] = "3"

class LocalSemanticRouter:
    def __init__(self, model_dir):
        print("🧠 Booting Custom ONNX Semantic Router (Zero Downloads)...")
        
        # Load the tokenizer you already downloaded
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        
        # We only load the encoder brain you already downloaded
        self.encoder = ort.InferenceSession(
            os.path.join(model_dir, "encoder.onnx"),
            providers=["CPUExecutionProvider"]
        )
        print("✓ Local Encoder loaded into RAM.")

    def _encode_text(self, text):
        """Converts text into a mathematical vector representation."""
        # 1. Tokenize
        enc = self.tokenizer.encode(text)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)
        
        # 2. Extract deep representations from the encoder
        outputs = self.encoder.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask
        })
        last_hidden_state = outputs[0] # The raw output map
        
        # 3. Mean Pooling (Average the vectors together to get one single coordinate)
        mask_expanded = np.expand_dims(attention_mask, axis=-1)
        sum_embeddings = np.sum(last_hidden_state * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        mean_pooled = sum_embeddings / sum_mask
        
        # 4. Normalize the vector so we can measure distance cleanly
        norm = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
        return mean_pooled / norm

    def classify_intent(self, query, intents):
        """Measures which intent vector is closest to the query vector."""
        query_vec = self._encode_text(query)
        
        best_intent = None
        best_score = -2.0
        results = {}
        
        for intent in intents:
            # We add a tiny prompt to give the word more semantic weight
            intent_vec = self._encode_text(f"The topic is about {intent.lower()}")
            
            # The dot product of two normalized vectors gives us the Cosine Similarity
            score = np.dot(query_vec, intent_vec.T)[0][0]
            results[intent] = float(score)
            
            if score > best_score:
                best_score = score
                best_intent = intent
                
        return best_intent, results

if __name__ == "__main__":
    # Point this to the folder containing the files you already have
    model_dir = os.path.expanduser("~/local_ai_workspace/models/gliner2_quantized")
    
    router = LocalSemanticRouter(model_dir)
    
    # --- TEST PAYLOAD ---
    test_query = "Read my Python files in ~/workspace/RAG and explain the vector indexing logic."
    intents = ["CODE", "RAG", "GENERAL"]
    
    print(f"\n📥 Processing Query: '{test_query}'")
    
    # 1. Route the intent mathematically
    best_intent, scores = router.classify_intent(test_query, intents)
    
    print(f"\n🎯 Classified Intent: {best_intent}")
    print("📊 Similarity Scores:")
    for intent, score in scores.items():
        print(f"   - {intent}: {score:.4f}")

    # 2. Instant File Path Extraction
    # Since we dropped the heavy NER model, we use a simple regex for file paths.
    # For local OS directory routing, this is actually 100x faster and more accurate than a neural net.
    paths = re.findall(r'~?/[\w\.\-]+(?:/[\w\.\-]+)*', test_query)
    
    print("\n🏷️ Extracted Paths:")
    if paths:
        for path in paths:
            print(f"   - [FILE_PATH] : {path}")
    else:
        print("   - None found.")

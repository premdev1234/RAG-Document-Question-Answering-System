import os, logging, requests, numpy as np, re
from typing import List, Tuple, Optional, Dict, Any
import PyPDF2
from bs4 import BeautifulSoup
import nltk
from sentence_transformers import SentenceTransformer
import faiss
import pickle
from openai import OpenAI
import config
from typing import Optional


logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# Ensure tokenizer
try:
    nltk.data.find("tokenizers/punkt")
except:
    nltk.download("punkt")
client = OpenAI(api_key=config.OPENAI_API_KEY) if config.USE_OPENAI else None


# ================= VECTOR STORE =================
class VectorStore:
    def __init__(self, dim: int = 384):
        self.index = faiss.IndexFlatIP(dim)
        self.records: List[Dict[str, Any]] = []

    def add(self, chunks, embeddings, source, page=None):
        vecs = np.asarray(embeddings, dtype=np.float32)

        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)

        faiss.normalize_L2(vecs)
        self.index.add(vecs)  # type: ignore

        offset = len(self.records)
        for i, chunk in enumerate(chunks):
            self.records.append(
                {"text": chunk, "source": source, "page": page, "idx": offset + i}
            )

    def search(self, q_vec, top_k=3, threshold=0.4):
        if self.index.ntotal == 0:
            return []

        q = np.asarray(q_vec, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(q)

        scores, indices = self.index.search(q, int(top_k))  # type: ignore

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score >= threshold:
                results.append((self.records[idx], float(score)))

        return results

    def save(self, path="faiss.index"):
        faiss.write_index(self.index, path)
        with open(path + "_meta.pkl", "wb") as f:
            pickle.dump(self.records, f)

    def load(self, path="faiss.index"):
        if os.path.exists(path):
            self.index = faiss.read_index(path)

        meta_path = path + "_meta.pkl"
        if os.path.exists(meta_path):
            with open(meta_path, "rb") as f:
                self.records = pickle.load(f)

    def clear(self):
        self.index.reset()
        self.records.clear()

    @property
    def size(self):
        return self.index.ntotal


# ================= RAG PIPELINE =================
class RAGPipeline:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.store = VectorStore()
        self.store.load()  # 🔥 load existing data
        self.processed_sources = []
        self.chat_history = []

    # ---------- CLEAN ----------
    def clean_text(self, text):
        return re.sub(r"\s+", " ", text).strip()

    # ---------- BETTER CHUNKING ----------
    def chunk_text(self, text, chunk_size=500, overlap=100):
        sentences = nltk.sent_tokenize(text)
        chunks = []
        current_chunk = ""

        for sent in sentences:
            if len(current_chunk) + len(sent) <= chunk_size:
                current_chunk += " " + sent
            else:
                chunks.append(current_chunk.strip())

                overlap_text = current_chunk[-overlap:]
                current_chunk = overlap_text + " " + sent

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    # ---------- FILE INGEST ----------
    def ingest_file(self, path: str):
        source = os.path.basename(path)

        if path.endswith(".pdf"):
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)

                text_parts = []
                for p in reader.pages:
                    page_text = p.extract_text()
                    if page_text:
                        text_parts.append(page_text)

                text = " ".join(text_parts)
        elif path.endswith(".txt"):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            raise ValueError("Unsupported file type")

        text = self.clean_text(text)
        chunks = self.chunk_text(text)

        embeddings = self.model.encode(chunks, normalize_embeddings=True)
        self.store.add(chunks, np.array(embeddings), source)
        self.store.save()  # 🔥 persist

        self.processed_sources.append(source)
        return {"source": source, "chunks": len(chunks)}

    # ---------- URL INGEST ----------
    def ingest_url(self, url: str):
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        text = self.clean_text(soup.get_text())
        chunks = self.chunk_text(text)

        embeddings = self.model.encode(chunks, normalize_embeddings=True)
        self.store.add(chunks, np.array(embeddings), url)
        self.store.save()

        self.processed_sources.append(url)
        return {"source": url, "chunks": len(chunks)}

    def call_llm(self, prompt):
        try:
            if config.USE_OPENAI and client is not None:
                response = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30,
                )
                return response.choices[0].message.content
            else:
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": config.MODEL_NAME,
                        "prompt": prompt,
                        "stream": False,
                    },
                    timeout=30,
                )
                data = response.json()
                return data.get("response", "").strip() or "LLM returned empty response"
        except Exception as e:
            log.error(f"LLM Error: {e}")
            return "LLM unavailable. Please try again."

    # ===== ONLY CHANGED PART: answer() =====

    def answer(self, question: str, top_k: Optional[int] = None):
        if self.store.size == 0:
            return {"answer": "No documents uploaded.", "low_confidence": True}

        # Use config or UI-provided top_k
        if top_k is None:
            top_k = int(config.TOP_K)
        else:
            top_k = int(top_k)
        q_vec = self.model.encode([question], normalize_embeddings=True)[0]
        results = self.store.search(q_vec, top_k=top_k)

        if not results:
            return {
                "answer": "I could not find relevant information in the uploaded documents.",
                "low_confidence": True,
            }

        best_score = results[0][1]

        # 🔥 Confidence control
        if best_score < config.SIMILARITY_THRESHOLD:
            return {
                "answer": "Not found in documents.",
                "low_confidence": True,
                "sources": [],
            }

        # Build context
        context = "\n\n".join([r[0]["text"] for r in results])

        prompt = f"""
You are a strict AI assistant.

Answer ONLY using the provided context.
If the answer is not clearly present, say: "Not found in documents."

Do NOT guess.

Context:
{context}

Question:
{question}
"""

        answer = self.call_llm(prompt)

        # 🔥 Append sources (VERY IMPORTANT)
        sources_text = "\n\nSources:\n" + "\n".join(
            [f"- {r[0]['source']} (score: {round(r[1], 2)})" for r in results]
        )

        answer = str(answer) if answer else "LLM returned empty response"
        final_answer = answer.strip() + sources_text

        # Save chat history
        self.chat_history.append({"role": "user", "content": question})
        self.chat_history.append({"role": "assistant", "content": final_answer})

        return {
            "answer": final_answer,
            "low_confidence": False,
            "sources": [{"doc_name": r[0]["source"], "score": r[1]} for r in results],
        }

    def reset(self):
        self.store.clear()
        self.processed_sources.clear()
        self.chat_history.clear()

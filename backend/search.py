# search.py
# ---------
# When a user types "explain backpropagation", this file:
#   1. Optionally expands the query with synonyms ("backprop, gradient, weight update")
#   2. Converts the query into an embedding vector using the same model as ingestion
#   3. Asks ChromaDB for the 20 most similar chunks (first-pass, fast but approximate)
#   4. Runs a cross-encoder to precisely rescore those 20 candidates
#   5. Returns the top 5 results sorted by reranker score
#
# Two-stage retrieval (bi-encoder → cross-encoder) is the industry standard.
# First pass is fast (precomputed vectors), second pass is slow but precise
# and only runs on 20 candidates, not the entire database.

import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

# ── Load models (same instances as ingestion.py if imported from there) ───────
# In production you would share these via a module-level singleton.
# For clarity, we reload them here. In app.py we will import from ingestion.py.

EMBED_MODEL   = SentenceTransformer("all-MiniLM-L6-v2")

# CrossEncoder takes a (query, document) pair and outputs a relevance score.
# ms-marco-MiniLM-L-6-v2 is trained on Microsoft's MARCO dataset,
# which contains real search queries and their relevant passages.
RERANK_MODEL  = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

CHROMA_CLIENT = chromadb.PersistentClient(path="./chroma_store")
COLLECTION    = CHROMA_CLIENT.get_or_create_collection(
    name="yt_chunks",
    metadata={"hnsw:space": "cosine"}
)


def expand_query(query: str) -> str:
    """
    Simple query expansion: append a few related terms to the query.
    This increases the chance that the embedding captures related concepts.
    
    For a production system you'd use WordNet or an LLM for this.
    For now, we just return the query unchanged — the bi-encoder is
    already good enough without expansion for most queries.
    
    You can enhance this later.
    """
    return query  # placeholder for now


def seconds_to_timestamp(seconds: float) -> str:
    """
    Converts 3725.4 → "01:02:05"
    Converts 125.0  → "00:02:05"
    
    YouTube deep links use raw seconds (?t=3725),
    but we show the human-readable HH:MM:SS in the UI.
    """
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def search(query: str, video_id: str, top_k: int = 5) -> list:
    """
    Main search function.
    
    query    : what the user typed, e.g. "explain attention mechanism"
    video_id : the YouTube video ID (e.g. "dQw4w9WgXcQ")
               We filter ChromaDB to only search chunks from THIS video.
    top_k    : how many results to return (default 5)
    
    Returns a list of result dicts:
    [
      {
        "timestamp_display": "01:23:45",
        "start_seconds": 5025.0,
        "youtube_url": "https://youtube.com/watch?v=...&t=5025",
        "text": "...the attention mechanism works by...",
        "score": 0.91
      },
      ...
    ]
    """
    
    # Step 1: Expand the query (no-op for now, placeholder for improvement)
    expanded = expand_query(query)
    
    # Step 2: Embed the query using the bi-encoder
    # The result is a 384-dimensional vector, same space as our stored chunks.
    query_embedding = EMBED_MODEL.encode(expanded).tolist()
    
    # Step 3: First-pass retrieval — ask ChromaDB for top 20 candidates.
    # We retrieve 20 here (not 5) because the reranker will reorder them
    # and we want the reranker to have enough candidates to work with.
    #
    # where={"video_id": video_id} filters to only chunks from the requested video.
    # This is why we stored video_id in metadata during ingestion.
    
    first_pass_count = min(20, COLLECTION.count())  # can't ask for more than we have
    
    if first_pass_count == 0:
        return []  # database is empty
    
    results = COLLECTION.query(
        query_embeddings=[query_embedding],
        n_results=first_pass_count,
        where={"video_id": video_id},   # only search this video's chunks
        include=["documents", "metadatas", "distances"]
    )
    
    # COLLECTION.query returns nested lists (one per query embedding).
    # Since we only sent one query, we take index [0] from each.
    documents = results["documents"][0]   # list of chunk texts
    metadatas = results["metadatas"][0]   # list of metadata dicts
    distances = results["distances"][0]   # list of cosine distances (lower = more similar)
    
    if not documents:
        return []
    
    # Step 4: Cross-encoder reranking.
    # We create (query, chunk_text) pairs and the cross-encoder scores each pair.
    # Unlike the bi-encoder (which embeds query and document separately),
    # the cross-encoder reads BOTH together, so it understands their relationship
    # much more precisely. It's slower, but we only run it on 20 candidates.
    
    pairs = [(query, doc) for doc in documents]
    rerank_scores = RERANK_MODEL.predict(pairs)  # returns a list of floats
    
    # Step 5: Combine everything into result dicts and sort by reranker score.
    combined = []
    for i, (doc, meta, score) in enumerate(zip(documents, metadatas, rerank_scores)):
        combined.append({
            "text":              doc,
            "start_seconds":     meta["start"],
            "end_seconds":       meta["end"],
            "video_id":          meta["video_id"],
            "rerank_score":      float(score),
            "timestamp_display": seconds_to_timestamp(meta["start"]),
            "youtube_url":       f"https://www.youtube.com/watch?v={meta['video_id']}&t={int(meta['start'])}"
        })
    
    # Sort descending by reranker score (higher = more relevant)
    combined.sort(key=lambda x: x["rerank_score"], reverse=True)
    
    # Return only the top_k results
    return combined[:top_k]
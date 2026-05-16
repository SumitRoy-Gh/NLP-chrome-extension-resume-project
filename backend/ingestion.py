# ingestion.py
# ------------
# This file is responsible for processing a YouTube video from scratch.
# Given a URL, it:
#   1. Downloads just the audio track (not the full video — saves space/time)
#   2. Transcribes the audio using Whisper (speech → text with timestamps)
#   3. Splits the transcript into overlapping 30-second chunks (chunker.py)
#   4. Converts each chunk's text into a 384-dimension embedding vector
#   5. Stores every chunk (text + embedding + timestamp metadata) in ChromaDB

import os
import whisper
import yt_dlp
import chromadb
from sentence_transformers import SentenceTransformer
from chunker import make_chunks

# ── Load models once at import time ──────────────────────────────────────────
# Loading these is slow (several seconds). We load them once when the server
# starts, then reuse them for every request.

# Whisper "base" model is fast and accurate enough for most videos.
# Options in order of size/accuracy: tiny, base, small, medium, large-v3
# For a laptop, "base" or "small" is recommended.
print("Loading Whisper model...")
WHISPER_MODEL = whisper.load_model("base")

# This is the bi-encoder model. It converts a sentence into a 384-number vector.
# "all-MiniLM-L6-v2" is the best balance of speed and accuracy for this use case.
print("Loading embedding model...")
EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")

# ── Connect to ChromaDB ───────────────────────────────────────────────────────
# ChromaDB stores our vectors on disk in the "chroma_store" folder.
# Each time the server starts, it connects to the existing store (or creates it).
CHROMA_CLIENT = chromadb.PersistentClient(path="./chroma_store")

# A "collection" in ChromaDB is like a table in a database.
# get_or_create_collection: if it already exists, use it; otherwise create it.
COLLECTION = CHROMA_CLIENT.get_or_create_collection(
    name="yt_chunks",
    metadata={"hnsw:space": "cosine"}  # use cosine similarity for comparisons
)


def download_audio(youtube_url: str, output_path: str = "./temp_audio") -> str:
    """
    Downloads only the audio from a YouTube URL.
    Returns the path to the downloaded audio file.
    
    yt_dlp is a powerful YouTube downloader. We configure it to:
    - Download only audio (no video)
    - Convert to WAV format at 16kHz mono (exactly what Whisper needs)
    - Save to output_path
    """
    
    # ydl_opts is a dictionary of options for yt-dlp
    ydl_opts = {
        "format": "bestaudio/best",           # pick the best audio quality
        "outtmpl": f"{output_path}/%(id)s",   # save as {video_id}.wav
        "postprocessors": [{
            "key": "FFmpegExtractAudio",       # use ffmpeg to extract audio
            "preferredcodec": "wav",           # convert to WAV
        }],
        "postprocessor_args": [
            "-ar", "16000",   # sample rate: 16000 Hz (Whisper requirement)
            "-ac", "1",       # mono audio (1 channel)
        ],
        "quiet": True,        # don't print yt-dlp's own output
    }
    
    # Create the output folder if it doesn't exist
    os.makedirs(output_path, exist_ok=True)
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # Extract info first to get the video ID
        info = ydl.extract_info(youtube_url, download=True)
        video_id = info["id"]
    
    audio_file = f"{output_path}/{video_id}.wav"
    return audio_file, video_id


def transcribe_audio(audio_path: str) -> list:
    """
    Runs Whisper on the audio file.
    Returns a list of segments like:
    [{"start": 0.0, "end": 4.2, "text": "Hello everyone"}, ...]
    
    word_timestamps=True tells Whisper to give per-word timing,
    which makes our timestamp precision much better.
    """
    
    print(f"Transcribing {audio_path} ...")
    
    # Whisper's transcribe() does all the heavy lifting
    result = WHISPER_MODEL.transcribe(
        audio_path,
        word_timestamps=True,   # get precise per-word timing
        verbose=False           # don't print every segment
    )
    
    # result["segments"] is a list of dicts.
    # Each dict has: id, start, end, text, words (list of word-level timestamps)
    # We only need start, end, text for our chunking step.
    segments = [
        {"start": seg["start"], "end": seg["end"], "text": seg["text"]}
        for seg in result["segments"]
    ]
    
    return segments


def embed_chunks(chunks: list) -> list:
    """
    Takes a list of chunk dicts and adds an "embedding" key to each.
    The embedding is a list of 384 floats representing the chunk's meaning.
    
    We encode all chunks at once (batch encoding) — much faster than one by one.
    """
    
    # Extract just the text from each chunk for batch encoding
    texts = [chunk["text"] for chunk in chunks]
    
    # encode() returns a numpy array of shape (num_chunks, 384)
    # Each row is the embedding for one chunk
    embeddings = EMBED_MODEL.encode(texts, show_progress_bar=True)
    
    # Add the embedding back into each chunk dict
    for i, chunk in enumerate(chunks):
        chunk["embedding"] = embeddings[i].tolist()  # convert numpy array to plain list
    
    return chunks


def store_in_chromadb(chunks: list, video_id: str):
    """
    Stores all chunks in ChromaDB.
    
    ChromaDB needs three things per item:
    - ids       : unique string ID for each chunk
    - documents : the text of each chunk
    - embeddings: the vector for each chunk
    - metadatas : any extra info (we store video_id, start, end)
    """
    
    # Build the four lists ChromaDB expects
    ids         = [f"{video_id}_chunk_{i}" for i in range(len(chunks))]
    documents   = [chunk["text"] for chunk in chunks]
    embeddings  = [chunk["embedding"] for chunk in chunks]
    metadatas   = [
        {
            "video_id": video_id,
            "start":    chunk["start"],  # seconds (float)
            "end":      chunk["end"],
        }
        for chunk in chunks
    ]
    
    # upsert = insert if not exists, update if it does.
    # This means re-ingesting the same video is safe — it just overwrites.
    COLLECTION.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )
    
    print(f"Stored {len(chunks)} chunks for video {video_id}")


def ingest_video(youtube_url: str) -> dict:
    """
    Master function that runs the full ingestion pipeline:
    download → transcribe → chunk → embed → store
    
    Returns a summary dict with video_id and number of chunks created.
    """
    
    # Step 1: Download audio
    print("Downloading audio...")
    audio_path, video_id = download_audio(youtube_url)
    
    # Step 2: Transcribe with Whisper
    segments = transcribe_audio(audio_path)
    print(f"Got {len(segments)} transcript segments")
    
    # Step 3: Split into overlapping 30-second chunks
    chunks = make_chunks(segments, window_seconds=30, overlap_seconds=10)
    print(f"Created {len(chunks)} chunks")
    
    # Step 4: Generate embeddings for all chunks
    chunks = embed_chunks(chunks)
    
    # Step 5: Store everything in ChromaDB
    store_in_chromadb(chunks, video_id)
    
    # Clean up the audio file to save disk space
    if os.path.exists(audio_path):
        os.remove(audio_path)
    
    return {"video_id": video_id, "chunks": len(chunks)}
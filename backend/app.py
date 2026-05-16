# app.py
# ------
# The Flask web server. This is the entry point — you run "python app.py"
# to start the server. It exposes two endpoints:
#
#   POST /ingest   — body: {"url": "https://youtube.com/watch?v=..."}
#                    Downloads, transcribes, and stores the video.
#                    Returns: {"video_id": "...", "chunks": 42}
#
#   POST /search   — body: {"query": "attention mechanism", "video_id": "dQw4w9WgXcQ"}
#                    Searches for relevant timestamps.
#                    Returns: list of result dicts with timestamps
#
# flask_cors (CORS = Cross-Origin Resource Sharing) is required because
# the Chrome extension runs on a different "origin" than localhost:5000.
# Without CORS headers, the browser refuses to let the extension talk to Flask.

from flask import Flask, request, jsonify
from flask_cors import CORS
from ingestion import ingest_video, COLLECTION
from search import search as run_search

# Create the Flask app
app = Flask(__name__)

# Allow all origins (any Chrome extension can call this server).
# In production you'd restrict this to your extension's ID.
CORS(app)


@app.route("/ingest", methods=["POST"])
def ingest():
    """
    Endpoint: POST /ingest
    Body (JSON): {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    
    This will take several minutes for long videos (Whisper is slow).
    The extension should show a loading state while waiting.
    """
    
    # request.get_json() parses the JSON body sent by the extension
    data = request.get_json()
    
    # Validate that "url" was provided
    if not data or "url" not in data:
        # 400 = Bad Request
        return jsonify({"error": "Missing 'url' in request body"}), 400
    
    url = data["url"]
    
    try:
        # Run the full ingestion pipeline (this blocks until done)
        result = ingest_video(url)
        # 200 = OK
        return jsonify(result), 200
    except Exception as e:
        # 500 = Internal Server Error
        return jsonify({"error": str(e)}), 500


@app.route("/search", methods=["POST"])
def search():
    """
    Endpoint: POST /search
    Body (JSON): {"query": "explain attention", "video_id": "dQw4w9WgXcQ"}
    
    Returns a list of up to 5 results. If the video hasn't been ingested yet,
    returns an empty list with a message.
    """
    
    data = request.get_json()
    
    if not data or "query" not in data or "video_id" not in data:
        return jsonify({"error": "Missing 'query' or 'video_id'"}), 400
    
    query    = data["query"].strip()
    video_id = data["video_id"].strip()
    
    if not query:
        return jsonify({"error": "Query cannot be empty"}), 400
    
    # Check if this video has been ingested yet
    # We peek at ChromaDB to see if any chunks exist for this video_id
    try:
        existing = COLLECTION.get(where={"video_id": video_id}, limit=1)
        if not existing["ids"]:
            return jsonify({
                "results": [],
                "message": "Video not ingested yet. Please click 'Process Video' first."
            }), 200
    except Exception:
        pass  # If the check fails, proceed anyway and let search() handle it
    
    try:
        results = run_search(query, video_id, top_k=5)
        return jsonify({"results": results}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/status/<video_id>", methods=["GET"])
def status(video_id):
    """
    Endpoint: GET /status/<video_id>
    
    The extension calls this to check if a video has been ingested already.
    Returns {"ingested": true/false, "chunks": N}
    """
    try:
        result = COLLECTION.get(where={"video_id": video_id})
        count  = len(result["ids"])
        return jsonify({"ingested": count > 0, "chunks": count}), 200
    except Exception as e:
        return jsonify({"ingested": False, "chunks": 0}), 200


if __name__ == "__main__":
    # debug=True auto-reloads the server when you change a file
    # port=5000 is the default Flask port
    # host="127.0.0.1" means only your computer can access it (not the internet)
    print("Starting Flask server on http://localhost:5000")
    app.run(debug=True, port=5000, host="127.0.0.1")
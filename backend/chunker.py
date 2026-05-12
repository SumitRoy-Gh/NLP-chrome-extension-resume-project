# chunker.py
# ---------
# Whisper gives us segments like:
#   [{"start": 0.0, "end": 4.2, "text": "Hello everyone"},
#    {"start": 4.2, "end": 8.5, "text": "today we talk about NLP"}, ...]
#
# This file groups those small segments into bigger ~30-second chunks
# with a 10-second overlap between consecutive chunks.
# Overlap matters: if an explanation starts near the end of chunk 1,
# it also appears at the start of chunk 2, so it won't be missed.

def make_chunks(segments, window_seconds=30, overlap_seconds=10):
    """
    segments      : list of dicts from Whisper, each has 'start', 'end', 'text'
    window_seconds: how many seconds each chunk should cover
    overlap_seconds: how many seconds two consecutive chunks share
    
    Returns a list of dicts:
      [{"start": 0.0, "end": 30.0, "text": "combined text of all segments in window"}, ...]
    """
    
    if not segments:
        return []
    
    chunks = []
    
    # We slide a window across the transcript.
    # The window starts at chunk_start and ends at chunk_start + window_seconds.
    # After each chunk, we move forward by (window_seconds - overlap_seconds).
    # So for 30s window and 10s overlap, we move forward 20s each time.
    
    step = window_seconds - overlap_seconds  # = 20 seconds
    
    # Find the total duration of the video from the last segment's end time
    total_duration = segments[-1]["end"]
    
    chunk_start = 0.0
    
    while chunk_start < total_duration:
        chunk_end = chunk_start + window_seconds
        
        # Collect all segments whose start time falls within this window
        window_segments = [
            seg for seg in segments
            if seg["start"] >= chunk_start and seg["start"] < chunk_end
        ]
        
        if window_segments:
            # Join all the text from segments in this window into one string
            combined_text = " ".join(seg["text"].strip() for seg in window_segments)
            
            # The chunk starts at the first segment's actual start time
            actual_start = window_segments[0]["start"]
            actual_end   = window_segments[-1]["end"]
            
            chunks.append({
                "start": actual_start,
                "end":   actual_end,
                "text":  combined_text
            })
        
        chunk_start += step  # move the window forward
    
    return chunks
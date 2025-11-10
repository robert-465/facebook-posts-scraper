import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

def ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

def export_posts_to_json(posts: List[Dict[str, Any]], output_path: Path) -> None:
    """
    Write a list of post dictionaries to a JSON file with pretty formatting.
    """
    ensure_parent_dir(output_path)
    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
        logger.info("Exported %d post(s) to %s", len(posts), output_path)
    except OSError as exc:
        logger.error("Failed to write JSON output to %s: %s", output_path, exc)
        raise

def export_posts_to_ndjson(posts: List[Dict[str, Any]], output_path: Path) -> None:
    """
    Optionally export posts as newline-delimited JSON (one JSON object per line).
    """
    ensure_parent_dir(output_path)
    try:
        with output_path.open("w", encoding="utf-8") as f:
            for post in posts:
                f.write(json.dumps(post, ensure_ascii=False) + "\n")
        logger.info("Exported %d post(s) to NDJSON file %s", len(posts), output_path)
    except OSError as exc:
        logger.error("Failed to write NDJSON output to %s: %s", output_path, exc)
        raise
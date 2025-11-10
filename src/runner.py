import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional

from extractors.facebook_parser import FacebookPostsScraper
from outputs.exporters import export_posts_to_json
from configparser import ConfigParser  # not used but kept for potential extension

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_FILE = ROOT_DIR / "data" / "inputs.sample.txt"
DEFAULT_OUTPUT_FILE = ROOT_DIR / "data" / "sample.json"
DEFAULT_CONFIG_FILE = ROOT_DIR / "src" / "config" / "settings.example.json"

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logging.warning("Settings file %s not found, falling back to built-in defaults.", path)
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        logging.info("Loaded settings from %s", path)
        return data
    except json.JSONDecodeError as exc:
        logging.error("Failed to parse settings JSON at %s: %s", path, exc)
        return {}

def read_input_urls(path: Path) -> List[str]:
    if not path.exists():
        logging.error("Input file %s does not exist.", path)
        return []

    urls: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)

    if not urls:
        logging.warning("No URLs found in %s", path)
    else:
        logging.info("Loaded %d URL(s) from %s", len(urls), path)
    return urls

def build_scraper_from_settings(settings: Dict[str, Any]) -> FacebookPostsScraper:
    request_settings = settings.get("request", {})
    scraper_settings = settings.get("scraper", {})
    proxy_settings = settings.get("proxy", {})

    timeout = float(request_settings.get("timeout", 10.0))
    max_retries = int(request_settings.get("max_retries", 3))
    backoff_factor = float(request_settings.get("backoff_factor", 0.5))

    user_agent = str(scraper_settings.get("user_agent", "")).strip() or FacebookPostsScraper.DEFAULT_USER_AGENT

    proxies: Optional[Dict[str, str]] = None
    if proxy_settings:
        proxies = {
            k: v
            for k, v in proxy_settings.items()
            if isinstance(v, str) and v.strip()
        } or None

    return FacebookPostsScraper(
        timeout=timeout,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        user_agent=user_agent,
        proxies=proxies,
    )

def scrape_urls(
    scraper: FacebookPostsScraper,
    urls: List[str],
    max_workers: int = 4,
) -> List[Dict[str, Any]]:
    logger = logging.getLogger("runner.scrape_urls")
    results: List[Dict[str, Any]] = []
    if not urls:
        return results

    logger.info("Starting scrape of %d URL(s) with %d worker(s).", len(urls), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(scraper.fetch_and_parse, url): url for url in urls
        }

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                posts = future.result()
                if posts:
                    results.extend(posts)
                    logger.info("Parsed %d post(s) from %s", len(posts), url)
                else:
                    logger.warning("No posts parsed from %s", url)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error while scraping %s: %s", url, exc)

    logger.info("Finished scraping. Total posts parsed: %d", len(results))
    return results

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape public Facebook post data into structured JSON."
    )
    parser.add_argument(
        "--input-file",
        type=str,
        default=str(DEFAULT_INPUT_FILE),
        help=f"Path to text file with one Facebook URL per line (default: {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=str(DEFAULT_OUTPUT_FILE),
        help=f"Path to write JSON output (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--config-file",
        type=str,
        default=str(DEFAULT_CONFIG_FILE),
        help=f"Path to scraper settings JSON (default: {DEFAULT_CONFIG_FILE})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent workers to use when scraping.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging.",
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)

    input_file = Path(args.input_file)
    output_file = Path(args.output_file)
    config_file = Path(args.config_file)

    settings = load_settings(config_file)
    scraper = build_scraper_from_settings(settings)

    urls = read_input_urls(input_file)
    if not urls:
        logging.error("No URLs to process. Exiting.")
        return

    scraper_settings = settings.get("scraper", {})
    max_workers = int(scraper_settings.get("concurrency", args.workers))

    posts = scrape_urls(scraper, urls, max_workers=max_workers)

    if not posts:
        logging.warning("No posts were scraped. Output file will contain an empty list.")

    export_posts_to_json(posts, output_file)
    logging.info("Done. Output written to %s", output_file)

if __name__ == "__main__":
    main()
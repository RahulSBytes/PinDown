"""
╔══════════════════════════════════════════════════════════╗
║          Pinterest Downloader (Pins + Boards)            ║
║   Download images/videos from pins or entire boards      ║
╚══════════════════════════════════════════════════════════╝

Usage:
    python pinterest_downloader.py

Dependencies:
    pip install requests beautifulsoup4 lxml
"""

import os
import re
import sys
import json
import time
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

# ─── COLORS ───────────────────────────────────────────────
class C:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    MAGENTA= "\033[95m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

# ─── CONFIG ───────────────────────────────────────────────
DOWNLOAD_DIR = "pinterest_downloads"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.pinterest.com/",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-AppState": "active",
    "X-APP-VERSION": "cf34770",
}

session = requests.Session()
session.headers.update(HEADERS)


# ─── UTILITIES ────────────────────────────────────────────
def banner():
    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║              📌 Pinterest Downloader v2.0                    ║
║          Download Pins, Images, Videos & Full Boards         ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}

{C.YELLOW}Supported inputs:{C.RESET}
  {C.GREEN}• Single pin:{C.RESET}    https://www.pinterest.com/pin/123456789
  {C.GREEN}• Short pin:{C.RESET}     https://pin.it/abc123
  {C.GREEN}• Multiple pins:{C.RESET} url1, url2, url3
  {C.GREEN}• Board URL:{C.RESET}     https://www.pinterest.com/username/board-name/
  {C.GREEN}• Multiple boards + pins mixed:{C.RESET} board_url, pin_url, board_url2

{C.DIM}Files are saved to: ./{DOWNLOAD_DIR}/{C.RESET}
""")


def progress_bar(current, total, prefix="", bar_len=40):
    if total == 0:
        return
    frac = current / total
    filled = int(bar_len * frac)
    bar = "█" * filled + "░" * (bar_len - filled)
    mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)
    sys.stdout.write(f"\r  {prefix} |{C.CYAN}{bar}{C.RESET}| {frac*100:5.1f}% ({mb:.1f}/{total_mb:.1f} MB)")
    sys.stdout.flush()


def safe_filename(name, ext="jpg"):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name[:100].strip('. ')
    return f"{name}.{ext}" if name else f"download_{int(time.time())}.{ext}"


def resolve_short_url(url):
    """Resolve pin.it short URLs"""
    if "pin.it" in url:
        try:
            print(f"  {C.DIM}Resolving short URL...{C.RESET}")
            resp = session.head(url, allow_redirects=True, timeout=15)
            url = resp.url
            print(f"  {C.DIM}→ {url}{C.RESET}")
        except Exception as e:
            print(f"  {C.RED}Failed to resolve short URL: {e}{C.RESET}")
    return url


def detect_url_type(url):
    """Detect if URL is a pin, board, or unknown"""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if "pin.it" in parsed.netloc:
        return "pin"

    if not parsed.netloc or "pinterest" not in parsed.netloc:
        return "unknown"

    # Pin URL: /pin/123456...
    if re.match(r'^pin/\d+', path):
        return "pin"

    # Board URL: /username/boardname/ (2 segments, not a special page)
    special_pages = {"ideas", "search", "settings", "notifications",
                     "business", "password", "_", "pin", "today",
                     "categories", "topics", "explore"}
    segments = [s for s in path.split("/") if s]

    if len(segments) >= 2 and segments[0].lower() not in special_pages:
        return "board"

    return "unknown"


# ─── PINTEREST INIT (GET COOKIES + CSRFTOKEN) ────────────
def init_pinterest_session():
    """Visit Pinterest homepage to grab cookies & CSRF token"""
    try:
        resp = session.get("https://www.pinterest.com/", timeout=15)
        csrf = session.cookies.get("csrftoken", "")
        if csrf:
            session.headers["X-CSRFToken"] = csrf
        return True
    except Exception as e:
        print(f"{C.YELLOW}⚠ Could not initialize session: {e}{C.RESET}")
        return False


# ─── SINGLE PIN DOWNLOAD ─────────────────────────────────
def extract_media_from_pin(url):
    """Extract the best media URL from a single pin page"""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        media = {"type": None, "url": None, "title": ""}

        # ── Method 1: JSON-LD ──
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "VideoObject":
                        vid_url = item.get("contentUrl") or item.get("embedUrl")
                        if vid_url:
                            media = {"type": "video", "url": vid_url,
                                     "title": item.get("name", "")}
                            return media
                    if item.get("@type") == "ImageObject":
                        img_url = item.get("contentUrl") or item.get("url")
                        if img_url:
                            media = {"type": "image", "url": img_url,
                                     "title": item.get("name", "")}
            except json.JSONDecodeError:
                pass

        # ── Method 2: Parse __PWS_DATA__ or initial state JSON ──
        for script in soup.find_all("script", id="__PWS_DATA__"):
            try:
                data = json.loads(script.string)
                media = _dig_pin_from_pws(data)
                if media and media["url"]:
                    return media
            except:
                pass

        # Search all scripts for big JSON blobs
        for script in soup.find_all("script"):
            if not script.string:
                continue
            text = script.string
            # Look for pin data patterns
            for pattern in [r'__PWS_DATA__\s*=\s*({.*?});',
                            r'"pin"\s*:\s*({.*?})\s*[,}]']:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    try:
                        blob = json.loads(m.group(1))
                        media = _dig_pin_from_pws(blob)
                        if media and media["url"]:
                            return media
                    except:
                        pass

        # ── Method 3: Video source tags ──
        video = soup.find("video")
        if video:
            src = video.get("src")
            source = video.find("source")
            vid_url = src or (source.get("src") if source else None)
            if vid_url:
                return {"type": "video", "url": vid_url, "title": ""}

        # ── Method 4: Meta og:video ──
        og_vid = soup.find("meta", property="og:video")
        if og_vid and og_vid.get("content"):
            return {"type": "video", "url": og_vid["content"], "title": ""}

        # ── Method 5: Meta og:image (fallback) ──
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            title_tag = soup.find("meta", property="og:title")
            title = title_tag["content"] if title_tag and title_tag.get("content") else ""
            return {"type": "image", "url": og_img["content"], "title": title}

        # ── Method 6: Any large image ──
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "pinimg.com" in src and ("originals" in src or "736x" in src):
                return {"type": "image", "url": src, "title": img.get("alt", "")}

        return media

    except Exception as e:
        print(f"  {C.RED}Error fetching pin: {e}{C.RESET}")
        return {"type": None, "url": None, "title": ""}


def _dig_pin_from_pws(data):
    """Recursively dig through PWS JSON to find pin media data"""
    media = {"type": None, "url": None, "title": ""}

    if isinstance(data, dict):
        # Check for video data
        videos = data.get("videos")
        if isinstance(videos, dict):
            vid_list = videos.get("video_list", {})
            best_vid = None
            best_w = 0
            for key, val in vid_list.items():
                if isinstance(val, dict) and val.get("url"):
                    w = val.get("width", 0)
                    if w > best_w:
                        best_w = w
                        best_vid = val["url"]
            if best_vid:
                return {"type": "video", "url": best_vid,
                        "title": data.get("title", data.get("grid_title", ""))}

        # Check for image data
        images = data.get("images") or data.get("image_large_url")
        if isinstance(images, dict):
            orig = images.get("orig", {})
            if isinstance(orig, dict) and orig.get("url"):
                return {"type": "image", "url": orig["url"],
                        "title": data.get("title", data.get("grid_title", ""))}
            # fallback to any large image
            for key in ["1200x", "736x", "564x", "474x"]:
                entry = images.get(key, {})
                if isinstance(entry, dict) and entry.get("url"):
                    return {"type": "image", "url": entry["url"],
                            "title": data.get("title", data.get("grid_title", ""))}
        elif isinstance(images, str) and images:
            return {"type": "image", "url": images,
                    "title": data.get("title", data.get("grid_title", ""))}

        # Check image_large_url directly
        large_url = data.get("image_large_url")
        if isinstance(large_url, str) and large_url:
            return {"type": "image", "url": large_url,
                    "title": data.get("title", data.get("grid_title", ""))}

        # Recurse into nested dicts
        for key, val in data.items():
            if key in ("videos", "images"):
                continue
            result = _dig_pin_from_pws(val)
            if result and result["url"]:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _dig_pin_from_pws(item)
            if result and result["url"]:
                return result

    return media


def _extract_pin_data_from_dict(pin_data):
    """Extract media info from a single pin data dict (from board API)"""
    if not isinstance(pin_data, dict):
        return None

    pin_id = pin_data.get("id", "")
    title = pin_data.get("title") or pin_data.get("grid_title") or ""

    # Video?
    videos = pin_data.get("videos")
    if isinstance(videos, dict):
        vid_list = videos.get("video_list", {})
        best_vid = None
        best_w = 0
        for key, val in vid_list.items():
            if isinstance(val, dict) and val.get("url"):
                w = val.get("width", 0)
                if w > best_w:
                    best_w = w
                    best_vid = val["url"]
        if best_vid:
            return {"id": pin_id, "type": "video", "url": best_vid, "title": title}

    # Story pin video
    story_data = pin_data.get("story_pin_data")
    if isinstance(story_data, dict):
        pages = story_data.get("pages", [])
        for page in pages:
            if isinstance(page, dict):
                blocks = page.get("blocks", [])
                for block in blocks:
                    if isinstance(block, dict):
                        vid = block.get("video", {})
                        if isinstance(vid, dict):
                            vid_list = vid.get("video_list", {})
                            best_vid = None
                            best_w = 0
                            for key, val in vid_list.items():
                                if isinstance(val, dict) and val.get("url"):
                                    w = val.get("width", 0)
                                    if w > best_w:
                                        best_w = w
                                        best_vid = val["url"]
                            if best_vid:
                                return {"id": pin_id, "type": "video",
                                        "url": best_vid, "title": title}
                        img = block.get("image", {})
                        if isinstance(img, dict):
                            images = img.get("images", {})
                            orig = images.get("originals", {}) or images.get("orig", {})
                            if isinstance(orig, dict) and orig.get("url"):
                                return {"id": pin_id, "type": "image",
                                        "url": orig["url"], "title": title}

    # Image
    images = pin_data.get("images") or pin_data.get("image_large_url")
    if isinstance(images, dict):
        for key in ["orig", "originals", "1200x", "736x", "564x", "474x"]:
            entry = images.get(key, {})
            if isinstance(entry, dict) and entry.get("url"):
                return {"id": pin_id, "type": "image", "url": entry["url"], "title": title}
    elif isinstance(images, str) and images:
        return {"id": pin_id, "type": "image", "url": images, "title": title}

    # image_large_url
    large_url = pin_data.get("image_large_url")
    if isinstance(large_url, str) and large_url:
        return {"id": pin_id, "type": "image", "url": large_url, "title": title}

    return None


def download_file(url, filepath, label=""):
    """Download a file with progress bar"""
    try:
        resp = session.get(url, stream=True, timeout=30,
                           headers={"Referer": "https://www.pinterest.com/"})
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        progress_bar(downloaded, total, prefix=label)

        if total:
            print()  # newline after progress bar
        return True
    except Exception as e:
        print(f"\n  {C.RED}Download failed: {e}{C.RESET}")
        return False


def download_single_pin(url, save_dir=None, index=0, total=0):
    """Download a single pin (image or video)"""
    save_dir = save_dir or DOWNLOAD_DIR
    os.makedirs(save_dir, exist_ok=True)

    url = resolve_short_url(url)

    prefix = f"[{index}/{total}] " if total else ""
    print(f"\n  {C.BLUE}{prefix}🔍 Extracting: {url}{C.RESET}")

    media = extract_media_from_pin(url)

    if not media["url"]:
        print(f"  {C.RED}✗ No media found for this pin.{C.RESET}")
        return False

    # Build filename
    pin_id_match = re.search(r'/pin/(\d+)', url)
    pin_id = pin_id_match.group(1) if pin_id_match else hashlib.md5(url.encode()).hexdigest()[:10]

    media_url = media["url"]
    if media["type"] == "video":
        ext = "mp4"
        if ".gif" in media_url:
            ext = "gif"
    else:
        ext_match = re.search(r'\.(jpg|jpeg|png|gif|webp)', media_url, re.I)
        ext = ext_match.group(1) if ext_match else "jpg"

    title_part = re.sub(r'[^a-zA-Z0-9 ]', '', media.get("title", ""))[:50].strip()
    if title_part:
        filename = safe_filename(f"{pin_id}_{title_part}", ext)
    else:
        filename = safe_filename(f"{pin_id}", ext)

    filepath = os.path.join(save_dir, filename)

    # Skip if already exists
    if os.path.exists(filepath):
        print(f"  {C.YELLOW}⊘ Already exists: {filename}{C.RESET}")
        return True

    media_type_icon = "🎬" if media["type"] == "video" else "🖼️"
    print(f"  {C.CYAN}{media_type_icon} Downloading {media['type']}: {filename}{C.RESET}")

    success = download_file(media_url, filepath, label="  📥")

    if success:
        size = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  {C.GREEN}✓ Saved ({size:.2f} MB): {filepath}{C.RESET}")
    return success


# ─── BOARD DOWNLOAD ───────────────────────────────────────
def get_board_info(board_url):
    """Parse the board page to find board ID, name, and initial pins"""
    try:
        resp = session.get(board_url, timeout=20)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        board_info = {"id": None, "name": "", "pins": [], "bookmark": None}

        # Get board name from og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            board_info["name"] = og_title["content"]

        # Parse __PWS_DATA__ for board data
        pws_script = soup.find("script", id="__PWS_DATA__")
        if pws_script and pws_script.string:
            try:
                pws_data = json.loads(pws_script.string)
                _extract_board_from_pws(pws_data, board_info)
            except json.JSONDecodeError:
                pass

        # Fallback: search all scripts for board JSON
        if not board_info["id"]:
            for script in soup.find_all("script"):
                if not script.string:
                    continue
                text = script.string

                # Try to find board ID
                bid_match = re.search(r'"board_id"\s*:\s*"(\d+)"', text)
                if bid_match:
                    board_info["id"] = bid_match.group(1)

                bid_match2 = re.search(r'"id"\s*:\s*"(\d+)".*?"type"\s*:\s*"board"', text)
                if bid_match2 and not board_info["id"]:
                    board_info["id"] = bid_match2.group(1)

        return board_info

    except Exception as e:
        print(f"  {C.RED}Error fetching board: {e}{C.RESET}")
        return None


def _extract_board_from_pws(data, board_info):
    """Dig through PWS data to find board info and initial pins"""
    if isinstance(data, dict):
        # Look for board id
        if data.get("type") == "board" and data.get("id"):
            board_info["id"] = str(data["id"])
            board_info["name"] = board_info["name"] or data.get("name", "")

        # Look for resource responses
        for key, val in data.items():
            if key == "board_id" and isinstance(val, str):
                board_info["id"] = board_info["id"] or val

            if key == "board" and isinstance(val, dict):
                bid = val.get("id")
                if bid:
                    board_info["id"] = board_info["id"] or str(bid)
                    board_info["name"] = board_info["name"] or val.get("name", "")

            if key == "board_feed" and isinstance(val, list):
                for pin in val:
                    pin_media = _extract_pin_data_from_dict(pin)
                    if pin_media:
                        board_info["pins"].append(pin_media)

            if key == "data" and isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("type") == "pin":
                        pin_media = _extract_pin_data_from_dict(item)
                        if pin_media:
                            board_info["pins"].append(pin_media)

            if key == "bookmark" and isinstance(val, str):
                board_info["bookmark"] = val

            # Recurse
            if isinstance(val, (dict, list)):
                _extract_board_from_pws(val, board_info)

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                _extract_board_from_pws(item, board_info)


def fetch_board_pins_api(board_url, board_id):
    """
    Fetch ALL pins from a board using Pinterest's resource API.
    Uses the /resource/BoardFeedResource/get/ endpoint with pagination.
    """
    all_pins = []
    bookmark = None
    page = 0

    # Parse username and board slug from URL
    parsed = urlparse(board_url)
    path = parsed.path.strip("/")
    segments = [s for s in path.split("/") if s]
    
    if len(segments) < 2:
        return all_pins

    username = segments[0]
    board_slug = segments[1]

    print(f"  {C.CYAN}📡 Fetching pins via API...{C.RESET}")

    while True:
        page += 1

        if bookmark:
            options = {
                "board_id": board_id,
                "board_url": f"/{username}/{board_slug}/",
                "currentFilter": -1,
                "field_set_key": "react_grid_pin",
                "filter_section_pins": True,
                "sort": "default",
                "layout": "default",
                "page_size": 25,
                "redux_normalize_feed": True,
                "bookmarks": [bookmark],
            }
        else:
            options = {
                "board_id": board_id,
                "board_url": f"/{username}/{board_slug}/",
                "currentFilter": -1,
                "field_set_key": "react_grid_pin",
                "filter_section_pins": True,
                "sort": "default",
                "layout": "default",
                "page_size": 25,
                "redux_normalize_feed": True,
            }

        params = {
            "source_url": f"/{username}/{board_slug}/",
            "data": json.dumps({"options": options, "context": {}}),
        }

        try:
            api_url = "https://www.pinterest.com/resource/BoardFeedResource/get/"
            resp = session.get(api_url, params=params, timeout=20,
                               headers={**session.headers, **API_HEADERS})
            resp.raise_for_status()
            result = resp.json()

            resource_data = result.get("resource_response", {})
            data = resource_data.get("data", [])

            if not data:
                break

            count_this_page = 0
            for item in data:
                if isinstance(item, dict):
                    pin_media = _extract_pin_data_from_dict(item)
                    if pin_media:
                        # Deduplicate
                        if not any(p["url"] == pin_media["url"] for p in all_pins):
                            all_pins.append(pin_media)
                            count_this_page += 1

            sys.stdout.write(f"\r  {C.DIM}  Page {page}: found {count_this_page} new pins "
                             f"(total: {len(all_pins)}){C.RESET}    ")
            sys.stdout.flush()

            # Get next bookmark
            new_bookmark = resource_data.get("bookmark")
            if not new_bookmark or new_bookmark == bookmark or new_bookmark == "-end-":
                break
            bookmark = new_bookmark

            time.sleep(0.5)  # polite delay

        except Exception as e:
            print(f"\n  {C.YELLOW}⚠ API error on page {page}: {e}{C.RESET}")
            break

    print()  # newline
    return all_pins


def fetch_board_pin_urls_scrape(board_url):
    """
    Fallback: scrape the board page for individual pin URLs,
    then download each one individually.
    """
    try:
        resp = session.get(board_url, timeout=20)
        resp.raise_for_status()
        html = resp.text

        pin_urls = set()

        # Find all pin links in the page
        pin_matches = re.findall(r'"/pin/(\d+)/"', html)
        for pid in pin_matches:
            pin_urls.add(f"https://www.pinterest.com/pin/{pid}/")

        # Also check href attributes
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.match(r'/pin/(\d+)', href)
            if m:
                pin_urls.add(f"https://www.pinterest.com/pin/{m.group(1)}/")

        return list(pin_urls)

    except Exception as e:
        print(f"  {C.RED}Error scraping board: {e}{C.RESET}")
        return []


def download_board(board_url):
    """Download all pins from a Pinterest board"""
    board_url = board_url.strip().rstrip("/") + "/"

    print(f"\n{C.MAGENTA}{C.BOLD}📋 Processing Board: {board_url}{C.RESET}")
    print(f"  {C.DIM}{'─' * 55}{C.RESET}")

    # Step 1: Get board info
    board_info = get_board_info(board_url)

    if not board_info:
        print(f"  {C.RED}✗ Could not load board page.{C.RESET}")
        return 0, 0

    board_name = board_info.get("name", "unknown_board")
    board_name_clean = re.sub(r'[<>:"/\\|?*]', '_', board_name)[:80]
    board_id = board_info.get("id")

    print(f"  {C.GREEN}📌 Board: {board_name}{C.RESET}")
    if board_id:
        print(f"  {C.DIM}   ID: {board_id}{C.RESET}")

    # Create subfolder for this board
    save_dir = os.path.join(DOWNLOAD_DIR, board_name_clean)
    os.makedirs(save_dir, exist_ok=True)

    # Step 2: Fetch all pins
    all_pin_media = list(board_info.get("pins", []))  # initial pins from HTML

    if board_id:
        # Use API for pagination
        api_pins = fetch_board_pins_api(board_url, board_id)
        # Merge, deduplicate
        existing_urls = {p["url"] for p in all_pin_media}
        for p in api_pins:
            if p["url"] not in existing_urls:
                all_pin_media.append(p)
                existing_urls.add(p["url"])

    # Step 3: Fallback — if we got very few pins, try scraping pin URLs
    if len(all_pin_media) < 3:
        print(f"  {C.YELLOW}⚠ Few pins found via API, trying page scrape...{C.RESET}")
        pin_urls = fetch_board_pin_urls_scrape(board_url)
        if pin_urls:
            print(f"  {C.GREEN}Found {len(pin_urls)} pin URLs on page.{C.RESET}")
            success = 0
            fail = 0
            for i, purl in enumerate(pin_urls, 1):
                ok = download_single_pin(purl, save_dir=save_dir, index=i, total=len(pin_urls))
                if ok:
                    success += 1
                else:
                    fail += 1
                time.sleep(0.3)
            return success, fail

    if not all_pin_media:
        print(f"  {C.RED}✗ No pins found in this board.{C.RESET}")
        return 0, 0

    total = len(all_pin_media)
    print(f"\n  {C.GREEN}{C.BOLD}🎯 Found {total} pins to download{C.RESET}")
    print(f"  {C.DIM}   Saving to: {save_dir}{C.RESET}\n")

    # Step 4: Download each pin
    success = 0
    fail = 0

    for i, pin_media in enumerate(all_pin_media, 1):
        media_url = pin_media["url"]
        pin_id = pin_media.get("id", hashlib.md5(media_url.encode()).hexdigest()[:10])
        title = pin_media.get("title", "")
        media_type = pin_media.get("type", "image")

        # Determine extension
        if media_type == "video":
            ext = "mp4"
            icon = "🎬"
        else:
            ext_match = re.search(r'\.(jpg|jpeg|png|gif|webp)', media_url, re.I)
            ext = ext_match.group(1) if ext_match else "jpg"
            icon = "🖼️"

        title_part = re.sub(r'[^a-zA-Z0-9 ]', '', title)[:50].strip()
        if title_part:
            filename = safe_filename(f"{pin_id}_{title_part}", ext)
        else:
            filename = safe_filename(f"{pin_id}", ext)

        filepath = os.path.join(save_dir, filename)

        # Skip existing
        if os.path.exists(filepath):
            print(f"  [{i}/{total}] {C.YELLOW}⊘ Already exists: {filename}{C.RESET}")
            success += 1
            continue

        print(f"  [{i}/{total}] {C.CYAN}{icon} {filename}{C.RESET}")
        ok = download_file(media_url, filepath, label=f"  📥 [{i}/{total}]")

        if ok:
            size = os.path.getsize(filepath) / (1024 * 1024)
            print(f"  {C.GREEN}  ✓ {size:.2f} MB{C.RESET}")
            success += 1
        else:
            fail += 1

        time.sleep(0.3)  # polite

    return success, fail


# ─── MAIN ─────────────────────────────────────────────────
def main():
    banner()

    # Initialize session
    print(f"{C.DIM}Initializing Pinterest session...{C.RESET}")
    init_pinterest_session()
    print(f"{C.GREEN}✓ Session ready{C.RESET}\n")

    while True:
        raw = input(f"{C.BOLD}{C.YELLOW}🔗 Paste Pinterest URL(s) (comma-separated) or 'q' to quit:{C.RESET}\n> ").strip()

        if raw.lower() in ("q", "quit", "exit"):
            print(f"\n{C.CYAN}👋 Goodbye!{C.RESET}")
            break

        if not raw:
            continue

        urls = [u.strip() for u in raw.split(",") if u.strip()]

        if not urls:
            print(f"{C.RED}No valid URLs entered.{C.RESET}")
            continue

        total_success = 0
        total_fail = 0
        start_time = time.time()

        for url in urls:
            url_type = detect_url_type(url)

            if url_type == "board":
                s, f = download_board(url)
                total_success += s
                total_fail += f

            elif url_type == "pin":
                ok = download_single_pin(url, index=urls.index(url)+1, total=len(urls))
                if ok:
                    total_success += 1
                else:
                    total_fail += 1

            else:
                # Try resolving (might be a short URL)
                resolved = resolve_short_url(url)
                rtype = detect_url_type(resolved)
                if rtype == "board":
                    s, f = download_board(resolved)
                    total_success += s
                    total_fail += f
                elif rtype == "pin":
                    ok = download_single_pin(resolved, index=urls.index(url)+1, total=len(urls))
                    if ok:
                        total_success += 1
                    else:
                        total_fail += 1
                else:
                    print(f"\n  {C.RED}✗ Unrecognized URL: {url}{C.RESET}")
                    print(f"  {C.DIM}  Expected: pinterest.com/pin/... or pinterest.com/user/board/{C.RESET}")
                    total_fail += 1

        elapsed = time.time() - start_time

        # ── Summary ──
        print(f"""
{C.BOLD}{'═' * 55}
 📊 SUMMARY
{'═' * 55}{C.RESET}
  {C.GREEN}✓ Success : {total_success}{C.RESET}
  {C.RED}✗ Failed  : {total_fail}{C.RESET}
  {C.DIM}⏱ Time    : {elapsed:.1f}s{C.RESET}
  {C.DIM}📂 Folder  : ./{DOWNLOAD_DIR}/{C.RESET}
{C.BOLD}{'═' * 55}{C.RESET}
""")


if __name__ == "__main__":
    main()

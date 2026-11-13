import os
import re
import time
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import requests

from downloader import download_appllama_url, clean_filename
from parser import parse_app_page

BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR / "apps"
REGISTRY_FILE = APPS_DIR / ".sync_registry.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

# State management
_sync_lock = threading.Lock()
_scheduler_started = False
_sync_state = {
    "enabled": True,
    "interval_seconds": 600,  # 10 minutes
    "is_running": False,
    "last_run_time": None,
    "next_run_time": None,
    "last_result": None,
    "total_synced_count": 0
}

def load_registry() -> Dict[str, Any]:
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_registry(data: Dict[str, Any]):
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Auto-Sync] Failed to save registry: {e}")

def fetch_top_free_apps(limit: int = 2) -> List[Dict[str, str]]:
    """
    Fetches the Appllama homepage and extracts the top free app links.
    Returns a list of dicts: [{'id': ..., 'slug': ..., 'url': ...}, ...]
    """
    url = "https://appllama.io/"
    session = requests.Session()
    session.headers.update(HEADERS)
    
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # Extract all /apps/<id>/<slug> occurrences
    # Example: /apps/6450329545/ai-calorie-counter-appediet
    matches = re.findall(r'/apps/(\d+)/([a-zA-Z0-9\-]+)', html)
    
    seen = set()
    top_apps = []
    for app_id, slug in matches:
        if app_id not in seen:
            seen.add(app_id)
            top_apps.append({
                "id": str(app_id),
                "slug": slug,
                "url": f"https://appllama.io/apps/{app_id}/{slug}"
            })
            if len(top_apps) >= limit:
                break

    return top_apps

def is_app_already_downloaded(app_id: str, slug: str) -> bool:
    """
    Checks if an app is already present and fully downloaded locally.
    1. Checks persistent registry
    2. Checks if app_id exists inside any saved HTML file
    3. Checks slug match in folder/file names
    """
    registry = load_registry()
    if app_id in registry:
        # Verify that the folder still exists
        folder_path = APPS_DIR / registry[app_id].get("files_folder", "")
        if folder_path.is_dir() and any(folder_path.iterdir()):
            return True

    # Check existing HTML files in apps/
    if APPS_DIR.exists():
        for html_file in APPS_DIR.glob("*.html"):
            if html_file.name.lower() in ["index.html", "anchor.html", "saved_resource.html"]:
                continue
            
            # Check slug matching file stem
            stem_norm = re.sub(r'[^a-zA-Z0-9]', '', html_file.stem.lower())
            slug_norm = re.sub(r'[^a-zA-Z0-9]', '', slug.lower())
            if slug_norm in stem_norm or stem_norm in slug_norm:
                # Check that its _files folder exists and is non-empty
                files_folder = APPS_DIR / f"{html_file.stem}_files"
                if files_folder.is_dir() and any(files_folder.iterdir()):
                    # Cache in registry
                    registry[app_id] = {
                        "slug": slug,
                        "html_file": html_file.name,
                        "files_folder": files_folder.name,
                        "verified_at": datetime.now().isoformat()
                    }
                    save_registry(registry)
                    return True

            # Check if app_id is in content
            try:
                content = html_file.read_text(encoding="utf-8", errors="ignore")
                if app_id in content:
                    files_folder = APPS_DIR / f"{html_file.stem}_files"
                    if files_folder.is_dir() and any(files_folder.iterdir()):
                        registry[app_id] = {
                            "slug": slug,
                            "html_file": html_file.name,
                            "files_folder": files_folder.name,
                            "verified_at": datetime.now().isoformat()
                        }
                        save_registry(registry)
                        return True
            except Exception:
                pass

    return False

def sync_top_free_apps(limit: int = 2) -> Dict[str, Any]:
    """
    Scrapes the top free apps on Appllama, checks if they exist locally,
    downloads any missing apps, and returns a summary result.
    """
    global _sync_state

    # Acquire lock so only one sync runs at a time
    if not _sync_lock.acquire(blocking=False):
        return {
            "status": "already_running",
            "message": "A sync is already in progress. Please wait."
        }

    now_iso = datetime.now().isoformat()
    _sync_state["is_running"] = True
    result = {
        "status": "success",
        "timestamp": now_iso,
        "checked_apps": [],
        "downloaded_apps": [],
        "skipped_apps": [],
        "errors": [],
        "message": ""
    }

    print(f"\n[Auto-Sync] 🔍 Checking top {limit} free apps on https://appllama.io/ at {datetime.now().strftime('%H:%M:%S')}...")

    try:
        top_apps = fetch_top_free_apps(limit=limit)
        print(f"[Auto-Sync] Found {len(top_apps)} top app(s): {[a['slug'] for a in top_apps]}")

        newly_downloaded = 0
        for app_info in top_apps:
            app_id = app_info["id"]
            slug = app_info["slug"]
            url = app_info["url"]

            exists = is_app_already_downloaded(app_id, slug)
            app_record = {
                "id": app_id,
                "slug": slug,
                "url": url,
                "already_exists": exists
            }
            result["checked_apps"].append(app_record)

            if exists:
                print(f"[Auto-Sync] ✅ App '{slug}' (ID: {app_id}) is already downloaded. Skipping.")
                result["skipped_apps"].append(slug)
            else:
                print(f"[Auto-Sync] ⬇️ New app detected! Downloading '{slug}' from {url}...")
                try:
                    dl_res = download_appllama_url(url, APPS_DIR)
                    newly_downloaded += 1
                    result["downloaded_apps"].append({
                        "id": app_id,
                        "slug": slug,
                        "name": dl_res.get("app_name"),
                        "files_count": dl_res.get("files_downloaded")
                    })

                    # Update registry
                    registry = load_registry()
                    registry[app_id] = {
                        "slug": slug,
                        "html_file": f"{dl_res['base_stem']}.html",
                        "files_folder": f"{dl_res['base_stem']}_files",
                        "downloaded_at": datetime.now().isoformat(),
                        "files_count": dl_res.get("files_downloaded")
                    }
                    save_registry(registry)
                    print(f"[Auto-Sync] 🎉 Successfully downloaded '{dl_res.get('app_name')}'!")
                except Exception as err:
                    print(f"[Auto-Sync] ❌ Error downloading '{slug}': {err}")
                    result["errors"].append({"slug": slug, "error": str(err)})

        _sync_state["total_synced_count"] += newly_downloaded

        if newly_downloaded > 0:
            result["message"] = f"Downloaded {newly_downloaded} new app(s) from Appllama!"
        else:
            result["message"] = f"Top {len(top_apps)} free apps are already downloaded. Library is up to date."

    except Exception as e:
        print(f"[Auto-Sync] ❌ Failed to fetch Appllama homepage: {e}")
        result["status"] = "error"
        result["message"] = f"Sync check failed: {str(e)}"
        result["errors"].append({"general": str(e)})

    finally:
        _sync_state["is_running"] = False
        _sync_state["last_run_time"] = datetime.now().isoformat()
        _sync_state["next_run_time"] = datetime.fromtimestamp(time.time() + _sync_state["interval_seconds"]).isoformat()
        _sync_state["last_result"] = result
        _sync_lock.release()

    return result

def get_sync_status() -> Dict[str, Any]:
    global _sync_state
    now = time.time()
    
    # Calculate seconds until next run
    seconds_remaining = 0
    if _sync_state["next_run_time"]:
        try:
            next_ts = datetime.fromisoformat(_sync_state["next_run_time"]).timestamp()
            seconds_remaining = max(0, int(next_ts - now))
        except Exception:
            seconds_remaining = 0

    return {
        "enabled": _sync_state["enabled"],
        "interval_seconds": _sync_state["interval_seconds"],
        "interval_minutes": _sync_state["interval_seconds"] // 60,
        "is_running": _sync_state["is_running"],
        "last_run_time": _sync_state["last_run_time"],
        "next_run_time": _sync_state["next_run_time"],
        "seconds_remaining": seconds_remaining,
        "last_result": _sync_state["last_result"],
        "total_synced_count": _sync_state["total_synced_count"]
    }

def _scheduler_loop():
    """
    Background worker loop that runs every 10 minutes (600 seconds).
    """
    print("[Auto-Sync] 🚀 10-Minute Auto-Sync Scheduler started.")
    
    # Run initial check after a short delay (3 seconds) to let server initialize
    time.sleep(3)
    try:
        sync_top_free_apps(limit=2)
    except Exception as e:
        print(f"[Auto-Sync] Initial check error: {e}")

    while True:
        try:
            # Sleep in small 1-second chunks so status queries are responsive and we can wake up on time
            interval = _sync_state.get("interval_seconds", 600)
            target_time = time.time() + interval
            _sync_state["next_run_time"] = datetime.fromtimestamp(target_time).isoformat()

            while time.time() < target_time:
                time.sleep(1)

            if _sync_state.get("enabled", True):
                print("[Auto-Sync] ⏰ 10-Minute recurring trigger activated...")
                sync_top_free_apps(limit=2)

        except Exception as e:
            print(f"[Auto-Sync] Unexpected scheduler exception: {e}")
            time.sleep(10)

def start_scheduler():
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        t = threading.Thread(target=_scheduler_loop, daemon=True, name="AutoSyncScheduler")
        t.start()
        print("[Auto-Sync] Auto-Sync background thread launched.")

if __name__ == "__main__":
    print("Testing auto_sync manually...")
    res = sync_top_free_apps(limit=2)
    print("Sync Result:", json.dumps(res, indent=2))


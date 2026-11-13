import os
import io
import time
import zipfile
import shutil
import urllib.parse
from pathlib import Path
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, BackgroundTasks, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parser import parse_app_page
from downloader import download_appllama_url
from auto_sync import sync_top_free_apps, get_sync_status, start_scheduler

# Paths
BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR / "apps"
STATIC_DIR = BASE_DIR / "static"

APPS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AppFlows Studio - Appllama Archive", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# App Data Cache
_APP_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_MTIME: Dict[str, float] = {}

def scan_all_apps(force: bool = False) -> List[Dict[str, Any]]:
    global _APP_CACHE, _CACHE_MTIME
    
    html_files = []
    if APPS_DIR.exists():
        # Find all .html files in APPS_DIR and its subdirectories, excluding asset _files directories
        for p in APPS_DIR.rglob("*.html"):
            if any(part.endswith(('_files', '.files')) for part in p.parts):
                continue
            if p.name.lower() in ["anchor.html", "saved_resource.html", "index.html"]:
                continue
            html_files.append(p)

    apps_list = []
    current_ids = set()

    for html_path in html_files:
        try:
            mtime = html_path.stat().st_mtime
            str_path = str(html_path)
            
            # Use cache if mtime is unchanged
            if not force and str_path in _APP_CACHE and _CACHE_MTIME.get(str_path) == mtime:
                app_data = _APP_CACHE[str_path]
            else:
                app_data = parse_app_page(str_path)
                if app_data and app_data.get("name"):
                    _APP_CACHE[str_path] = app_data
                    _CACHE_MTIME[str_path] = mtime
                else:
                    continue

            if app_data:
                apps_list.append(app_data)
                current_ids.add(str_path)
        except Exception as e:
            print(f"Error scanning {html_path}: {e}")

    # Remove stale cache entries
    stale_keys = [k for k in _APP_CACHE if k not in current_ids]
    for k in stale_keys:
        _APP_CACHE.pop(k, None)
        _CACHE_MTIME.pop(k, None)

    # Sort apps by name
    apps_list.sort(key=lambda x: x.get("name", "").lower())
    return apps_list

def get_app_by_id(app_id: str) -> Optional[Dict[str, Any]]:
    # Search by id or slug
    all_apps = scan_all_apps()
    for a in all_apps:
        if a["id"] == app_id:
            return a
    # fallback partial match
    for a in all_apps:
        if app_id.lower() in a["id"].lower() or a["id"].lower() in app_id.lower():
            return a
    return None

@app.get("/api/apps")
def list_apps(refresh: bool = False, full: bool = True):
    apps = scan_all_apps(force=refresh)
    summaries = []
    for a in apps:
        item = {
            "id": a["id"],
            "name": a["name"],
            "subtitle": a["subtitle"],
            "publisher": a["publisher"],
            "icon": a["icon"],
            "categories": a["categories"],
            "revenue": a["revenue"],
            "revenue_period_label": a.get("revenue_period_label", "Revenue • October 2026"),
            "downloads": a["downloads"],
            "rating": a["rating"],
            "ratings_count": a.get("ratings_count", ""),
            "rank": a["rank"],
            "total_screens": a["total_screens"],
            "stills_count": a.get("stills_count", a["total_screens"]),
            "videos_count": a.get("videos_count", 0),
            "flow_categories": a.get("flow_categories", []),
            "total_flows": len(a.get("flows", [])),
            "flow_titles": [f["name"] for f in a.get("flows", [])[:5]]
        }
        if full:
            item["flows"] = a.get("flows", [])
            item["store_screenshots"] = a.get("store_screenshots", [])
        summaries.append(item)
    return {
        "status": "ok",
        "total": len(summaries),
        "apps_dir": str(APPS_DIR),
        "apps": summaries
    }

@app.get("/api/apps/{app_id}")
def get_app_details(app_id: str):
    app_data = get_app_by_id(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail="App not found")
    return {"status": "ok", "app": app_data}

@app.get("/api/apps/{app_id}/download")
def download_full_app(app_id: str):
    app_data = get_app_by_id(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail="App not found")

    safe_app_name = "".join(c for c in app_data["name"] if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_app_name:
        safe_app_name = "app_screens"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for flow in app_data.get("flows", []):
            flow_clean_name = flow["full_title"].replace(" > ", "/").replace(":", "").replace("?", "").replace("\\", "/")
            for idx, screen in enumerate(flow.get("screens", [])):
                local_path = screen.get("local_path")
                if local_path and os.path.isfile(local_path):
                    ext = os.path.splitext(local_path)[1]
                    safe_title = "".join(c for c in screen["title"] if c.isalnum() or c in (' ', '_', '-')).strip()
                    arcname = f"{safe_app_name}/{flow_clean_name}/{idx+1:02d}_{safe_title}{ext}"
                    zf.write(local_path, arcname)

    zip_buffer.seek(0)
    filename = f"{safe_app_name}_all_flows.zip"
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/apps/{app_id}/flows/{flow_idx}/download")
def download_flow_zip(app_id: str, flow_idx: int):
    app_data = get_app_by_id(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail="App not found")

    flows = app_data.get("flows", [])
    if flow_idx < 0 or flow_idx >= len(flows):
        raise HTTPException(status_code=404, detail="Flow index out of range")

    flow = flows[flow_idx]
    safe_app_name = "".join(c for c in app_data["name"] if c.isalnum() or c in (' ', '_', '-')).strip()
    safe_flow_name = "".join(c for c in flow["name"] if c.isalnum() or c in (' ', '_', '-')).strip()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, screen in enumerate(flow.get("screens", [])):
            local_path = screen.get("local_path")
            if local_path and os.path.isfile(local_path):
                ext = os.path.splitext(local_path)[1]
                safe_title = "".join(c for c in screen["title"] if c.isalnum() or c in (' ', '_', '-')).strip()
                arcname = f"{safe_flow_name}/{idx+1:02d}_{safe_title}{ext}"
                zf.write(local_path, arcname)

    zip_buffer.seek(0)
    filename = f"{safe_app_name}_{safe_flow_name}_screens.zip"
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/download-image")
def download_single_image(path: str = Query(...), filename: str = Query("screen.webp")):
    # Safe validation of path
    # It must be within APPS_DIR
    req_path = (APPS_DIR / path).resolve()
    # Check if inside APPS_DIR
    if not str(req_path).startswith(str(APPS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not req_path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")

    # Clean desired filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in ('.', ' ', '_', '-')).strip()
    if not safe_filename:
        safe_filename = req_path.name

    return FileResponse(
        path=str(req_path),
        filename=safe_filename,
        media_type="application/octet-stream"
    )

class UrlDownloadRequest(BaseModel):
    url: str

@app.post("/api/download-url")
def download_from_url(payload: UrlDownloadRequest):
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Please provide a valid Appllama URL")

    if not url.startswith("http"):
        url = "https://" + url

    try:
        result = download_appllama_url(url, APPS_DIR)
        apps = scan_all_apps(force=True)
        # Find the newly created app
        new_app = None
        for a in apps:
            if a["id"] == result["base_stem"] or a.get("name") == result["app_name"]:
                new_app = a
                break
        return {
            "status": "ok",
            "message": f"Successfully downloaded '{result['app_name']}' with {result['files_downloaded']} media files!",
            "app": new_app,
            "total_apps": len(apps)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download from URL: {str(e)}")

@app.on_event("startup")
def startup_event():
    # Start the 10-minute recurring auto-sync scheduler
    start_scheduler()

@app.get("/api/sync/status")
def get_auto_sync_status():
    return get_sync_status()

@app.post("/api/sync/trigger")
def trigger_auto_sync():
    result = sync_top_free_apps(limit=2)
    # If any new apps were downloaded, force rescan
    if result.get("downloaded_apps"):
        scan_all_apps(force=True)
    return {
        "status": result.get("status", "ok"),
        "result": result,
        "total_apps": len(scan_all_apps())
    }

@app.post("/api/rescan")
def rescan_apps():
    apps = scan_all_apps(force=True)
    return {"status": "ok", "total": len(apps), "message": f"Successfully rescanned {len(apps)} app(s)"}

@app.post("/api/upload")
def upload_webpage_archive(file: UploadFile = File(...)):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No file selected")

    if filename.lower().endswith('.zip'):
        zip_bytes = file.file.read()
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(APPS_DIR)
            apps = scan_all_apps(force=True)
            return {"status": "ok", "message": f"Archive extracted successfully! Detected {len(apps)} apps."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract zip: {e}")
    elif filename.lower().endswith(('.html', '.htm')):
        dest_path = APPS_DIR / filename
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        apps = scan_all_apps(force=True)
        return {"status": "ok", "message": f"HTML file uploaded. Make sure its matching '_files' folder is also in 'apps/'."}
    else:
        raise HTTPException(status_code=400, detail="Only .zip or .html files are supported")

# Media Route to serve images from APPS_DIR
@app.get("/media/{folder_and_file:path}")
def serve_media(folder_and_file: str):
    decoded = urllib.parse.unquote(folder_and_file)
    target_path = (APPS_DIR / decoded).resolve()
    
    if not str(target_path).startswith(str(APPS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = target_path.suffix.lower()
    media_types = {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".mp4": "video/mp4",
        ".svg": "image/svg+xml",
        ".gif": "image/gif"
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(str(target_path), media_type=media_type)

# Serve Frontend SPA
@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        return JSONResponse({"message": "Frontend static file not yet created"})
    return FileResponse(str(index_file))

# Mount static files folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

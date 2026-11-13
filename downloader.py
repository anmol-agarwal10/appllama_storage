import os
import re
import json
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

def clean_filename(s: str) -> str:
    # Replace characters not allowed in Windows filenames
    return re.sub(r'[\\/*?:"<>|]', '_', s).strip()

def download_appllama_url(url: str, apps_dir: Path, progress_callback=None):
    """
    Downloads an Appllama page by URL:
    1. Fetches HTML
    2. Extracts app name, icon, and all flow images
    3. Downloads images to <app_folder>_files/
    4. Rewrites image URLs in HTML to local files
    5. Saves <app_name>.html in apps_dir
    """
    url = url.strip()
    if not url.startswith('http'):
        url = 'https://' + url

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Fetching URL: {url}...")
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # Extract App Name
    app_name = "Appllama_App"
    # Try ld+json
    ld_matches = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    for m in ld_matches:
        try:
            data = json.loads(m.strip())
            if data.get("@type") in ["Product", "MobileApplication"] or "additionalType" in data:
                app_name = data.get("name", app_name)
                break
        except:
            pass

    if app_name == "Appllama_App":
        # Fallback to <title>
        t = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL)
        if t:
            app_name = t.group(1).split('|')[0].split('-')[0].strip()

    # Create safe base name matching browser "Save As" style
    safe_base = clean_filename(f"{app_name} screens, onboarding and paywall _ Appllama")
    if len(safe_base) > 120:
        safe_base = safe_base[:120].strip()

    target_html_path = apps_dir / f"{safe_base}.html"
    target_files_dir = apps_dir / f"{safe_base}_files"
    target_files_dir.mkdir(parents=True, exist_ok=True)

    print(f"Target files dir: {target_files_dir}")

    # Find all media URLs
    # 1. Matches cloud.appllama.io orig images and icons
    raw_urls = re.findall(r'https://cloud\.appllama\.io/[^\s"\'<>\\]+', html)
    # Filter valid extensions
    valid_urls = set()
    for u in raw_urls:
        clean_u = u.rstrip('\\').rstrip('"').rstrip("'")
        if any(clean_u.endswith(ext) for ext in ['.webp', '.jpg', '.jpeg', '.png', '.mp4', '.svg']):
            valid_urls.add(clean_u)

    print(f"Found {len(valid_urls)} media files to download")

    # Download helper
    def download_file(media_url):
        filename = media_url.split('/')[-1]
        dest_file = target_files_dir / filename
        if dest_file.exists() and dest_file.stat().st_size > 0:
            return media_url, filename, True

        try:
            r = session.get(media_url, timeout=15)
            if r.status_code == 200:
                with open(dest_file, 'wb') as f:
                    f.write(r.content)
                return media_url, filename, True
        except Exception as e:
            print(f"Error downloading {media_url}: {e}")
        return media_url, filename, False

    # Download images concurrently with 16 workers
    downloaded_count = 0
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(download_file, u): u for u in valid_urls}
        for future in as_completed(futures):
            m_url, fname, success = future.result()
            if success:
                downloaded_count += 1
                if progress_callback:
                    progress_callback(downloaded_count, len(valid_urls))

    print(f"Successfully downloaded {downloaded_count}/{len(valid_urls)} files.")

    # Rewrite HTML to point cloud.appllama.io URLs to local ./<safe_base>_files/<filename>
    # In browser saved pages, the relative src is:
    # ./Feenko_ Cancel Subscriptions..._files/e47ed419da20690a51bcd70eabcffaac61c2e083.webp
    rewritten_html = html
    for u in valid_urls:
        filename = u.split('/')[-1]
        # Replace in src, srcset, etc.
        local_rel = f"./{target_files_dir.name}/{filename}"
        rewritten_html = rewritten_html.replace(u, local_rel)

    with open(target_html_path, 'w', encoding='utf-8') as f:
        f.write(rewritten_html)

    print(f"Saved rewritten HTML to {target_html_path}")
    return {
        "app_name": app_name,
        "base_stem": safe_base,
        "html_path": str(target_html_path),
        "files_dir": str(target_files_dir),
        "files_downloaded": downloaded_count
    }

if __name__ == "__main__":
    from pathlib import Path
    apps_folder = Path("apps")
    res = download_appllama_url(
        "https://appllama.io/apps/6747166058/glow-diet-coach-meal-plans",
        apps_folder
    )
    print("Download result:", res)


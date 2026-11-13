import os
import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_app_page(html_file_path: str) -> Optional[Dict[str, Any]]:
    """
    Parses a downloaded Appllama HTML page and its associated _files folder.
    Returns structured metadata, flows, and screen image references.
    """
    path = Path(html_file_path)
    if not path.is_file() or not path.name.lower().endswith(('.html', '.htm')):
        return None

    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()
    except Exception as e:
        print(f"Error reading {html_file_path}: {e}")
        return None

    base_dir = path.parent
    base_stem = path.stem

    # Locate associated files folder
    # Browser usually saves as "<stem>_files"
    files_folder = None
    candidate_folders = [
        base_dir / f"{base_stem}_files",
        base_dir / f"{base_stem}.files",
        base_dir / base_stem,
    ]
    for c in candidate_folders:
        if c.is_dir():
            files_folder = c
            break

    # If no files folder with matching stem, search for any folder matching prefix
    if not files_folder:
        for item in base_dir.iterdir():
            if item.is_dir() and (item.name.startswith(base_stem[:15]) or base_stem.startswith(item.name[:15])):
                files_folder = item
                break

    # Metadata initialization
    meta = {
        "id": base_stem,
        "name": "",
        "subtitle": "",
        "publisher": "",
        "icon": "",
        "icon_local_path": "",
        "categories": [],
        "revenue": "",
        "downloads": "",
        "rating": "",
        "ratings_count": "",
        "rank": "",
        "description": "",
        "source_html": str(path.relative_to(base_dir.parent) if base_dir.parent in path.parents else path),
        "files_folder": str(files_folder.relative_to(base_dir.parent) if files_folder and base_dir.parent in files_folder.parents else files_folder) if files_folder else "",
        "flows": [],
        "total_screens": 0
    }

    # 1. Parse JSON-LD Schema.org scripts
    ld_matches = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    for m in ld_matches:
        try:
            data = json.loads(m.strip())
            if isinstance(data, dict):
                # Product / MobileApplication
                if data.get("@type") in ["Product", "MobileApplication", "SoftwareApplication"] or "additionalType" in data:
                    meta["name"] = data.get("name", meta["name"])
                    meta["subtitle"] = data.get("description", meta["subtitle"])
                    if isinstance(data.get("brand"), dict):
                        meta["publisher"] = data["brand"].get("name", meta["publisher"])
                    if data.get("category"):
                        meta["categories"] = [c.strip() for c in data["category"].split(",") if c.strip()]
                    if isinstance(data.get("aggregateRating"), dict):
                        meta["rating"] = str(data["aggregateRating"].get("ratingValue", meta["rating"]))
                        meta["ratings_count"] = str(data["aggregateRating"].get("ratingCount", meta["ratings_count"]))
        except Exception:
            pass

    # 2. Parse Next.js App Router chunks for revenue, downloads, rank, ratings
    rev = re.search(r'revenue_display\\*":\\*"([^"\\]+)', html)
    if rev:
        meta["revenue"] = rev.group(1).replace('$$', '$')

    down = re.search(r'downloads_display\\*":\\*"([^"\\]+)', html)
    if down:
        meta["downloads"] = down.group(1)

    rank = re.search(r'category_rank\\*":(\d+).*?category_rank_name\\*":\\*"([^"\\]+)', html)
    if rank:
        meta["rank"] = f"#{rank.group(1)} {rank.group(2)}"

    if not meta["rating"]:
        rating_match = re.search(r'average_rating\\*":([0-9.]+)', html)
        if rating_match:
            meta["rating"] = rating_match.group(1)

    if not meta["ratings_count"]:
        ratings_count_match = re.search(r'total_ratings\\*":(\d+)', html)
        if ratings_count_match:
            meta["ratings_count"] = ratings_count_match.group(1)

    if not meta["name"]:
        # Fallback to <title> or <h1>
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        if h1:
            meta["name"] = clean_text(h1.group(1))
        else:
            t = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL)
            if t:
                meta["name"] = clean_text(t.group(1)).split('|')[0].split('-')[0].strip()
            else:
                meta["name"] = base_stem.replace('_', ' ').replace('-', ' ').title()

    # 3. Locate App Icon
    icon_filename = None
    icon_match = re.search(r'icon_url\\*":\\*"([^"\\]+)', html)
    if icon_match:
        url = icon_match.group(1)
        icon_filename = url.split('/')[-1]

    if files_folder and files_folder.is_dir():
        # Check if the matched icon filename exists
        if icon_filename and (files_folder / icon_filename).is_file():
            meta["icon"] = f"/media/{files_folder.name}/{icon_filename}"
            meta["icon_local_path"] = str(files_folder / icon_filename)
        else:
            # Look for icon or jpg in files_folder
            for f in files_folder.iterdir():
                if f.is_file() and (f.suffix.lower() == '.jpg' or 'icon' in f.stem.lower() or 'logo' in f.stem.lower()):
                    if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                        meta["icon"] = f"/media/{files_folder.name}/{f.name}"
                        meta["icon_local_path"] = str(f)
                        break

    # 4. Extract Headings and Flow Hierarchy
    headings = []
    for m in re.finditer(r'<(h[23])[^>]*>(.*?)</\1>', html, re.DOTALL):
        tag = m.group(1)
        text = clean_text(m.group(2))
        headings.append({
            "tag": tag,
            "text": text,
            "start": m.start(),
            "end": m.end()
        })

    # 5. Extract Images and correlate with headings
    # We find all <img> tags in the html
    raw_images = []
    for m in re.finditer(r'<img\s+([^>]+)>', html):
        tag_str = m.group(1)
        alt_match = re.search(r'alt="([^"]*)"', tag_str)
        src_match = re.search(r'src="([^"]*)"', tag_str)
        alt = clean_text(alt_match.group(1)) if alt_match else ""
        src = src_match.group(1) if src_match else ""

        # Filter out Appllama logos, decorative elements, avatars
        if not alt or alt.lower() in ['appllama', 'logo', 'icon', '']:
            continue
        if 'logo' in src.lower() or 'avatar' in src.lower():
            continue

        # Resolve local image file in files_folder
        filename = Path(src).name
        local_path = None
        web_src = ""
        if files_folder and (files_folder / filename).is_file():
            local_path = str(files_folder / filename)
            web_src = f"/media/{files_folder.name}/{filename}"
        elif files_folder:
            # Check by unquoted or decoded name
            decoded = filename.split('?')[0]
            if (files_folder / decoded).is_file():
                local_path = str(files_folder / decoded)
                web_src = f"/media/{files_folder.name}/{decoded}"

        if not local_path and not src.startswith(('http://', 'https://')):
            continue

        raw_images.append({
            "alt": alt,
            "filename": filename,
            "local_path": local_path or "",
            "src": web_src or src,
            "is_video": False,
            "pos": m.start()
        })

    # 5b. Extract Video assets from files_folder
    raw_videos = []
    if files_folder and files_folder.is_dir():
        for vid_file in files_folder.glob("*.mp4"):
            v_filename = vid_file.name
            v_flow = "Welcome Screen"
            idx = html.find(v_filename)
            if idx != -1:
                context = html[max(0, idx - 150): min(len(html), idx + 250)]
                flow_match = re.search(r'flow\\*":\\*"([^"\\]+)', context)
                if flow_match:
                    v_flow = flow_match.group(1)

            raw_videos.append({
                "alt": f"{v_flow} (Video Walkthrough)",
                "filename": v_filename,
                "local_path": str(vid_file),
                "src": f"/media/{files_folder.name}/{v_filename}",
                "is_video": True,
                "flow_name": v_flow,
                "pos": idx if idx != -1 else 0
            })

    # Combine images and videos
    all_media = raw_images + raw_videos

    # 6. Assign media items to flow sections
    flows_dict: Dict[str, Dict[str, Any]] = {}
    flow_order: List[str] = []

    for item in all_media:
        current_h2 = "General Screens"
        current_h3 = ""
        for h in headings:
            if h['start'] < item['pos']:
                if h['tag'] == 'h2':
                    current_h2 = h['text']
                    current_h3 = ""
                elif h['tag'] == 'h3':
                    current_h3 = h['text']
            else:
                break

        if item.get("is_video"):
            v_flow_target = item.get("flow_name", "Welcome")
            flow_key = v_flow_target
            for k in flow_order:
                if v_flow_target.lower() in k.lower() or k.lower() in v_flow_target.lower():
                    flow_key = k
                    break
        else:
            # Ignore Similar apps section
            if current_h2.lower().startswith("similar app"):
                continue
            flow_key = f"{current_h2} > {current_h3}" if current_h3 else current_h2

        if flow_key not in flows_dict:
            flows_dict[flow_key] = {
                "category": current_h2,
                "subcategory": current_h3,
                "name": current_h3 if current_h3 else current_h2,
                "full_title": flow_key,
                "screens": []
            }
            flow_order.append(flow_key)

        screen_item = {
            "title": item["alt"],
            "filename": item["filename"],
            "local_path": item["local_path"],
            "src": item["src"],
            "is_video": item.get("is_video", False),
            "flow": flow_key
        }
        flows_dict[flow_key]["screens"].append(screen_item)

    flows = [flows_dict[k] for k in flow_order if flows_dict[k]["screens"]]
    meta["flows"] = flows
    meta["total_screens"] = sum(len(f["screens"]) for f in flows)
    meta["stills_count"] = sum(1 for f in flows for s in f["screens"] if not s.get("is_video"))
    meta["videos_count"] = sum(1 for f in flows for s in f["screens"] if s.get("is_video"))
    meta["flow_categories"] = list(dict.fromkeys(f.get("category", f.get("name", "Flow")) for f in flows))

    return meta

if __name__ == "__main__":
    res = parse_app_page("apps/Feenko_ Cancel Subscriptions screens, onboarding and paywall _ Appllama.html")
    print(f"App: {res['name']}")
    print(f"Subtitle: {res['subtitle']}")
    print(f"Publisher: {res['publisher']}")
    print(f"Icon: {res['icon']}")
    print(f"Categories: {res['categories']}")
    print(f"Revenue: {res['revenue']} | Downloads: {res['downloads']} | Rating: {res['rating']} ({res['ratings_count']})")
    print(f"Total Flows: {len(res['flows'])}, Total Screens: {res['total_screens']}")
    for f in res["flows"]:
        print(f"  • {f['full_title']} ({len(f['screens'])} screens)")


# 📱 AppFrame — Automated Appllama Flow Archive & Viewer

A single-page, serverless mobile app screen archive that automatically scrapes, compresses, and archives the latest free screen flows from [Appllama.io](https://appllama.io/) using **GitHub Actions**, deployed 100% free on **GitHub Pages**.

---

## ⚡ How It Works

1. **Automated Scraping & Compression (`compress_scraper.py`)**:
   - Runs automatically on GitHub Actions on a recurring schedule.
   - Discovers the top 2 free app flows on [Appllama.io](https://appllama.io/).
   - Compresses all high-resolution screen images to optimized **WebP** (reducing storage by 80%–95%).
   - Commits and pushes the new flows and updated `data.json` directly back to the GitHub repository.

2. **Standalone Frontend (`index.html`)**:
   - Zero-server, client-side SPA ready for **GitHub Pages**.
   - Preserves complete Appllama styling with dark and light themes, horizontal phone mockups, flow breakdown, full-text search, and lightbox modal.
   - Client-side ZIP generation using JSZip (download full app or single flow ZIP directly from your browser without a backend).

---

## 🚀 How to Enable GitHub Pages (2 Clicks)

1. Push this repository to GitHub:
   ```bash
   git add .
   git commit -m "Deploy Appllama archive"
   git push origin master
   ```
2. In your GitHub repository:
   - Go to **Settings** → **Pages** (under Code and automation in the left sidebar).
   - Under **Build and deployment** > **Source**, select **Deploy from a branch**.
   - Under **Branch**, select `master` (or `main`) and folder `/ (root)`.
   - Click **Save**.
3. In ~60 seconds, your site is live at:
   `https://<your-username>.github.io/<repo-name>/`

---

## ⚙️ Triggering the Workflow Manually

You don't have to wait for the cron schedule:
1. Go to the **Actions** tab in your GitHub repository.
2. Select **Auto-Sync Appllama Free Flows** on the left.
3. Click **Run workflow** → **Run workflow**.
4. GitHub Actions will run `compress_scraper.py`, download any new flows, compress them, commit them, and update your live site!


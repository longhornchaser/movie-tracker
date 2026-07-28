# Deploying your Movie Tracker

Everything needed to put your movie collection online is in this folder.

| File | What it is |
|---|---|
| `main.py` | The app — the search/add engine plus the add-password gate |
| `index.html` | The web page you interact with |
| `movies.db` | Your collection — seeds the server on first run |
| `requirements.txt`, `Dockerfile`, `render.yaml` | Deployment setup |
| `DEPLOY.md` | This guide |

---

## How access works

- **Browsing and searching are open to everyone** — no password needed to look around.
- **Adding a movie requires a password.** On the *Add a movie* tab, a visitor enters your password once to unlock the form; it stays unlocked on that device for 30 days, or until they click **Lock**.

## Settings (environment variables)

| Variable | What it does |
|---|---|
| `APP_PASSWORD` | The password required to add movies. **You set this.** |
| `SECRET_KEY` | Random string that signs the unlock cookie. Render generates it automatically. |
| `DB_PATH` | Where the live database lives. Preset to `/data/movies.db`. |

---

## 1. (Optional) Try it on your computer first

1. Install Python 3.
2. In this folder: `pip install -r requirements.txt`
3. Start it (Mac/Linux):
   `APP_PASSWORD=choose-a-password SECRET_KEY=anything uvicorn main:app --reload`
   Windows PowerShell:
   `$env:APP_PASSWORD="choose-a-password"; $env:SECRET_KEY="anything"; uvicorn main:app --reload`
4. Open **http://localhost:8000**. Browse freely; to add a movie, enter the password you set.

---

## 2. Deploy to Render (recommended)

1. Create an account at **render.com**.
2. Put this folder into a Git repository (GitHub or GitLab) and push it — Render deploys from a repo.
3. In Render: **New → Blueprint**, and point it at your repository. It reads `render.yaml` and creates
   the web service **and** a 1 GB persistent disk mounted at `/data`.
4. Set **`APP_PASSWORD`** to the password you want for adding movies.
   (`SECRET_KEY` is generated for you; `DB_PATH` is already `/data/movies.db`.)
5. Click **Deploy**. On first boot the app copies your `movies.db` onto the persistent disk; every movie
   added afterward is saved there and survives restarts and redeploys.
6. Render gives you an HTTPS address like `https://movie-tracker-xxxx.onrender.com`.

> **Plan note:** a persistent disk requires a paid instance (Render's free tier has no disk and sleeps when
> idle). The smallest always-on tier runs about **$7/month** — check current pricing, as it changes.

---

## 3. Connect your domain (longhornchaser.com)

1. Register **longhornchaser.com** at a registrar — **Cloudflare Registrar** (at-cost), **Porkbun**, or
   **Namecheap** (~$10–15/year).
2. In Render → your service → **Settings → Custom Domains** → add `longhornchaser.com` (and `www.longhornchaser.com`).
3. Render shows you a DNS record to create (a CNAME for `www`, and an A/ALIAS record for the bare domain).
   Add it in your registrar's DNS settings.
4. Render issues a **free SSL certificate** automatically. Within a few minutes to an hour,
   **https://longhornchaser.com** serves your tracker.

---

## 4. Automatic backups to Dropbox

The app uploads a fresh copy of your database to Dropbox on startup and then every night. It stays off until
you provide three Dropbox credentials. One-time setup:

1. Go to the **Dropbox App Console** (dropbox.com/developers/apps) → **Create app**.
   - Choose **Scoped access** and **App folder** access (safest — the app only sees its own folder).
   - Name it, e.g. `MovieTrackerBackup`.
2. On the app's **Permissions** tab, enable **`files.content.write`**, then **Submit**.
3. On the **Settings** tab, copy the **App key** and **App secret**.
4. Get a **refresh token** (one time):
   1. Visit this URL in your browser (paste in your App key), click **Allow**, and copy the code shown:
      `https://www.dropbox.com/oauth2/authorize?client_id=YOUR_APP_KEY&response_type=code&token_access_type=offline`
   2. Exchange that code for a refresh token (fill in the three values):
      `curl https://api.dropbox.com/oauth2/token -d code=YOUR_CODE -d grant_type=authorization_code -u YOUR_APP_KEY:YOUR_APP_SECRET`
      Copy the `refresh_token` from the JSON response.
5. In Render → your service → **Environment**, set:
   - `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
   - *(optional)* `DROPBOX_BACKUP_FOLDER` — leave empty for App-folder access; set e.g. `/MovieTracker` if you chose Full Dropbox access.
   - *(optional)* `BACKUP_INTERVAL_HOURS` — defaults to `24`.
6. Redeploy. Backups land in Dropbox under **Apps/MovieTrackerBackup/** as `movies-YYYY-MM-DD.db`.

**Test it now:** open the site, unlock the *Add a movie* tab with your password, and click **Back up to Dropbox now**.

You can still grab a manual copy anytime from Render → your service → **Shell**. It's a 30-year archive — these
copies are cheap insurance.

---

## Any other Docker host (Fly.io, a VPS, etc.)

The included `Dockerfile` is standard:

```
docker build -t movie-tracker .
docker run -p 8000:8000 -e APP_PASSWORD=... -e SECRET_KEY=... -v "$(pwd)/data:/data" movie-tracker
```

Mount a volume at `/data` so the database persists.

---

## Changing it later

Edit `index.html` (the page) or `main.py` (search/add logic), push to your repository, and the host
redeploys automatically. Your data on `/data` is never touched by a redeploy.

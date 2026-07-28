"""
Movie Tracker — backend API + login gate.

Reads and writes a SQLite database (the schema you approved) and serves the
single-page interface. Configuration comes from environment variables:

  DB_PATH      where the live database lives   (default: /data/movies.db on a host)
  APP_PASSWORD the password to log in          (REQUIRED in production)
  SECRET_KEY   random string used to sign the login cookie (REQUIRED in production)

On first boot, if DB_PATH doesn't exist yet, the bundled seed `movies.db`
(your migrated collection) is copied to it — so a fresh persistent disk is
populated automatically, and every later write stays on that disk.
"""
import os, sqlite3, hmac, hashlib, time, shutil
import json, threading, tempfile, datetime, urllib.request, urllib.parse
from fastapi import FastAPI, Request, Body, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse

HERE        = os.path.dirname(os.path.abspath(__file__))
SEED_DB     = os.path.join(HERE, "movies.db")
DB_PATH     = os.environ.get("DB_PATH", os.path.join(HERE, "movies.db"))
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-only-change-me")
COOKIE      = "mt_session"
MAX_AGE     = 30 * 86400  # login lasts 30 days

# Seed a fresh persistent disk from the bundled database on first run.
if os.path.abspath(DB_PATH) != os.path.abspath(SEED_DB) and not os.path.exists(DB_PATH):
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    shutil.copy(SEED_DB, DB_PATH)

app = FastAPI(title="Movie Tracker")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


# --------------------------------------------------------------------------
# Optional automatic backup of the database to Dropbox.
# Runs on startup and then every BACKUP_INTERVAL_HOURS (default 24h).
# Enabled only when all three Dropbox credentials are provided.
# --------------------------------------------------------------------------
DROPBOX_APP_KEY       = os.environ.get("DROPBOX_APP_KEY", "")
DROPBOX_APP_SECRET    = os.environ.get("DROPBOX_APP_SECRET", "")
DROPBOX_REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN", "")
DROPBOX_FOLDER        = os.environ.get("DROPBOX_BACKUP_FOLDER", "")   # "" = app-folder root
BACKUP_INTERVAL_HOURS = float(os.environ.get("BACKUP_INTERVAL_HOURS", "24"))
BACKUP_ENABLED = bool(DROPBOX_APP_KEY and DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN)

def _db_snapshot():
    """Make a consistent copy of the live database (safe even during a write)."""
    fd, tmp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    src = sqlite3.connect(DB_PATH); dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    return tmp

def _dropbox_token():
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY, "client_secret": DROPBOX_APP_SECRET,
    }).encode()
    req = urllib.request.Request("https://api.dropbox.com/oauth2/token", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]

def backup_to_dropbox():
    """Snapshot the database and upload it to Dropbox. Returns the Dropbox path."""
    if not BACKUP_ENABLED:
        raise RuntimeError("Dropbox backup is not configured")
    tmp = _db_snapshot()
    try:
        with open(tmp, "rb") as f:
            body = f.read()
    finally:
        try: os.remove(tmp)
        except OSError: pass
    day = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    path = DROPBOX_FOLDER.rstrip("/") + "/movies-" + day + ".db"
    token = _dropbox_token()
    req = urllib.request.Request("https://content.dropboxapi.com/2/files/upload", data=body, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Dropbox-API-Arg", json.dumps({"path": path, "mode": "overwrite", "mute": True}))
    req.add_header("Content-Type", "application/octet-stream")
    with urllib.request.urlopen(req, timeout=120) as r:
        info = json.loads(r.read())
    return info.get("path_display", path)

def _backup_loop():
    while True:
        try:
            print("[backup] uploaded", backup_to_dropbox(), flush=True)
        except Exception as e:
            print("[backup] failed:", e, flush=True)
        time.sleep(BACKUP_INTERVAL_HOURS * 3600)

if BACKUP_ENABLED:
    threading.Thread(target=_backup_loop, daemon=True).start()


# --------------------------------------------------------------------------
# Authentication (a signed cookie; password compared in constant time)
# --------------------------------------------------------------------------
def _make_token():
    ts = str(int(time.time()))
    sig = hmac.new(SECRET_KEY.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return ts + "." + sig

def _valid(token):
    try:
        ts, sig = token.split(".", 1)
    except ValueError:
        return False
    good = hmac.new(SECRET_KEY.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and (time.time() - int(ts)) < MAX_AGE

def require_auth(request: Request):
    if not _valid(request.cookies.get(COOKIE, "")):
        raise HTTPException(status_code=401, detail="login required")
    return True

@app.get("/")
def index():
    # Browsing and search are public; only adding a movie requires the password.
    return FileResponse(os.path.join(HERE, "index.html"))

@app.get("/api/auth")
def auth_status(request: Request):
    """Tell the page whether the current visitor may add movies."""
    return {"authed": _valid(request.cookies.get(COOKIE, ""))}

@app.post("/api/login")
def api_login(payload: dict = Body(...)):
    if hmac.compare_digest((payload.get("password") or ""), APP_PASSWORD):
        r = JSONResponse({"ok": True})
        r.set_cookie(COOKIE, _make_token(), httponly=True, samesite="lax", max_age=MAX_AGE)
        return r
    raise HTTPException(status_code=401, detail="incorrect password")

@app.post("/api/logout")
def api_logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE)
    return r

@app.post("/api/backup")
def api_backup(_: bool = Depends(require_auth)):
    if not BACKUP_ENABLED:
        raise HTTPException(status_code=400, detail="Dropbox backup isn't configured on the server.")
    try:
        return {"ok": True, "path": backup_to_dropbox()}
    except Exception as e:
        raise HTTPException(status_code=502, detail="Backup failed: " + str(e))


# --------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------
def hydrate(con, ids):
    """Turn a list of movie ids into full movie objects."""
    if not ids:
        return []
    qs = ",".join("?" * len(ids))
    movies = {r["id"]: {"id": r["id"], "title": r["title"], "year": r["release_year"],
                        "directors": [], "actors": [], "viewings": []}
              for r in con.execute(f"SELECT id,title,release_year FROM movies WHERE id IN ({qs})", ids)}
    for r in con.execute(f"""SELECT md.movie_id mid,d.name FROM movie_directors md
                             JOIN directors d ON d.id=md.director_id
                             WHERE md.movie_id IN ({qs}) ORDER BY d.name""", ids):
        movies[r["mid"]]["directors"].append(r["name"])
    for r in con.execute(f"""SELECT ma.movie_id mid,a.name FROM movie_actors ma
                             JOIN actors a ON a.id=ma.actor_id
                             WHERE ma.movie_id IN ({qs}) ORDER BY a.name""", ids):
        movies[r["mid"]]["actors"].append(r["name"])
    vmap = {}
    for r in con.execute(f"""SELECT id,movie_id,date_seen,location_seen,rating,notes
                             FROM viewings WHERE movie_id IN ({qs})""", ids):
        vw = {"date": r["date_seen"], "location": r["location_seen"],
              "rating": r["rating"], "notes": r["notes"], "friends": []}
        movies[r["movie_id"]]["viewings"].append(vw)
        vmap[r["id"]] = vw
    if vmap:
        vids = list(vmap); vqs = ",".join("?" * len(vids))
        for r in con.execute(f"""SELECT vf.viewing_id vid,f.name FROM viewing_friends vf
                                 JOIN friends f ON f.id=vf.friend_id
                                 WHERE vf.viewing_id IN ({vqs}) ORDER BY f.name""", vids):
            vmap[r["vid"]]["friends"].append(r["name"])
    out = list(movies.values())
    out.sort(key=lambda m: (m["title"] or "").lower())
    return out

def get_or_create(cur, table, name):
    row = cur.execute(f"SELECT id FROM {table} WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    cur.execute(f"INSERT INTO {table}(name) VALUES(?)", (name,))
    return cur.lastrowid


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.get("/api/facets")
def facets():
    con = db()
    def col(sql): return [r[0] for r in con.execute(sql)]
    out = {
        "actors":    col("SELECT name FROM actors ORDER BY name"),
        "directors": col("SELECT name FROM directors ORDER BY name"),
        "friends":   col("SELECT name FROM friends ORDER BY name"),
        "locations": col("SELECT DISTINCT location_seen FROM viewings WHERE location_seen IS NOT NULL ORDER BY location_seen"),
        "titles":    col("SELECT title FROM movies ORDER BY title"),
    }
    con.close()
    return out

@app.post("/api/search")
def search(payload: dict = Body(...)):
    """Combine one or more criteria — match 'all' (AND, default) or 'any' (OR)."""
    filters = payload.get("filters") or []
    match = (payload.get("match") or "all").lower()
    if not filters:
        return []
    con = db()

    def idset(f):
        mode = f.get("mode")
        like = "%" + (f.get("q", "") or "") + "%"
        if mode == "actor":
            sql = """SELECT DISTINCT m.id FROM movies m JOIN movie_actors ma ON ma.movie_id=m.id
                     JOIN actors a ON a.id=ma.actor_id WHERE a.name LIKE ?"""; p = (like,)
        elif mode == "director":
            sql = """SELECT DISTINCT m.id FROM movies m JOIN movie_directors md ON md.movie_id=m.id
                     JOIN directors d ON d.id=md.director_id WHERE d.name LIKE ?"""; p = (like,)
        elif mode == "friend":
            sql = """SELECT DISTINCT v.movie_id FROM viewings v JOIN viewing_friends vf ON vf.viewing_id=v.id
                     JOIN friends fr ON fr.id=vf.friend_id WHERE fr.name LIKE ?"""; p = (like,)
        elif mode == "location":
            sql = "SELECT DISTINCT movie_id FROM viewings WHERE location_seen LIKE ?"; p = (like,)
        elif mode == "title":
            sql = "SELECT id FROM movies WHERE title LIKE ?"; p = (like,)
        elif mode == "rating":
            op = {"gte": ">=", "lte": "<=", "eq": "="}.get(f.get("cmp"), ">=")
            sql = f"SELECT DISTINCT movie_id FROM viewings WHERE rating IS NOT NULL AND rating {op} ?"
            p = (float(f.get("val", 0)),)
        else:
            return None
        return set(r[0] for r in con.execute(sql, p))

    sets = [s for s in (idset(f) for f in filters) if s is not None]
    if not sets:
        result_ids = set()
    elif match == "any":
        result_ids = set().union(*sets)
    else:
        result_ids = set.intersection(*sets)
    out = hydrate(con, list(result_ids))
    con.close()
    return out

@app.post("/api/movies")
def add_movie(payload: dict = Body(...), _: bool = Depends(require_auth)):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    con = db(); cur = con.cursor()
    cur.execute("INSERT INTO movies(title,release_year) VALUES(?,?)", (title, payload.get("year")))
    mid = cur.lastrowid
    for d in payload.get("directors", []):
        if d.strip():
            cur.execute("INSERT OR IGNORE INTO movie_directors(movie_id,director_id) VALUES(?,?)",
                        (mid, get_or_create(cur, "directors", d.strip())))
    for a in payload.get("actors", []):
        if a.strip():
            cur.execute("INSERT OR IGNORE INTO movie_actors(movie_id,actor_id) VALUES(?,?)",
                        (mid, get_or_create(cur, "actors", a.strip())))
    v = payload.get("viewing", {}) or {}
    cur.execute("INSERT INTO viewings(movie_id,date_seen,location_seen,rating,notes) VALUES(?,?,?,?,?)",
                (mid, v.get("date"), v.get("location"), v.get("rating"), v.get("notes")))
    vid = cur.lastrowid
    for f in v.get("friends", []):
        if f.strip():
            cur.execute("INSERT OR IGNORE INTO viewing_friends(viewing_id,friend_id) VALUES(?,?)",
                        (vid, get_or_create(cur, "friends", f.strip())))
    con.commit(); con.close()
    return {"ok": True, "id": mid}

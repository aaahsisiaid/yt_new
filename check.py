"""
check.py  —  YT Watcher playlist checker
Runs every 10 min via GitHub Actions.
Reads playlists/subscriptions from Cloudflare Worker KV.
Sends Web Push notifications via pywebpush.
"""
import os, json, urllib.request
from pywebpush import webpush, WebPushException

YOUTUBE_API_KEY   = os.environ["YOUTUBE_API_KEY"]
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_EMAIL       = os.environ.get("VAPID_EMAIL", "mailto:a6068376@gmail.com")
WORKER_URL        = os.environ["WORKER_URL"].rstrip("/")
API_SECRET        = os.environ["API_SECRET"]

# Fallback: read playlists from env if Worker is unavailable
PLAYLISTS_FALLBACK = os.environ.get("PLAYLISTS_JSON", "[]")


def worker_get(path):
    url = f"{WORKER_URL}{path}?secret={API_SECRET}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "yt-watcher-check"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def yt_playlist_videos(playlist_id):
    videos, page_token = [], ""
    while True:
        url = (f"https://www.googleapis.com/youtube/v3/playlistItems"
               f"?part=snippet&maxResults=50&playlistId={playlist_id}&key={YOUTUBE_API_KEY}"
               + (f"&pageToken={page_token}" if page_token else ""))
        with urllib.request.urlopen(urllib.request.Request(url), timeout=20) as r:
            data = json.loads(r.read())
        for item in data.get("items", []):
            s   = item["snippet"]
            vid = s.get("resourceId", {}).get("videoId")
            if not vid or s["title"] in ("Deleted video", "Private video"):
                continue
            videos.append({"id": vid, "title": s["title"]})
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return videos


def send_push(sub, title, body, url=""):
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL},
        )
        print(f"    ✓ {sub['endpoint'][:60]}…")
        return True
    except WebPushException as e:
        resp = getattr(e, "response", None)
        code = resp.status_code if resp else 0
        print(f"    ✗ {code}: {str(e)[:80]}")
        return code != 410   # 410 Gone = subscription expired, remove it
    except Exception as e:
        print(f"    ✗ error: {e}")
        return True


def main():
    # ── Load state ────────────────────────────────────────────────────────────
    state = {}
    if os.path.exists("state.json"):
        try:
            with open("state.json") as f:
                state = json.load(f)
        except Exception:
            pass

    # ── Fetch playlists ───────────────────────────────────────────────────────
    try:
        playlists = worker_get("/playlists")
        print(f"[playlists] {len(playlists)} from Worker KV")
    except Exception as e:
        print(f"[playlists] Worker unreachable ({e}), using PLAYLISTS_JSON env")
        try:
            playlists = json.loads(PLAYLISTS_FALLBACK)
        except Exception:
            print("[error] Cannot load playlists")
            return

    # ── Fetch subscriptions ───────────────────────────────────────────────────
    try:
        subs = worker_get("/subscriptions")
        if not isinstance(subs, list):
            subs = []
        print(f"[subscriptions] {len(subs)} from Worker KV")
    except Exception as e:
        print(f"[subscriptions] error: {e}")
        subs = []

    if not subs:
        print("[skip] No subscribers — nothing to notify")
        # Still update state so we track new videos for when someone subscribes
    if not playlists:
        print("[skip] No playlists configured")
        return

    # ── Check each playlist ───────────────────────────────────────────────────
    for pl in playlists:
        pl_id    = pl.get("id", "")
        pl_title = pl.get("title", pl_id)
        if not pl_id:
            continue

        print(f"\n[playlist] {pl_title}  ({pl_id})")

        try:
            videos = yt_playlist_videos(pl_id)
        except Exception as e:
            print(f"  [error] {e}")
            continue

        known      = set(state.get(pl_id, []))
        new_videos = [v for v in videos if v["id"] not in known]
        print(f"  total={len(videos)}, known={len(known)}, new={len(new_videos)}")

        state[pl_id] = [v["id"] for v in videos]   # always update

        if not new_videos or not subs:
            continue

        for v in new_videos:
            print(f"  [new] {v['title']}")

        # ── Send push ─────────────────────────────────────────────────────────
        print(f"  [push] notifying {len(subs)} subscriber(s)…")

        # One notification per new video (max 3), then a summary
        notify_videos = new_videos[:3]
        for v in notify_videos:
            for sub in subs:
                send_push(
                    sub,
                    title=f"新着: {pl_title}",
                    body=v["title"],
                    url=f"https://www.youtube.com/watch?v={v['id']}",
                )

        if len(new_videos) > 3:
            for sub in subs:
                send_push(
                    sub,
                    title=f"{pl_title}: 他 {len(new_videos) - 3} 件の新着",
                    body="タップして確認",
                    url=f"https://www.youtube.com/playlist?list={pl_id}",
                )

    # ── Save state ────────────────────────────────────────────────────────────
    with open("state.json", "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("\n[state] saved")


if __name__ == "__main__":
    main()

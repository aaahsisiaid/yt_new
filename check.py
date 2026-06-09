import os,json,urllib.request,datetime
from pywebpush import webpush,WebPushException
YOUTUBE_API_KEY=os.environ["YOUTUBE_API_KEY"]
VAPID_PRIVATE_KEY=os.environ["VAPID_PRIVATE_KEY"]
VAPID_EMAIL=os.environ.get("VAPID_EMAIL","mailto:a6068376@gmail.com")
WORKER_URL=os.environ["WORKER_URL"].rstrip("/")
API_SECRET=os.environ["API_SECRET"]
PLAYLISTS_FALLBACK=os.environ.get("PLAYLISTS_JSON","[]")
def worker_get(path):
    url=f"{WORKER_URL}{path}?secret={API_SECRET}"
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"yt-watcher"})
    with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read())
def yt_playlist_videos(pl_id):
    videos,page_token=[],""
    while True:
        url=f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={pl_id}&key={YOUTUBE_API_KEY}"+(f"&pageToken={page_token}"if page_token else"")
        with urllib.request.urlopen(urllib.request.Request(url),timeout=20) as r: data=json.loads(r.read())
        for item in data.get("items",[]):
            s=item["snippet"];vid=s.get("resourceId",{}).get("videoId")
            if not vid or s["title"] in("Deleted video","Private video"):continue
            videos.append({"id":vid,"title":s["title"]})
        page_token=data.get("nextPageToken","")
        if not page_token: break
    return videos
def send_push(sub,title,body,url=""):
    try:
        webpush(subscription_info={"endpoint":sub["endpoint"],"keys":sub["keys"]},data=json.dumps({"title":title,"body":body,"url":url}),vapid_private_key=VAPID_PRIVATE_KEY,vapid_claims={"sub":VAPID_EMAIL})
        print(f"    sent → {sub['endpoint'][:55]}...")
    except WebPushException as e:
        resp=getattr(e,"response",None);code=resp.status_code if resp else 0
        print(f"    fail {code}: {str(e)[:60]}")
def push_all(subs,title,body,url=""):
    for sub in subs: send_push(sub,title,body,url)
def check_schedule_notifications(schedules,subs):
    if not schedules or not subs: return 0
    now_jst=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today=now_jst.strftime("%Y-%m-%d");now_min=now_jst.hour*60+now_jst.minute;sent=0
    for ev in schedules:
        if not ev.get("notify") or ev.get("date")!=today: continue
        start=ev.get("startTime","")
        if not start: continue
        try: h,m=map(int,start.split(":"))
        except: continue
        start_min=h*60+m
        for nb in ev.get("notifyBefore",[60,30,10]):
            diff=now_min-(start_min-nb)
            if 0<=diff<=2:
                title=f"まもなく開始: {ev.get('subject','')}"
                body=f"{ev.get('unit','')}  {start}開始  {nb}分前"
                link=ev.get("link",{}).get("url") or ev.get("zoomUrl","")
                print(f"  [sched] {title} — {body}")
                push_all(subs,title,body,link);sent+=1;break
    return sent
def main():
    state={}
    if os.path.exists("state.json"):
        try:
            with open("state.json") as f: state=json.load(f)
        except: pass
    try: subs=worker_get("/subscriptions");assert isinstance(subs,list);print(f"[subs] {len(subs)}件")
    except Exception as e: print(f"[subs] {e}");subs=[]
    try: playlists=worker_get("/playlists");print(f"[playlists] {len(playlists)}件")
    except Exception as e:
        print(f"[playlists] fallback: {e}")
        try: playlists=json.loads(PLAYLISTS_FALLBACK)
        except: playlists=[]
    try: schedules=worker_get("/schedules");assert isinstance(schedules,list);print(f"[schedules] {len(schedules)}件")
    except Exception as e: print(f"[schedules] {e}");schedules=[]
    for pl in playlists:
        pl_id=pl.get("id","");pl_title=pl.get("title",pl_id)
        if not pl_id: continue
        print(f"\n[playlist] {pl_title} ({pl_id})")
        try: videos=yt_playlist_videos(pl_id)
        except Exception as e: print(f"  error: {e}");continue
        known=set(state.get(pl_id,[]));new_videos=[v for v in videos if v["id"] not in known]
        print(f"  total={len(videos)}, known={len(known)}, new={len(new_videos)}")
        state[pl_id]=[v["id"] for v in videos]
        if not new_videos or not subs: continue
        for v in new_videos: print(f"  [new] {v['title']}")
        for v in new_videos[:3]: push_all(subs,f"新着: {pl_title}",v["title"],f"https://www.youtube.com/watch?v={v['id']}")
        if len(new_videos)>3: push_all(subs,f"{pl_title}: 他{len(new_videos)-3}件の新着","タップして確認",f"https://www.youtube.com/playlist?list={pl_id}")
    print("\n[schedule check]");n=check_schedule_notifications(schedules,subs);print(f"  {n}件送信")
    with open("state.json","w") as f: json.dump(state,f,ensure_ascii=False,indent=2)
    print("\n[done]")
if __name__=="__main__": main()

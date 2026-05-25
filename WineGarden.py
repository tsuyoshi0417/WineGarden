#!/usr/bin/python3
"""
WineGarden - Mac用Windowsエロゲランチャー（ブラウザUI版）
"""

import http.server
import json
import subprocess
import os
import shutil
import webbrowser
import threading
import time
import re
import mimetypes
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

APP_NAME  = "WineGarden"
PORT      = 8765
DATA_DIR  = Path.home() / ".winegarden"
GAMES_FILE    = DATA_DIR / "games.json"
BACKUP_DIR    = Path.home() / "Documents" / "ErogeBackup"
WINEPREFIX_BASE = Path.home() / ".wine_games"
ASSETS_DIR    = Path(__file__).parent / "assets"

WINE_CANDIDATES = [
    "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Devel.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Staging.app/Contents/Resources/wine/bin/wine",
    "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine",
    "/opt/homebrew/bin/wine",
    "/usr/local/bin/wine",
]

games = []
wine_path = None
running_processes = {}


def find_wine():
    for p in WINE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def load_games():
    global games
    if GAMES_FILE.exists():
        try:
            games = json.loads(GAMES_FILE.read_text(encoding="utf-8"))
        except Exception:
            games = []


def save_games():
    GAMES_FILE.write_text(
        json.dumps(games, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def detect_save_dir(exe_path):
    game_dir = Path(exe_path).parent
    for name in ["savedata", "save", "SaveData", "Save"]:
        p = game_dir / name
        if p.is_dir():
            return str(p)
    return str(game_dir)


def make_prefix_name(name):
    return re.sub(r"[^\w]", "_", name)[:32]


def setup_wineprefix(prefix_path, wine):
    prefix = Path(prefix_path)
    if (prefix / ".winegarden_init").exists():
        return
    env = {**os.environ, "WINEPREFIX": str(prefix_path),
           "WINEDEBUG": "-all", "LANG": "ja_JP.UTF-8"}
    subprocess.run([wine, "wineboot", "--init"],
                   env=env, capture_output=True, timeout=120)
    reg = ('REGEDIT4\n\n'
           '[HKEY_CURRENT_USER\\Software\\Wine\\Mac Driver]\n'
           '"RetinaMode"="Y"\n\n'
           '[HKEY_CURRENT_USER\\Control Panel\\International]\n'
           '"Locale"="00000411"\n"sLanguage"="JPN"\n')
    reg_file = prefix / "setup.reg"
    reg_file.write_text(reg)
    subprocess.run([wine, "regedit", "/S", str(reg_file)],
                   env=env, capture_output=True)
    font_dst = prefix / "drive_c" / "windows" / "Fonts"
    font_dst.mkdir(parents=True, exist_ok=True)
    for f in (Path.home() / "Library" / "Fonts").glob("GenJyuu*.ttf"):
        shutil.copy2(f, font_dst)
    (prefix / ".winegarden_init").touch()


# ── HTTP ハンドラー ────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        elif p.startswith("/assets/"):
            self._serve_asset(p[8:])
        elif p == "/api/games":
            self.send_json(games)
        elif p == "/api/status":
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
                s.close()
            except Exception:
                lan_ip = None
            self.send_json({
                "wine": wine_path,
                "wine_name": (Path(wine_path).parent.parent.parent.parent.parent.name
                              if wine_path else None),
                "running": {str(k): True for k, v in running_processes.items()
                            if v.poll() is None},
                "lan_ip": lan_ip,
                "port": PORT,
            })
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path
        data = self.read_json()

        # /api/games → ゲーム追加
        if p == "/api/games":
            self._add_game()
        # /api/games/N/action
        elif m := re.match(r"/api/games/(\d+)/(\w[\w-]*)$", p):
            idx, action = int(m.group(1)), m.group(2)
            if action == "launch":
                self._launch(idx)
            elif action == "backup":
                self._backup(idx)
            elif action == "open-save":
                subprocess.run(["open", detect_save_dir(games[idx]["exe_path"])])
                self.send_json({"ok": True})
            elif action == "cover":
                self._pick_cover(idx)
            elif action == "update":
                for key in ("name", "note", "display_size", "win_size"):
                    if key in data:
                        games[idx][key] = data[key]
                save_games()
                self.send_json({"ok": True})
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_DELETE(self):
        m = re.match(r"/api/games/(\d+)$", urlparse(self.path).path)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < len(games):
                games.pop(idx)
                save_games()
                self.send_json({"ok": True})
                return
        self.send_error(404)

    # ── ゲーム操作 ─────────────────────────────────────────────

    def _add_game(self):
        r = subprocess.run(
            ["osascript", "-e",
             'POSIX path of (choose file with prompt "ゲームの .exe を選択")'],
            capture_output=True, text=True)
        exe = r.stdout.strip()
        if not exe:
            self.send_json({"ok": False, "error": "キャンセルされました"})
            return
        name = Path(exe).stem
        game = {"name": name, "exe_path": exe, "cover_path": "",
                "note": "", "display_size": "retina",
                "prefix_name": make_prefix_name(name)}
        games.append(game)
        save_games()
        self.send_json({"ok": True, "index": len(games) - 1})

    def _launch(self, idx):
        if not wine_path:
            self.send_json({"ok": False, "error": "Wineが見つかりません"}); return
        if idx >= len(games):
            self.send_json({"ok": False, "error": "ゲームが見つかりません"}); return
        g = games[idx]
        if not os.path.isfile(g["exe_path"]):
            self.send_json({"ok": False,
                            "error": f"ファイルが見つかりません: {g['exe_path']}"}); return
        prefix = str(WINEPREFIX_BASE / g["prefix_name"])
        try:
            setup_wineprefix(prefix, wine_path)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}); return
        env = {**os.environ, "WINEPREFIX": prefix,
               "WINEDEBUG": "-all", "LANG": "ja_JP.UTF-8", "LC_ALL": "ja_JP.UTF-8"}
        # 拡大モード: 仮想デスクトップなし・RetinaMode外してMac解像度に合わせる
        if g.get("display_size") == "large":
            win_size = g.get("win_size", "1280x960")
            cmd = [wine_path, "explorer", f"/desktop=WineDesktop,{win_size}",
                   g["exe_path"]]
        else:
            cmd = [wine_path, g["exe_path"]]
        proc = subprocess.Popen(
            cmd, env=env,
            cwd=str(Path(g["exe_path"]).parent),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        running_processes[idx] = proc
        self.send_json({"ok": True, "pid": proc.pid})

    def _backup(self, idx):
        if idx >= len(games):
            self.send_json({"ok": False, "error": "ゲームが見つかりません"}); return
        g = games[idx]
        save_dir = Path(detect_save_dir(g["exe_path"]))
        if not save_dir.exists():
            self.send_json({"ok": False, "error": "セーブフォルダが見つかりません"}); return
        dest = BACKUP_DIR / g["name"] / datetime.now().strftime("%Y%m%d_%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(save_dir), str(dest / save_dir.name), dirs_exist_ok=True)
        self.send_json({"ok": True, "path": str(dest)})

    def _pick_cover(self, idx):
        r = subprocess.run(
            ["osascript", "-e",
             'POSIX path of (choose file with prompt "カバー画像を選択" of type {"png","jpg","jpeg"})'],
            capture_output=True, text=True)
        src = r.stdout.strip()
        if not src:
            self.send_json({"ok": False}); return
        g = games[idx]
        ext = Path(src).suffix
        dest = ASSETS_DIR / f"{g['prefix_name']}_cover{ext}"
        ASSETS_DIR.mkdir(exist_ok=True)
        shutil.copy2(src, dest)
        g["cover_path"] = str(dest)
        save_games()
        self.send_json({"ok": True, "filename": dest.name})

    def _serve_asset(self, filename):
        fp = ASSETS_DIR / filename
        if not fp.exists():
            self.send_error(404); return
        data = fp.read_bytes()
        mime = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)


# ── HTML ──────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>🌿 WineGarden</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#1a1a2e;--side:#16213e;--card:#0f3460;--acc:#e94560;--text:#eaeaea;--sub:#8899aa;--ok:#4ecca3}
body{background:var(--bg);color:var(--text);font-family:-apple-system,"Hiragino Sans",sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{background:var(--acc);padding:12px 20px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
header h1{font-size:18px;font-weight:700}
#ws{font-size:12px;opacity:.9}
.main{display:flex;flex:1;overflow:hidden}
.side{width:220px;background:var(--side);display:flex;flex-direction:column;flex-shrink:0}
.slabel{padding:12px 16px 6px;font-size:11px;color:var(--sub);text-transform:uppercase;letter-spacing:1px}
#glist{flex:1;overflow-y:auto}
.gi{padding:11px 16px;cursor:pointer;border-left:3px solid transparent;font-size:13px;transition:.15s}
.gi:hover{background:rgba(255,255,255,.05)}
.gi.active{background:rgba(233,69,96,.15);border-left-color:var(--acc);color:var(--acc)}
.sbtns{padding:10px;display:flex;gap:6px}
.sbtns button{flex:1;padding:8px;background:var(--card);color:var(--text);border:none;border-radius:6px;cursor:pointer;font-size:13px;transition:.15s}
.sbtns button:hover{background:#1a4a8a}
#detail{flex:1;overflow-y:auto;padding:24px}
.empty{height:100%;display:flex;align-items:center;justify-content:center;color:var(--sub);font-size:15px;flex-direction:column;gap:12px}
.ei{font-size:48px;opacity:.3}
.gh{display:flex;gap:20px;margin-bottom:20px}
.cw{width:140px;height:100px;background:var(--card);border-radius:8px;overflow:hidden;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center;position:relative;font-size:11px;color:var(--sub);text-align:center}
.cw img{width:100%;height:100%;object-fit:cover}
.gi2{flex:1}
.gname{font-size:20px;font-weight:700;margin-bottom:6px;background:transparent;border:none;color:var(--text);width:100%;outline:none}
.gname:focus{border-bottom:1px solid var(--acc)}
.gmeta{font-size:11px;color:var(--sub);line-height:2}
.szo{margin-top:10px;display:flex;gap:14px}
.szo label{font-size:12px;display:flex;align-items:center;gap:5px;cursor:pointer}
.blaunch{width:100%;padding:14px;background:var(--acc);color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;margin-bottom:10px;transition:.15s}
.blaunch:hover{background:#ff6b6b}
.blaunch:disabled{background:#555;cursor:not-allowed}
.blaunch.run{background:var(--ok);color:#111}
.sbts{display:flex;gap:8px;margin-bottom:16px}
.bsub{flex:1;padding:10px;background:var(--card);color:var(--text);border:none;border-radius:6px;cursor:pointer;font-size:13px;transition:.15s}
.bsub:hover{background:#1a4a8a}
.nlabel{font-size:11px;color:var(--sub);margin-bottom:6px}
.note{width:100%;background:var(--card);color:var(--text);border:none;border-radius:6px;padding:10px;font-size:13px;font-family:inherit;resize:vertical;min-height:70px}
.note:focus{outline:1px solid var(--acc)}
.sbar{text-align:center;font-size:12px;color:var(--sub);margin-top:12px}
.sbar.run{color:var(--ok)}
.toast{position:fixed;bottom:20px;right:20px;background:var(--card);color:var(--text);padding:12px 18px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .3s;pointer-events:none}
.toast.show{opacity:1}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-thumb{background:var(--card);border-radius:3px}
</style>
</head>
<body>
<header>
  <h1>🌿 WineGarden</h1>
  <div style="text-align:right">
    <div id="ws">確認中...</div>
    <div id="mobile" style="font-size:11px;opacity:.7"></div>
  </div>
</header>
<div class="main">
  <div class="side">
    <div class="slabel">ライブラリ</div>
    <div id="glist"></div>
    <div class="sbtns">
      <button onclick="addGame()">＋ 追加</button>
      <button onclick="removeGame()">－ 削除</button>
    </div>
  </div>
  <div id="detail">
    <div class="empty"><div class="ei">🎮</div><div>ゲームを選択するか「＋ 追加」で登録</div></div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
let games=[],sel=null;
async function init(){await load();await poll();setInterval(poll,3000)}
async function load(){const r=await fetch('/api/games');games=await r.json();renderList();if(sel!==null&&sel<games.length)renderDetail(sel)}
async function poll(){
  const r=await fetch('/api/status'),s=await r.json();
  const w=document.getElementById('ws');
  w.textContent=s.wine?`Wine: ${s.wine_name} ✓`:'Wine: 未検出 ⚠';
  const mi=document.getElementById('mobile');
  if(mi&&s.lan_ip)mi.textContent=`📱 http://${s.lan_ip}:${s.port}`;
  if(sel!==null){
    const b=document.getElementById('lb');
    const sb=document.getElementById('sb');
    if(b){const run=s.running&&s.running[String(sel)];
      b.textContent=run?'▶ 実行中...':'▶  ゲームを起動';
      b.className='blaunch'+(run?' run':'');
      if(sb){sb.textContent=run?'状態: 実行中 ▶':'状態: 待機中';sb.className='sbar'+(run?' run':'');}
    }
  }
}
function renderList(){
  const el=document.getElementById('glist');el.innerHTML='';
  games.forEach((g,i)=>{const d=document.createElement('div');d.className='gi'+(i===sel?' active':'');d.textContent=g.name;d.onclick=()=>select(i);el.appendChild(d)});
}
function select(i){sel=i;renderList();renderDetail(i)}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function renderDetail(i){
  const g=games[i];
  const cov=g.cover_path?`<img src="/assets/${esc(g.cover_path.split('/').pop())}">`:'📷<br>クリックで<br>画像設定';
  document.getElementById('detail').innerHTML=`
    <div class="gh">
      <div class="cw" onclick="pickCover(${i})">${cov}</div>
      <div class="gi2">
        <input class="gname" value="${esc(g.name)}" onblur="updName(${i},this.value)" onkeydown="if(event.key==='Enter')this.blur()">
        <div class="gmeta">📁 ${esc(g.exe_path)}<br>🍷 ${esc(g.prefix_name)}</div>
        <div class="szo">
          <label><input type="radio" name="sz" value="retina" ${g.display_size!=='large'?'checked':''} onchange="updSize(${i},'retina')"> 標準（カーソル正確）</label>
          <label><input type="radio" name="sz" value="large" ${g.display_size==='large'?'checked':''} onchange="updSize(${i},'large')"> 拡大（仮想デスクトップ）</label>
        </div>
        <div id="szopt" style="display:${g.display_size==='large'?'flex':'none'};gap:6px;align-items:center;margin-top:6px;font-size:12px">
          幅<input id="sw" type="number" value="${(g.win_size||'1280x960').split('x')[0]}" min="640" max="3840" style="width:70px;background:#0f3460;color:#eaeaea;border:1px solid #8899aa;border-radius:4px;padding:3px;font-size:12px">
          ×
          高さ<input id="sh" type="number" value="${(g.win_size||'1280x960').split('x')[1]}" min="480" max="2160" style="width:70px;background:#0f3460;color:#eaeaea;border:1px solid #8899aa;border-radius:4px;padding:3px;font-size:12px">
          <button onclick="saveWinSize(${i})" style="background:#e94560;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;font-size:12px">適用</button>
        </div>
      </div>
    </div>
    <button class="blaunch" id="lb" onclick="launch(${i})">▶  ゲームを起動</button>
    <div class="sbts">
      <button class="bsub" onclick="openSave(${i})">📁 セーブフォルダ</button>
      <button class="bsub" onclick="backup(${i})">💾 バックアップ</button>
    </div>
    <div class="nlabel">メモ（動作状況など）</div>
    <textarea class="note" onblur="updNote(${i},this.value)">${esc(g.note)}</textarea>
    <div class="sbar" id="sb">状態: 待機中</div>
  `;
}
async function addGame(){
  toast('ファイルを選択してください...');
  const r=await fetch('/api/games',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();
  if(d.ok){await load();select(d.index);toast('ゲームを追加しました')}
  else if(d.error)toast(d.error);
}
async function removeGame(){
  if(sel===null)return;
  if(!confirm(`「${games[sel].name}」を削除しますか？`))return;
  await fetch(`/api/games/${sel}`,{method:'DELETE'});
  sel=null;document.getElementById('detail').innerHTML='<div class="empty"><div class="ei">🎮</div><div>ゲームを選択するか「＋ 追加」で登録</div></div>';
  await load();
}
async function launch(i){
  const b=document.getElementById('lb');b.disabled=true;b.textContent='起動中...';
  const r=await fetch(`/api/games/${i}/launch`,{method:'POST'});
  const d=await r.json();b.disabled=false;b.textContent='▶  ゲームを起動';
  d.ok?toast('起動しました'):toast('エラー: '+(d.error||'失敗'));
}
async function backup(i){
  toast('バックアップ中...');
  const r=await fetch(`/api/games/${i}/backup`,{method:'POST'});
  const d=await r.json();
  d.ok?toast('✓ バックアップ完了'):toast('エラー: '+(d.error||'失敗'));
}
async function openSave(i){await fetch(`/api/games/${i}/open-save`,{method:'POST'})}
async function pickCover(i){
  const r=await fetch(`/api/games/${i}/cover`,{method:'POST'});
  const d=await r.json();
  if(d.ok){await load();renderDetail(i);}
}
async function updNote(i,v){games[i].note=v;await fetch(`/api/games/${i}/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:v})})}
async function updName(i,v){if(!v.trim())return;games[i].name=v.trim();await fetch(`/api/games/${i}/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:v.trim()})});renderList()}
async function updSize(i,v){
  games[i].display_size=v;
  await fetch(`/api/games/${i}/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_size:v})});
  const o=document.getElementById('szopt');if(o)o.style.display=v==='large'?'flex':'none';
}
async function saveWinSize(i){
  const w=document.getElementById('sw').value;
  const h=document.getElementById('sh').value;
  const sz=w+'x'+h;
  games[i].win_size=sz;
  await fetch(`/api/games/${i}/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({win_size:sz})});
  toast('サイズを '+sz+' に設定しました');
}
let tt;function toast(m){const e=document.getElementById('toast');e.textContent=m;e.classList.add('show');clearTimeout(tt);tt=setTimeout(()=>e.classList.remove('show'),2500)}
init();
</script>
</body>
</html>"""


# ── エントリーポイント ─────────────────────────────────────────

def main():
    global wine_path
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WINEPREFIX_BASE.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    load_games()
    wine_path = find_wine()

    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(
        target=lambda: (time.sleep(0.6), webbrowser.open(f"http://localhost:{PORT}")),
        daemon=True
    ).start()

    # LAN IPアドレスを取得して表示
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "不明"

    print(f"🌿 WineGarden → http://localhost:{PORT}")
    print(f"📱 スマホからアクセス → http://{lan_ip}:{PORT}  (同じWiFiが必要)")
    print("終了: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました")


if __name__ == "__main__":
    main()

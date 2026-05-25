#!/usr/bin/python3
"""
WineGarden - Mac用Windowsエロゲランチャー
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import subprocess
import os
import shutil
from datetime import datetime
from pathlib import Path

APP_NAME = "WineGarden"
GAMES_FILE = Path.home() / ".winegarden" / "games.json"
BACKUP_DIR = Path.home() / "Documents" / "ErogeBackup"
WINEPREFIX_BASE = Path.home() / ".wine_games"
ASSETS_DIR = Path(__file__).parent / "assets"

WINE_CANDIDATES = [
    "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Devel.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Staging.app/Contents/Resources/wine/bin/wine",
    "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine",
    "/opt/homebrew/bin/wine",
    "/usr/local/bin/wine",
]

COLORS = {
    "bg": "#1a1a2e",
    "sidebar": "#16213e",
    "card": "#0f3460",
    "accent": "#e94560",
    "text": "#eaeaea",
    "subtext": "#a0a0b0",
    "success": "#4ecca3",
    "button": "#e94560",
    "button_hover": "#ff6b6b",
}


def find_wine():
    for path in WINE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def detect_save_dir(exe_path):
    """exeと同階層のsavedataフォルダを探す"""
    game_dir = Path(exe_path).parent
    for candidate in ["savedata", "save", "SaveData", "Save"]:
        p = game_dir / candidate
        if p.is_dir():
            return str(p)
    return str(game_dir)


def setup_wineprefix(prefix_path, wine_path):
    """WINEPREFIXを初期化してRetina/日本語設定を適用"""
    prefix = Path(prefix_path)
    marker = prefix / ".winegarden_init"
    if marker.exists():
        return

    env = {**os.environ, "WINEPREFIX": prefix_path, "WINEDEBUG": "-all",
           "LANG": "ja_JP.UTF-8"}

    subprocess.run([wine_path, "wineboot", "--init"], env=env,
                   capture_output=True, timeout=120)

    # Retina対応カーソル修正
    reg_content = """REGEDIT4

[HKEY_CURRENT_USER\\Software\\Wine\\Mac Driver]
"RetinaMode"="Y"

[HKEY_CURRENT_USER\\Control Panel\\International]
"Locale"="00000411"
"sLanguage"="JPN"

[HKEY_LOCAL_MACHINE\\System\\CurrentControlSet\\Control\\Nls\\Language]
"Default"="0411"
"InstallLanguage"="0411"
"""
    reg_file = prefix / "winegarden_setup.reg"
    reg_file.write_text(reg_content)
    subprocess.run([wine_path, "regedit", "/S", str(reg_file)],
                   env=env, capture_output=True)

    # 日本語フォントをコピー
    font_src = Path.home() / "Library" / "Fonts"
    font_dst = prefix / "drive_c" / "windows" / "Fonts"
    font_dst.mkdir(parents=True, exist_ok=True)
    for font_file in font_src.glob("GenJyuu*.ttf"):
        shutil.copy2(font_file, font_dst)

    marker.touch()


class GameCard:
    def __init__(self, name, exe_path, cover_path="", note="",
                 display_size="retina", prefix_name=""):
        self.name = name
        self.exe_path = exe_path
        self.cover_path = cover_path
        self.note = note
        self.display_size = display_size
        self.prefix_name = prefix_name or self._make_prefix_name(name)

    def _make_prefix_name(self, name):
        import re
        return re.sub(r"[^\w]", "_", name)[:32]

    def prefix_path(self):
        return str(WINEPREFIX_BASE / self.prefix_name)

    def to_dict(self):
        return {
            "name": self.name,
            "exe_path": self.exe_path,
            "cover_path": self.cover_path,
            "note": self.note,
            "display_size": self.display_size,
            "prefix_name": self.prefix_name,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


class WineGardenApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("820x560")
        self.root.resizable(False, False)
        self.root.configure(bg=COLORS["bg"])

        self.games = []
        self.selected_index = None
        self.wine_path = find_wine()
        self.process = None
        self.cover_image = None

        GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        WINEPREFIX_BASE.mkdir(parents=True, exist_ok=True)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._load_games()

    # ── UI構築 ──────────────────────────────────────────────

    def _build_ui(self):
        # タイトルバー
        title_frame = tk.Frame(self.root, bg=COLORS["accent"], height=44)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text=f"🌿 {APP_NAME}",
                 bg=COLORS["accent"], fg="white",
                 font=("Helvetica", 16, "bold")).pack(side="left", padx=16, pady=8)

        wine_status = f"Wine: {Path(self.wine_path).parent.parent.parent.parent.name}" \
            if self.wine_path else "Wine: 未検出 ⚠"
        tk.Label(title_frame, text=wine_status,
                 bg=COLORS["accent"], fg="white",
                 font=("Helvetica", 11)).pack(side="right", padx=16)

        # メインエリア
        main = tk.Frame(self.root, bg=COLORS["bg"])
        main.pack(fill="both", expand=True)

        self._build_sidebar(main)
        self._build_detail(main)

    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=COLORS["sidebar"], width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="ゲームライブラリ",
                 bg=COLORS["sidebar"], fg=COLORS["subtext"],
                 font=("Helvetica", 10)).pack(pady=(12, 4), padx=12, anchor="w")

        list_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        list_frame.pack(fill="both", expand=True, padx=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.game_listbox = tk.Listbox(
            list_frame, bg=COLORS["sidebar"], fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground="white",
            font=("Helvetica", 12), relief="flat", bd=0,
            highlightthickness=0, yscrollcommand=scrollbar.set,
            activestyle="none"
        )
        scrollbar.config(command=self.game_listbox.yview)
        self.game_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.game_listbox.bind("<<ListboxSelect>>", self._on_select)

        btn_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        btn_frame.pack(fill="x", padx=8, pady=8)
        tk.Button(btn_frame, text="＋ 追加", command=self._add_game,
                  bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                  font=("Helvetica", 11), cursor="hand2").pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(btn_frame, text="－ 削除", command=self._remove_game,
                  bg=COLORS["card"], fg=COLORS["subtext"], relief="flat",
                  font=("Helvetica", 11), cursor="hand2").pack(side="right", fill="x", expand=True, padx=(2, 0))

    def _build_detail(self, parent):
        self.detail = tk.Frame(parent, bg=COLORS["bg"])
        self.detail.pack(side="left", fill="both", expand=True)

        self._show_empty_detail()

    def _show_empty_detail(self):
        for w in self.detail.winfo_children():
            w.destroy()
        tk.Label(self.detail,
                 text="← ゲームを選択するか\n「＋ 追加」で登録してください",
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=("Helvetica", 14)).place(relx=0.5, rely=0.5, anchor="center")

    def _build_game_detail(self, game: GameCard):
        for w in self.detail.winfo_children():
            w.destroy()

        # 上段: カバー画像 + 基本情報
        top = tk.Frame(self.detail, bg=COLORS["bg"])
        top.pack(fill="x", padx=20, pady=16)

        # カバー画像
        self.cover_label = tk.Label(top, bg=COLORS["card"], width=12, height=7,
                                    text="画像なし", fg=COLORS["subtext"],
                                    font=("Helvetica", 10), cursor="hand2")
        self.cover_label.pack(side="left")
        self.cover_label.bind("<Button-1>", lambda e: self._pick_cover(game))
        self._load_cover(game)

        # 基本情報
        info = tk.Frame(top, bg=COLORS["bg"])
        info.pack(side="left", fill="both", expand=True, padx=16)

        tk.Label(info, text=game.name, bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Helvetica", 18, "bold"), anchor="w").pack(fill="x")

        tk.Label(info, text=game.exe_path, bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=("Helvetica", 9), anchor="w", wraplength=360).pack(fill="x", pady=(4, 0))

        wine_txt = Path(self.wine_path).parent.parent.parent.parent.name \
            if self.wine_path else "Wine未検出"
        tk.Label(info, text=f"Wine: {wine_txt}  |  Prefix: {game.prefix_name}",
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=("Helvetica", 9), anchor="w").pack(fill="x")

        # 画面サイズ
        size_frame = tk.Frame(info, bg=COLORS["bg"])
        size_frame.pack(fill="x", pady=(8, 0))
        tk.Label(size_frame, text="表示サイズ:", bg=COLORS["bg"],
                 fg=COLORS["text"], font=("Helvetica", 10)).pack(side="left")
        self.size_var = tk.StringVar(value=game.display_size)
        for val, label in [("retina", "標準 (Retina精細)"), ("large", "拡大 (スペースを拡大設定時)")]:
            tk.Radiobutton(size_frame, text=label, variable=self.size_var,
                           value=val, bg=COLORS["bg"], fg=COLORS["text"],
                           selectcolor=COLORS["card"], activebackground=COLORS["bg"],
                           font=("Helvetica", 10),
                           command=lambda g=game: self._update_size(g)).pack(side="left", padx=8)

        # メモ
        tk.Label(self.detail, text="メモ（動作状況など）",
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=("Helvetica", 10), anchor="w").pack(fill="x", padx=20)
        self.note_text = tk.Text(self.detail, height=3, bg=COLORS["card"],
                                 fg=COLORS["text"], font=("Helvetica", 11),
                                 relief="flat", bd=8, insertbackground="white")
        self.note_text.pack(fill="x", padx=20)
        self.note_text.insert("1.0", game.note)
        self.note_text.bind("<FocusOut>", lambda e, g=game: self._save_note(g))

        # アクションボタン
        action = tk.Frame(self.detail, bg=COLORS["bg"])
        action.pack(fill="x", padx=20, pady=12)

        self.launch_btn = tk.Button(
            action, text="▶  ゲームを起動", command=lambda: self._launch(game),
            bg=COLORS["button"], fg="white", font=("Helvetica", 14, "bold"),
            relief="flat", padx=20, pady=10, cursor="hand2",
            activebackground=COLORS["button_hover"], activeforeground="white"
        )
        self.launch_btn.pack(fill="x", pady=(0, 8))

        sub_btn = tk.Frame(action, bg=COLORS["bg"])
        sub_btn.pack(fill="x")
        tk.Button(sub_btn, text="📁 セーブフォルダを開く",
                  command=lambda: self._open_save_folder(game),
                  bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                  font=("Helvetica", 11), cursor="hand2",
                  pady=6).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(sub_btn, text="💾 バックアップ",
                  command=lambda: self._backup(game),
                  bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                  font=("Helvetica", 11), cursor="hand2",
                  pady=6).pack(side="right", fill="x", expand=True, padx=(4, 0))

        # ステータス
        self.status_label = tk.Label(self.detail, text="状態: 待機中",
                                     bg=COLORS["bg"], fg=COLORS["subtext"],
                                     font=("Helvetica", 10))
        self.status_label.pack(pady=(4, 0))

    # ── ゲーム操作 ─────────────────────────────────────────

    def _add_game(self):
        exe = filedialog.askopenfilename(
            title="ゲームの .exe ファイルを選択",
            filetypes=[("実行ファイル", "*.exe"), ("全てのファイル", "*.*")]
        )
        if not exe:
            return
        name = Path(exe).stem
        game = GameCard(name=name, exe_path=exe)
        self.games.append(game)
        self.game_listbox.insert("end", f"  {game.name}")
        self._save_games()
        self.game_listbox.selection_clear(0, "end")
        self.game_listbox.selection_set("end")
        self._on_select()

    def _remove_game(self):
        if self.selected_index is None:
            return
        game = self.games[self.selected_index]
        if not messagebox.askyesno("削除確認", f"「{game.name}」をリストから削除しますか？\n（ゲームファイルは削除されません）"):
            return
        self.games.pop(self.selected_index)
        self.game_listbox.delete(self.selected_index)
        self.selected_index = None
        self._show_empty_detail()
        self._save_games()

    def _on_select(self, event=None):
        sel = self.game_listbox.curselection()
        if not sel:
            return
        self.selected_index = sel[0]
        self._build_game_detail(self.games[self.selected_index])

    def _launch(self, game: GameCard):
        if not self.wine_path:
            messagebox.showerror("エラー", "Wineが見つかりません。\nWine StableをApplicationsフォルダに入れてください。")
            return
        if not os.path.isfile(game.exe_path):
            messagebox.showerror("エラー", f"ゲームファイルが見つかりません:\n{game.exe_path}")
            return

        self.status_label.config(text="状態: セットアップ中...", fg=COLORS["subtext"])
        self.launch_btn.config(state="disabled", text="起動中...")
        self.root.update()

        try:
            setup_wineprefix(game.prefix_path(), self.wine_path)
        except Exception as e:
            self.status_label.config(text=f"セットアップエラー: {e}", fg=COLORS["accent"])
            self.launch_btn.config(state="normal", text="▶  ゲームを起動")
            return

        env = {
            **os.environ,
            "WINEPREFIX": game.prefix_path(),
            "WINEDEBUG": "-all",
            "LANG": "ja_JP.UTF-8",
            "LC_ALL": "ja_JP.UTF-8",
        }

        cmd = [self.wine_path, game.exe_path]
        game_dir = str(Path(game.exe_path).parent)

        self.process = subprocess.Popen(cmd, env=env, cwd=game_dir,
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        self.status_label.config(text="状態: 実行中 ▶", fg=COLORS["success"])
        self.launch_btn.config(state="normal", text="▶  ゲームを起動")
        self._monitor_process()

    def _monitor_process(self):
        if self.process and self.process.poll() is not None:
            self.status_label.config(text="状態: 終了しました", fg=COLORS["subtext"])
            self.process = None
        elif self.process:
            self.root.after(2000, self._monitor_process)

    def _open_save_folder(self, game: GameCard):
        save_dir = detect_save_dir(game.exe_path)
        subprocess.run(["open", save_dir])

    def _backup(self, game: GameCard):
        save_dir = Path(detect_save_dir(game.exe_path))
        if not save_dir.exists():
            messagebox.showinfo("情報", "セーブフォルダが見つかりませんでした。")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / game.name / timestamp
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(save_dir), str(dest / save_dir.name),
                        dirs_exist_ok=True)
        messagebox.showinfo("バックアップ完了",
                            f"保存先:\n{dest}")

    def _pick_cover(self, game: GameCard):
        path = filedialog.askopenfilename(
            title="カバー画像を選択",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.gif *.bmp"), ("全て", "*.*")]
        )
        if not path:
            return
        ext = Path(path).suffix
        dest = ASSETS_DIR / f"{game.prefix_name}_cover{ext}"
        shutil.copy2(path, dest)
        game.cover_path = str(dest)
        self._save_games()
        self._load_cover(game)

    def _load_cover(self, game: GameCard):
        try:
            from PIL import Image, ImageTk
            if game.cover_path and Path(game.cover_path).exists():
                img = Image.open(game.cover_path).resize((130, 90))
                self.cover_image = ImageTk.PhotoImage(img)
                self.cover_label.config(image=self.cover_image, text="")
                return
        except ImportError:
            pass
        self.cover_label.config(image="", text="画像なし\n(クリックで設定)", width=16, height=5)

    def _update_size(self, game: GameCard):
        game.display_size = self.size_var.get()
        self._save_games()

    def _save_note(self, game: GameCard):
        game.note = self.note_text.get("1.0", "end-1c")
        self._save_games()

    # ── データ永続化 ──────────────────────────────────────

    def _save_games(self):
        data = [g.to_dict() for g in self.games]
        GAMES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load_games(self):
        if not GAMES_FILE.exists():
            return
        try:
            data = json.loads(GAMES_FILE.read_text())
            self.games = [GameCard.from_dict(d) for d in data]
            for g in self.games:
                self.game_listbox.insert("end", f"  {g.name}")
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = WineGardenApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

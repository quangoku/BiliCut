"""
BiliCut GUI – Dark-themed Tkinter interface with persistent settings
"""

import os
import json
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# ──────────────────────────────────────────────
# PERSISTENT SETTINGS
# ──────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, ".bilicut_settings.json")

DEFAULT_SETTINGS = {
    "capcut_draft_dir": os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "CapCut", "UserData", "Projects", "com.lveditor.draft"
    ),
    "model":              "small",
    "language":           "Auto detect",
    "enable_translation": False,
    "gemini_api_key":     "",
}


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(cfg: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ──────────────────────────────────────────────
# PALETTE
# ──────────────────────────────────────────────
BG       = "#0f1117"
SURFACE  = "#1a1d27"
SURFACE2 = "#22263a"
BORDER   = "#2e3350"
ACCENT   = "#6c63ff"
ACCENT_H = "#857dff"
SUCCESS  = "#43e97b"
ERROR    = "#ff5252"
TEXT     = "#e8eaf6"
DIM      = "#7b82a8"
MONO     = ("Consolas", 9)
SANS     = ("Segoe UI", 10)
SANS_B   = ("Segoe UI Semibold", 11)

MODELS = ["tiny", "base", "small", "medium", "large"]
LANGUAGES = [
    ("Auto detect", None), ("Chinese (zh)", "zh"), ("English (en)", "en"),
    ("Japanese (ja)", "ja"), ("Korean (ko)", "ko"), ("Vietnamese (vi)", "vi"),
    ("French (fr)", "fr"), ("German (de)", "de"), ("Spanish (es)", "es"),
]


# ──────────────────────────────────────────────
# WIDGET HELPERS
# ──────────────────────────────────────────────

def make_btn(parent, text, cmd, bg=ACCENT, fg="white", **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                  relief="flat", font=SANS_B, padx=14, pady=7,
                  activebackground=ACCENT_H, activeforeground="white",
                  cursor="hand2", bd=0, **kw)
    b.bind("<Enter>", lambda _: b.config(bg=ACCENT_H))
    b.bind("<Leave>", lambda _: b.config(bg=bg))
    return b


def make_lf(parent, title, bg=SURFACE):
    return tk.LabelFrame(parent, text=f"  {title}  ",
                         bg=bg, fg=DIM, font=SANS,
                         bd=1, relief="solid", padx=10, pady=8,
                         labelanchor="nw")


def make_entry(parent, var):
    return tk.Entry(parent, textvariable=var, bg=SURFACE2, fg=TEXT,
                    insertbackground=TEXT, relief="flat", font=SANS, bd=0,
                    highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=ACCENT)


def browse_row(parent, var, mode="file"):
    row = tk.Frame(parent, bg=SURFACE)
    e = make_entry(row, var)
    e.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))

    def _browse():
        if mode == "file":
            p = filedialog.askopenfilename(
                title="Select video file",
                filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm"),
                           ("All", "*.*")])
        else:
            p = filedialog.askdirectory(title="Select CapCut draft folder")
        if p:
            var.set(os.path.abspath(p))

    b = make_btn(row, "Browse...", _browse, bg=SURFACE2, fg=TEXT)
    b.config(pady=4, padx=10)
    b.pack(side="right")
    return row


# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────

class BiliCutApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg  = load_settings()
        self._setup_window()
        self._build_ui()
        self._load_into_ui()

    # ── window ──────────────────────────────
    def _setup_window(self):
        self.root.title("BiliCut  -  Video > SRT > CapCut")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(660, 560)
        w, h = 760, 660
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        s = ttk.Style()
        s.theme_use("clam")
        s.configure("D.TCombobox",
                    fieldbackground=SURFACE2, background=SURFACE2,
                    foreground=TEXT, selectbackground=ACCENT,
                    selectforeground="white", arrowcolor=DIM,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        s.configure("TProgressbar",
                    troughcolor=BORDER, background=ACCENT, thickness=6)

    # ── build UI ───────────────────────────
    def _build_ui(self):
        # ── scroll canvas ──
        c = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(self.root, orient="vertical", command=c.yview)
        c.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        c.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(c, bg=BG)
        win = c.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _: c.configure(scrollregion=c.bbox("all")))
        c.bind("<Configure>", lambda e: c.itemconfig(win, width=e.width))
        c.bind_all("<MouseWheel>", lambda e: c.yview_scroll(int(-e.delta/120), "units"))

        # ── header ──
        hdr = tk.Frame(inner, bg=SURFACE, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="BiliCut", fg=TEXT,
                 bg=SURFACE, font=("Segoe UI Semibold", 16)).pack(side="left", padx=20)
        tk.Label(hdr, text="Video  >  SRT  >  CapCut Draft",
                 fg=DIM, bg=SURFACE, font=SANS).pack(side="left")
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(inner, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        # ── video file ──
        vf = make_lf(body, "Video File")
        vf.pack(fill="x", pady=(0, 10))
        self.var_video = tk.StringVar()
        browse_row(vf, self.var_video, mode="file").pack(fill="x")

        # ── draft folder (auto-saved) ──
        df = make_lf(body, "CapCut Draft Folder  ( auto-saved )")
        df.pack(fill="x", pady=(0, 10))
        self.var_draft = tk.StringVar()
        self.var_draft.trace_add("write", self._on_draft_changed)
        browse_row(df, self.var_draft, mode="dir").pack(fill="x")
        self._saved_lbl = tk.Label(df, text="", fg=SUCCESS, bg=SURFACE, font=SANS)
        self._saved_lbl.pack(anchor="e")

        # ── model + language ──
        row_ml = tk.Frame(body, bg=BG)
        row_ml.pack(fill="x", pady=(0, 10))

        mf = make_lf(row_ml, "Whisper Model")
        mf.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.var_model = tk.StringVar(value="small")
        ttk.Combobox(mf, textvariable=self.var_model, values=MODELS,
                     state="readonly", style="D.TCombobox",
                     font=SANS, width=10).pack(fill="x", ipady=4)

        lf = make_lf(row_ml, "Language")
        lf.pack(side="left", fill="x", expand=True)
        self.lang_labels = [l for l, _ in LANGUAGES]
        self.lang_codes  = [c for _, c in LANGUAGES]
        self.var_lang = tk.StringVar(value=self.lang_labels[0])
        ttk.Combobox(lf, textvariable=self.var_lang,
                     values=self.lang_labels, state="readonly",
                     style="D.TCombobox", font=SANS,
                     width=16).pack(fill="x", ipady=4)

        # ── Gemini Translation ──
        gf = make_lf(body, "🤖  Gemini Translation (SRT → Tiếng Việt)")
        gf.pack(fill="x", pady=(0, 10))

        row_g1 = tk.Frame(gf, bg=SURFACE)
        row_g1.pack(fill="x", pady=(0, 6))
        self.var_translate = tk.BooleanVar(value=False)
        chk_trans = tk.Checkbutton(
            row_g1, text="Dịch phụ đề SRT sang tiếng Việt (bằng Gemini API)",
            variable=self.var_translate, bg=SURFACE, fg=TEXT,
            selectcolor=SURFACE2, activebackground=SURFACE,
            activeforeground=TEXT, font=SANS, cursor="hand2",
            command=self._toggle_translation,
        )
        chk_trans.pack(side="left")

        self.row_g2 = tk.Frame(gf, bg=SURFACE)
        self.row_g2.pack(fill="x")
        tk.Label(self.row_g2, text="Gemini API Key:", fg=TEXT, bg=SURFACE, font=SANS).pack(side="left", padx=(0, 8))
        self.var_gemini_key = tk.StringVar()
        e_key = tk.Entry(self.row_g2, textvariable=self.var_gemini_key, bg=SURFACE2, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=SANS, bd=0, show="*",
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        e_key.pack(side="left", fill="x", expand=True, ipady=4)

        # ── start button ──
        self.btn = make_btn(body, "Start Pipeline", self._start)
        self.btn.pack(fill="x", pady=(6, 8), ipady=6)

        # ── progress ──
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))

        # ── log ──
        lf2 = make_lf(body, "Log")
        lf2.pack(fill="both", expand=True)
        self.log_box = tk.Text(lf2, bg=SURFACE2, fg=TEXT, font=MONO,
                               relief="flat", wrap="word", state="disabled",
                               bd=0, height=10)
        scr = tk.Scrollbar(lf2, command=self.log_box.yview, bg=SURFACE2)
        self.log_box.configure(yscrollcommand=scr.set)
        scr.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True)

        for tag, fg in [("acc", ACCENT), ("ok", SUCCESS), ("err", ERROR), ("dim", DIM)]:
            self.log_box.tag_configure(tag, foreground=fg)

        self._write_log("Welcome to BiliCut! Fill in the fields and hit Start.", "dim")

    # ── load settings into widgets ──────────
    def _load_into_ui(self):
        self.var_draft.set(self.cfg.get("capcut_draft_dir", ""))
        self.var_model.set(self.cfg.get("model", "small"))
        self.var_lang.set(self.cfg.get("language", "Auto detect"))
        self.var_translate.set(self.cfg.get("enable_translation", False))
        self.var_gemini_key.set(self.cfg.get("gemini_api_key", ""))
        self._toggle_translation()

    # ── translation toggle ───────────
    def _toggle_translation(self):
        st = "normal" if self.var_translate.get() else "disabled"
        for w in self.row_g2.winfo_children():
            try: w.config(state=st)
            except Exception: pass

    # ── auto-save draft folder ──────────────
    def _on_draft_changed(self, *_):
        val = self.var_draft.get().strip()
        if val:
            self.cfg["capcut_draft_dir"] = val
            save_settings(self.cfg)
            self._saved_lbl.config(text="Saved")
            self.root.after(2000, lambda: self._saved_lbl.config(text=""))

    # ── log helpers ─────────────────────────
    def _write_log(self, msg: str, tag: str = ""):
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n", tag)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.root.after(0, _do)

    def _log_fn(self, *args, **_):
        msg = " ".join(str(a) for a in args)
        low = msg.lower()
        tag = ("ok"  if "done" in low or "thành công" in low else
               "err" if "error" in low or "lỗi" in low or "not found" in low else
               "acc" if msg.startswith("[") or "===" in msg else "")
        self._write_log(msg, tag)

    def _set_busy(self, busy: bool):
        def _do():
            if busy:
                self.btn.config(state="disabled", text="Running...")
                self.progress.start(10)
            else:
                self.btn.config(state="normal", text="Start Pipeline")
                self.progress.stop()
        self.root.after(0, _do)

    # ── start ───────────────────────────────
    def _start(self):
        video        = self.var_video.get().strip()
        draft_dir    = self.var_draft.get().strip()
        model        = self.var_model.get()
        lang_lbl     = self.var_lang.get()
        lang         = self.lang_codes[self.lang_labels.index(lang_lbl)]
        enable_trans = self.var_translate.get()
        gemini_key   = self.var_gemini_key.get().strip()

        if not video:
            messagebox.showerror("Missing", "Please select a video file!"); return
        if not os.path.isfile(video):
            messagebox.showerror("Not found", f"File not found:\n{video}"); return
        if not draft_dir:
            messagebox.showerror("Missing", "Please select the CapCut draft folder!"); return
        if enable_trans and not gemini_key:
            messagebox.showerror("Missing", "Vui lòng nhập Gemini API Key để dịch sang tiếng Việt!"); return

        # Save model/language/translation preference
        self.cfg.update({
            "model":              model,
            "language":           lang_lbl,
            "enable_translation": enable_trans,
            "gemini_api_key":     gemini_key,
        })
        save_settings(self.cfg)

        # Clear log
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        self._set_busy(True)

        def _run():
            try:
                from main import run_pipeline
                run_pipeline(
                    video_path=video,
                    capcut_draft_dir=draft_dir,
                    model_name=model,
                    language=lang,
                    n_threads=8,
                    enable_translation=enable_trans,
                    gemini_api_key=gemini_key,
                    log=self._log_fn,
                )
                self.root.after(0, lambda: messagebox.showinfo(
                    "Done", "CapCut draft created!\nOpen CapCut to check."))
            except Exception as e:
                msg = str(e)
                self._log_fn(f"[ERROR] {msg}")
                self.root.after(0, lambda: messagebox.showerror("Error", msg))
            finally:
                self._set_busy(False)

        threading.Thread(target=_run, daemon=True).start()


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    BiliCutApp(root)
    root.mainloop()

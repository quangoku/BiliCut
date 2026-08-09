"""
BiliCut GUI – Dark-themed Tkinter interface with persistent settings
"""

import os
import json
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk, messagebox

# ──────────────────────────────────────────────
# PERSISTENT SETTINGS
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_APP_DATA = os.environ.get(
    "LOCALAPPDATA",
    os.path.join(os.path.expanduser("~"), "AppData", "Local"),
)
APP_DATA_DIR = os.path.join(LOCAL_APP_DATA, "BiliCut")
SETTINGS_FILE = os.path.join(APP_DATA_DIR, ".bilicut_settings.json")
LEGACY_SETTINGS_FILE = os.path.join(BASE_DIR, ".bilicut_settings.json")


def resource_path(*parts) -> str:
    """Resolve bundled assets in source, PyInstaller onedir, and onefile modes."""
    bundle_dir = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(bundle_dir, *parts)


def set_windows_app_id():
    """Give Windows a stable identity so the taskbar uses BiliCut's icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "BiliCut.VideoSubtitleTool.1"
        )
    except (AttributeError, OSError):
        pass

DEFAULT_SETTINGS = {
    "video_path":         "",
    "capcut_draft_dir": os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "CapCut", "UserData", "Projects", "com.lveditor.draft"
    ),
    "model":              "small",
    "language":           "Tiếng Trung",
    "aspect_ratio":       "9:16",
    "mirror_video":       False,
    "logo_enabled":       False,
    "logo_path":          "",
    "logo_position":      "top_right",
    "logo_scale":         0.20,
    "enable_translation": False,
    "gemini_api_key":     "",
    "enable_tts":         False,
    "tts_voice":          "BV421_vivn_streaming",
    "tts_speed":          1.0,
    "tts_auto_fit":       True,
    "tts_allow_overlap":  True,
    "source_volume":      100.0,
    "text_color":         "#ffffff",
    "text_size":          7.0,
    "text_bold":          True,
    "stroke_enabled":     True,
    "stroke_color":       "#000000",
    "stroke_width":       40.0,
    "stroke_alpha":       1.0,
    "shadow_enabled":     False,
    "background_enabled": False,
    "background_color":   "#000000",
    "background_alpha":   0.65,
}


def load_settings() -> dict:
    settings_path = SETTINGS_FILE
    if not os.path.isfile(settings_path) and os.path.isfile(LEGACY_SETTINGS_FILE):
        settings_path = LEGACY_SETTINGS_FILE

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = {**DEFAULT_SETTINGS, **json.load(f)}

        # Migrate settings created by older versions beside the executable.
        if settings_path == LEGACY_SETTINGS_FILE:
            save_settings(settings)
        return settings
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(cfg: dict) -> None:
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
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
DIM      = "#9298b8"
MUTED    = "#626985"
MONO     = ("Consolas", 9)
SANS     = ("Segoe UI", 10)
SANS_B   = ("Segoe UI Semibold", 11)

MODELS = ["tiny", "base", "small", "medium", "large"]
LANGUAGES = [
    ("Tiếng Trung", "zh"),
    ("Tiếng Anh", "en"),
]

ASPECT_RATIOS = [
    ("9:16 · Dọc", "9:16"),
    ("16:9 · Ngang", "16:9"),
]

LOGO_POSITIONS = [
    ("Góc trên trái", "top_left"),
    ("Góc trên phải", "top_right"),
    ("Góc dưới trái", "bottom_left"),
    ("Góc dưới phải", "bottom_right"),
]

TTS_VOICES = [
    ("Nhỏ Ngọt Ngào (Nữ - Tiếng Việt)", "BV421_vivn_streaming"),
    ("Giọng Nữ Phổ Thông (Tiếng Việt)", "vi_female_huong"),
    ("Cô Gái Hoạt Ngôn (Nữ - Tiếng Việt)", "BV074_streaming"),
    ("Hoài Mỹ (Nữ - Tiếng Việt)", "vi-VN-HoaiMyNeural"),
    ("Nam Minh (Nam - Tiếng Việt)", "vi-VN-NamMinhNeural"),
    ("Review Phim New (Nữ - Tiếng Việt)", "multi_female_richgirl_uranus_bigtts"),
    ("Bản Tin 1 (Nữ - Tiếng Việt)", "multi_female_quanweinv_uranus_bigtts"),
    ("Review Phim 4 (Nữ - Tiếng Việt)", "multi_female_stokie_uranus_bigtts"),
    ("Ban Mai (Nữ - Tiếng Việt)", "multi_female_yangguangnv_uranus_bigtts"),
    ("Giọng Bé (Tiếng Việt)", "BV074_streaming_dsp"),
    ("Việt Méo (Tiếng Việt)", "BV075_streaming_vibrato_dsp"),
    ("Mai (Nữ - Tiếng Việt)", "BV562_streaming"),
]


# ──────────────────────────────────────────────
# WIDGET HELPERS
# ──────────────────────────────────────────────

def make_btn(parent, text, cmd, bg=ACCENT, fg="white", **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                  relief="flat", font=SANS_B, padx=14, pady=7,
                  activebackground=ACCENT_H, activeforeground="white",
                  cursor="hand2", bd=0, **kw)
    b.normal_bg = bg
    b.bind("<Enter>", lambda _: b.config(bg=ACCENT_H) if b["state"] != "disabled" else None)
    b.bind("<Leave>", lambda _: b.config(bg=b.normal_bg) if b["state"] != "disabled" else None)
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
                title="Chọn video nguồn",
                filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm"),
                           ("Tất cả tệp", "*.*")])
        elif mode == "image":
            p = filedialog.askopenfilename(
                title="Chọn ảnh logo",
                filetypes=[("Ảnh logo", "*.png *.jpg *.jpeg *.webp *.bmp"),
                           ("Tất cả tệp", "*.*")])
        else:
            p = filedialog.askdirectory(title="Chọn thư mục draft của CapCut")
        if p:
            var.set(os.path.abspath(p))

    b = make_btn(row, "Chọn...", _browse, bg=SURFACE2, fg=TEXT)
    b.config(pady=4, padx=10)
    b.pack(side="right")
    return row


def make_section_title(parent, step: str, title: str, description: str):
    """Create a compact section heading with a numbered step badge."""
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=(4, 8))
    tk.Label(row, text=step, bg=ACCENT, fg="white",
             font=("Segoe UI Semibold", 9), padx=8, pady=3).pack(side="left")
    text = tk.Frame(row, bg=BG)
    text.pack(side="left", fill="x", expand=True, padx=(10, 0))
    tk.Label(text, text=title, bg=BG, fg=TEXT,
             font=("Segoe UI Semibold", 12)).pack(anchor="w")
    tk.Label(text, text=description, bg=BG, fg=DIM,
             font=("Segoe UI", 9)).pack(anchor="w")


def make_color_picker(parent, variable):
    """Create a compact color swatch that stores colors as #RRGGBB."""
    row = tk.Frame(parent, bg=SURFACE)
    swatch = tk.Label(row, bg=variable.get(), width=3, relief="solid", bd=1)
    swatch.pack(side="left", ipady=4, padx=(0, 6))

    def choose_color():
        _, color = colorchooser.askcolor(variable.get(), parent=parent)
        if color:
            variable.set(color.lower())

    make_btn(row, "Chọn màu", choose_color, bg=SURFACE2, fg=TEXT).pack(side="left")
    variable.trace_add("write", lambda *_: swatch.config(bg=variable.get()))
    return row


# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────

class BiliCutApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg  = load_settings()
        self.cancel_event = threading.Event()
        set_windows_app_id()
        self._setup_window()
        self._build_ui()
        self._load_into_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── window ──────────────────────────────
    def _setup_window(self):
        self.root.title("BiliCut — Tạo phụ đề và draft CapCut")
        self.root.configure(bg=BG)
        icon_path = resource_path("assets", "icon.ico")
        if os.path.isfile(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except tk.TclError:
                pass
        self.root.resizable(True, True)
        self.root.minsize(720, 640)
        w, h = 820, 760
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        s = ttk.Style()
        s.theme_use("clam")
        s.configure("D.TCombobox",
                    fieldbackground=SURFACE2, background=SURFACE2,
                    foreground=TEXT, selectbackground=ACCENT,
                    selectforeground="white", arrowcolor=DIM,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    insertcolor=TEXT, padding=6)
        s.map(
            "D.TCombobox",
            fieldbackground=[("readonly", SURFACE2), ("disabled", SURFACE)],
            foreground=[("readonly", TEXT), ("disabled", MUTED)],
            background=[("readonly", SURFACE2), ("active", BORDER)],
            arrowcolor=[("readonly", TEXT), ("active", "white")],
            selectbackground=[("readonly", SURFACE2)],
            selectforeground=[("readonly", TEXT)],
        )

        # ttk does not style the drop-down Listbox through Style on Windows.
        self.root.option_add("*TCombobox*Listbox.background", SURFACE2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font", SANS)
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
        hdr = tk.Frame(inner, bg=SURFACE, pady=14)
        hdr.pack(fill="x")
        brand = tk.Frame(hdr, bg=SURFACE)
        brand.pack(side="left", padx=20)
        tk.Label(brand, text="BiliCut", fg=TEXT, bg=SURFACE,
                 font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(brand, text="Video  →  Phụ đề  →  Draft CapCut",
                 fg=DIM, bg=SURFACE, font=("Segoe UI", 9)).pack(anchor="w")
        self.status_badge = tk.Label(hdr, text="Sẵn sàng", fg=SUCCESS,
                                     bg=SURFACE2, font=("Segoe UI Semibold", 9),
                                     padx=12, pady=6)
        self.status_badge.pack(side="right", padx=20)
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(inner, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        make_section_title(body, "1", "Chọn nguồn", "Chọn video và nơi lưu draft trong CapCut")

        # ── video file ──
        vf = make_lf(body, "Video nguồn")
        vf.pack(fill="x", pady=(0, 10))
        self.var_video = tk.StringVar()
        browse_row(vf, self.var_video, mode="file").pack(fill="x")

        # ── draft folder (auto-saved) ──
        df = make_lf(body, "Thư mục draft CapCut")
        df.pack(fill="x", pady=(0, 10))
        self.var_draft = tk.StringVar()
        self.var_draft.trace_add("write", self._on_draft_changed)
        browse_row(df, self.var_draft, mode="dir").pack(fill="x")
        self._saved_lbl = tk.Label(df, text="Tự động ghi nhớ thư mục này", fg=MUTED,
                                   bg=SURFACE, font=("Segoe UI", 8))
        self._saved_lbl.pack(anchor="e")

        make_section_title(body, "2", "Thiết lập xử lý", "Chọn cách nhận diện, dịch và tạo giọng đọc")

        # ── model + language ──
        row_ml = tk.Frame(body, bg=BG)
        row_ml.pack(fill="x", pady=(0, 10))

        mf = make_lf(row_ml, "Độ chính xác nhận diện")
        mf.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.var_model = tk.StringVar(value="small")
        self.model_combo = ttk.Combobox(
            mf, textvariable=self.var_model, values=MODELS,
            state="readonly", style="D.TCombobox", font=SANS, width=10,
        )
        self.model_combo.pack(fill="x", ipady=4)
        self.model_combo.bind("<<ComboboxSelected>>", self._refresh_model_status)
        self.model_status_lbl = tk.Label(
            mf, text="", bg=SURFACE, fg=MUTED, font=("Segoe UI", 8),
        )
        self.model_status_lbl.pack(anchor="w", pady=(4, 0))

        lf = make_lf(row_ml, "Ngôn ngữ video")
        lf.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.lang_labels = [l for l, _ in LANGUAGES]
        self.lang_codes  = [c for _, c in LANGUAGES]
        self.var_lang = tk.StringVar(value=self.lang_labels[0])
        ttk.Combobox(lf, textvariable=self.var_lang,
                     values=self.lang_labels, state="readonly",
                     style="D.TCombobox", font=SANS,
                     width=16).pack(fill="x", ipady=4)

        rf = make_lf(row_ml, "Tỷ lệ khung hình")
        rf.pack(side="left", fill="x", expand=True)
        self.ratio_labels = [label for label, _ in ASPECT_RATIOS]
        self.ratio_codes = [code for _, code in ASPECT_RATIOS]
        self.var_ratio = tk.StringVar(value=self.ratio_labels[0])
        ttk.Combobox(rf, textvariable=self.var_ratio,
                     values=self.ratio_labels, state="readonly",
                     style="D.TCombobox", font=SANS,
                     width=14).pack(fill="x", ipady=4)

        # ── Gemini Translation ──
        gf = make_lf(body, "Dịch phụ đề")
        gf.pack(fill="x", pady=(0, 10))

        row_g1 = tk.Frame(gf, bg=SURFACE)
        row_g1.pack(fill="x", pady=(0, 6))
        self.var_translate = tk.BooleanVar(value=False)
        chk_trans = tk.Checkbutton(
            row_g1, text="Dịch phụ đề sang tiếng Việt bằng Gemini",
            variable=self.var_translate, bg=SURFACE, fg=TEXT,
            selectcolor=SURFACE2, activebackground=SURFACE,
            activeforeground=TEXT, font=SANS, cursor="hand2",
            command=self._toggle_translation,
        )
        chk_trans.pack(side="left")

        self.row_g2 = tk.Frame(gf, bg=SURFACE)
        tk.Label(self.row_g2, text="API key", fg=TEXT, bg=SURFACE, font=SANS).pack(side="left", padx=(0, 8))
        self.var_gemini_key = tk.StringVar()
        e_key = tk.Entry(self.row_g2, textvariable=self.var_gemini_key, bg=SURFACE2, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=SANS, bd=0, show="*",
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        e_key.pack(side="left", fill="x", expand=True, ipady=4)
        tk.Label(gf, text="API key được dùng để gọi Gemini khi chạy.", fg=MUTED,
                 bg=SURFACE, font=("Segoe UI", 8)).pack(anchor="w")

        # ── CapCut TTS Speech ──
        tf = make_lf(body, "Giọng đọc AI")
        tf.pack(fill="x", pady=(0, 10))

        row_t1 = tk.Frame(tf, bg=SURFACE)
        row_t1.pack(fill="x", pady=(0, 6))
        self.var_tts_enable = tk.BooleanVar(value=False)
        chk_tts = tk.Checkbutton(
            row_t1, text="Tạo giọng đọc từ nội dung phụ đề",
            variable=self.var_tts_enable, bg=SURFACE, fg=TEXT,
            selectcolor=SURFACE2, activebackground=SURFACE,
            activeforeground=TEXT, font=SANS, cursor="hand2",
            command=self._toggle_tts,
        )
        chk_tts.pack(side="left")

        self.row_t2 = tk.Frame(tf, bg=SURFACE)
        tk.Label(self.row_t2, text="Chọn giọng", fg=TEXT, bg=SURFACE, font=SANS).pack(side="left", padx=(0, 8))
        self.tts_labels = [l for l, _ in TTS_VOICES]
        self.tts_codes  = [c for _, c in TTS_VOICES]
        self.var_tts_voice_lbl = tk.StringVar(value=self.tts_labels[0])
        ttk.Combobox(self.row_t2, textvariable=self.var_tts_voice_lbl,
                     values=self.tts_labels, state="readonly",
                     style="D.TCombobox", font=SANS, width=24).pack(side="left", fill="x", expand=True, ipady=4)
        tk.Label(self.row_t2, text="Tốc độ", fg=TEXT, bg=SURFACE,
                 font=SANS).pack(side="left", padx=(14, 6))
        self.var_tts_speed = tk.DoubleVar(value=1.0)
        tk.Spinbox(self.row_t2, from_=0.5, to=2.0, increment=0.05,
                   textvariable=self.var_tts_speed, width=6, bg=SURFACE2, fg=TEXT,
                   buttonbackground=BORDER, insertbackground=TEXT, relief="flat",
                   font=SANS).pack(side="left", ipady=4)
        tk.Label(self.row_t2, text="×", fg=DIM, bg=SURFACE,
                 font=SANS).pack(side="left", padx=(4, 0))

        self.row_t3 = tk.Frame(tf, bg=SURFACE)
        self.var_tts_auto_fit = tk.BooleanVar(value=True)
        tk.Checkbutton(self.row_t3, text="Tự tăng tốc để khớp phụ đề",
                       variable=self.var_tts_auto_fit, bg=SURFACE, fg=TEXT,
                       selectcolor=SURFACE2, activebackground=SURFACE,
                       activeforeground=TEXT, font=SANS).pack(side="left", padx=(0, 12))
        self.var_tts_allow_overlap = tk.BooleanVar(value=True)
        tk.Checkbutton(self.row_t3, text="Cho phép chồng tiếng, giữ đúng timestamp",
                       variable=self.var_tts_allow_overlap, bg=SURFACE, fg=TEXT,
                       selectcolor=SURFACE2, activebackground=SURFACE,
                       activeforeground=TEXT, font=SANS).pack(side="left", padx=(0, 12))
        tk.Label(self.row_t3, text="Âm thanh gốc", fg=TEXT, bg=SURFACE,
                 font=SANS).pack(side="left")
        self.var_source_volume = tk.DoubleVar(value=100.0)
        tk.Spinbox(self.row_t3, from_=0.0, to=100.0, increment=5.0,
                   textvariable=self.var_source_volume, width=5, bg=SURFACE2, fg=TEXT,
                   buttonbackground=BORDER, insertbackground=TEXT, relief="flat",
                   font=SANS).pack(side="left", padx=(6, 3), ipady=4)
        tk.Label(self.row_t3, text="%", fg=DIM, bg=SURFACE,
                 font=SANS).pack(side="left")

        # ── Video enhancements ──
        vf2 = make_lf(body, "Logo kênh và hướng video")
        vf2.pack(fill="x", pady=(0, 10))
        feature_row = tk.Frame(vf2, bg=SURFACE)
        feature_row.pack(fill="x", pady=(0, 6))
        self.var_mirror_video = tk.BooleanVar(value=False)
        tk.Checkbutton(feature_row, text="Lật ngang video (trái ↔ phải)",
                       variable=self.var_mirror_video, bg=SURFACE, fg=TEXT,
                       selectcolor=SURFACE2, activebackground=SURFACE,
                       activeforeground=TEXT, font=SANS).pack(side="left", padx=(0, 18))
        self.var_logo_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(feature_row, text="Thêm logo kênh", variable=self.var_logo_enabled,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=SURFACE, activeforeground=TEXT,
                       command=self._toggle_logo, font=SANS).pack(side="left")

        self.row_logo = tk.Frame(vf2, bg=SURFACE)
        self.var_logo_path = tk.StringVar()
        browse_row(self.row_logo, self.var_logo_path, mode="image").pack(
            side="left", fill="x", expand=True, padx=(0, 10))
        self.logo_position_labels = [label for label, _ in LOGO_POSITIONS]
        self.logo_position_codes = [code for _, code in LOGO_POSITIONS]
        self.var_logo_position = tk.StringVar(value=self.logo_position_labels[1])
        ttk.Combobox(self.row_logo, textvariable=self.var_logo_position,
                     values=self.logo_position_labels, state="readonly",
                     style="D.TCombobox", font=SANS, width=17).pack(side="left")
        tk.Label(self.row_logo, text="Kích thước", bg=SURFACE, fg=TEXT,
                 font=SANS).pack(side="left", padx=(10, 5))
        self.var_logo_scale = tk.DoubleVar(value=20.0)
        tk.Spinbox(self.row_logo, from_=5.0, to=50.0, increment=1.0,
                   textvariable=self.var_logo_scale, width=5, bg=SURFACE2, fg=TEXT,
                   buttonbackground=BORDER, insertbackground=TEXT, relief="flat",
                   font=SANS).pack(side="left", ipady=4)
        tk.Label(self.row_logo, text="%", bg=SURFACE, fg=DIM,
                 font=SANS).pack(side="left", padx=(3, 0))

        # ── Subtitle style ──
        sf = make_lf(body, "Kiểu chữ phụ đề")
        sf.pack(fill="x", pady=(0, 10))

        style_row = tk.Frame(sf, bg=SURFACE)
        style_row.pack(fill="x", pady=(0, 7))
        tk.Label(style_row, text="Màu chữ", bg=SURFACE, fg=TEXT, font=SANS).pack(side="left")
        self.var_text_color = tk.StringVar(value="#ffffff")
        make_color_picker(style_row, self.var_text_color).pack(side="left", padx=(8, 18))
        tk.Label(style_row, text="Cỡ chữ", bg=SURFACE, fg=TEXT, font=SANS).pack(side="left")
        self.var_text_size = tk.DoubleVar(value=7.0)
        tk.Spinbox(style_row, from_=4.0, to=30.0, increment=0.5,
                   textvariable=self.var_text_size, width=6, bg=SURFACE2, fg=TEXT,
                   buttonbackground=BORDER, insertbackground=TEXT, relief="flat",
                   font=SANS).pack(side="left", padx=(8, 18), ipady=4)
        self.var_text_bold = tk.BooleanVar(value=True)
        tk.Checkbutton(style_row, text="In đậm", variable=self.var_text_bold,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=SURFACE, activeforeground=TEXT,
                       font=SANS).pack(side="left")

        border_row = tk.Frame(sf, bg=SURFACE)
        border_row.pack(fill="x")
        self.var_stroke_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(border_row, text="Viền chữ", variable=self.var_stroke_enabled,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=SURFACE, activeforeground=TEXT,
                       font=SANS).pack(side="left")
        self.var_stroke_color = tk.StringVar(value="#000000")
        make_color_picker(border_row, self.var_stroke_color).pack(side="left", padx=(8, 18))
        tk.Label(border_row, text="Độ dày", bg=SURFACE, fg=TEXT, font=SANS).pack(side="left")
        self.var_stroke_width = tk.DoubleVar(value=40.0)
        tk.Spinbox(border_row, from_=0.0, to=100.0, increment=5.0,
                   textvariable=self.var_stroke_width, width=6, bg=SURFACE2, fg=TEXT,
                   buttonbackground=BORDER, insertbackground=TEXT, relief="flat",
                   font=SANS).pack(side="left", padx=(8, 18), ipady=4)
        self.var_shadow_enabled = tk.BooleanVar(value=False)
        tk.Label(border_row, text="Bóng: chưa hỗ trợ", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 12))
        self.var_background_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(border_row, text="Nền tối", variable=self.var_background_enabled,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=SURFACE, activeforeground=TEXT,
                       font=SANS).pack(side="left")

        make_section_title(body, "3", "Tạo draft", "BiliCut sẽ xử lý và đưa kết quả vào CapCut")

        # ── start / cancel buttons ──
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", pady=(6, 8))

        self.btn_start = make_btn(btn_row, "Tạo draft CapCut", self._start)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=6)

        self.btn_cancel = make_btn(btn_row, "Hủy", self._cancel, bg=SURFACE2, fg=ERROR)
        self.btn_cancel.config(state="disabled")
        self.btn_cancel.pack(side="right", ipady=6, padx=(0, 0))

        # ── progress ──
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))

        # ── log ──
        lf2 = make_lf(body, "Chi tiết xử lý")
        lf2.pack(fill="both", expand=True)
        self.log_box = tk.Text(lf2, bg=SURFACE2, fg=TEXT, font=MONO,
                               relief="flat", wrap="word", state="disabled",
                               bd=0, height=8)
        scr = tk.Scrollbar(lf2, command=self.log_box.yview, bg=SURFACE2)
        self.log_box.configure(yscrollcommand=scr.set)
        scr.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True)

        for tag, fg in [("acc", ACCENT), ("ok", SUCCESS), ("err", ERROR), ("dim", DIM)]:
            self.log_box.tag_configure(tag, foreground=fg)

        self._write_log("Sẵn sàng. Hãy chọn video để bắt đầu.", "dim")

    # ── load settings into widgets ──────────
    def _load_into_ui(self):
        self.var_video.set(self.cfg.get("video_path", ""))
        self.var_draft.set(self.cfg.get("capcut_draft_dir", ""))
        saved_model = self.cfg.get("model", "small")
        self.var_model.set(saved_model if saved_model in MODELS else "small")
        self._refresh_model_status()
        saved_lang = self.cfg.get("language", "Tiếng Trung")
        legacy_languages = {
            "Chinese (zh)": "Tiếng Trung",
            "English (en)": "Tiếng Anh",
        }
        saved_lang = legacy_languages.get(saved_lang, saved_lang)
        self.var_lang.set(saved_lang if saved_lang in self.lang_labels else "Tiếng Trung")
        saved_ratio = self.cfg.get("aspect_ratio", "9:16")
        if saved_ratio in self.ratio_codes:
            self.var_ratio.set(self.ratio_labels[self.ratio_codes.index(saved_ratio)])
        self.var_mirror_video.set(self.cfg.get("mirror_video", False))
        self.var_logo_enabled.set(self.cfg.get("logo_enabled", False))
        self.var_logo_path.set(self.cfg.get("logo_path", ""))
        saved_logo_position = self.cfg.get("logo_position", "top_right")
        if saved_logo_position in self.logo_position_codes:
            index = self.logo_position_codes.index(saved_logo_position)
            self.var_logo_position.set(self.logo_position_labels[index])
        self.var_logo_scale.set(float(self.cfg.get("logo_scale", 0.20)) * 100.0)
        self._toggle_logo()
        self.var_translate.set(self.cfg.get("enable_translation", False))
        self.var_gemini_key.set(self.cfg.get("gemini_api_key", ""))
        self._toggle_translation()

        self.var_tts_enable.set(self.cfg.get("enable_tts", False))
        saved_voice_code = self.cfg.get("tts_voice", "BV421_vivn_streaming")
        if saved_voice_code in self.tts_codes:
            idx = self.tts_codes.index(saved_voice_code)
            self.var_tts_voice_lbl.set(self.tts_labels[idx])
        self.var_tts_speed.set(self.cfg.get("tts_speed", 1.0))
        self.var_tts_auto_fit.set(self.cfg.get("tts_auto_fit", True))
        self.var_tts_allow_overlap.set(self.cfg.get("tts_allow_overlap", True))
        self.var_source_volume.set(self.cfg.get("source_volume", 100.0))
        self._toggle_tts()

        self.var_text_color.set(self.cfg.get("text_color", "#ffffff"))
        self.var_text_size.set(self.cfg.get("text_size", 7.0))
        self.var_text_bold.set(self.cfg.get("text_bold", True))
        self.var_stroke_enabled.set(self.cfg.get("stroke_enabled", True))
        self.var_stroke_color.set(self.cfg.get("stroke_color", "#000000"))
        self.var_stroke_width.set(self.cfg.get("stroke_width", 40.0))
        self.var_shadow_enabled.set(False)
        self.var_background_enabled.set(self.cfg.get("background_enabled", False))

    # ── toggles ───────────
    def _model_is_installed(self, model=None):
        from main import MODELS_DIR

        model = model or self.var_model.get()
        return os.path.isfile(os.path.join(MODELS_DIR, f"ggml-{model}.bin"))

    def _refresh_model_status(self, *_):
        if self._model_is_installed():
            self.model_status_lbl.config(text="Đã cài đặt · sẵn sàng sử dụng", fg=SUCCESS)
        else:
            self.model_status_lbl.config(
                text="Chưa cài · sẽ tự động tải khi bắt đầu", fg=DIM,
            )

    def _toggle_translation(self):
        if self.var_translate.get():
            self.row_g2.pack(fill="x", pady=(0, 4))
        else:
            self.row_g2.pack_forget()

    def _toggle_tts(self):
        if self.var_tts_enable.get():
            self.row_t2.pack(fill="x", pady=(0, 4))
            self.row_t3.pack(fill="x", pady=(0, 4))
        else:
            self.row_t2.pack_forget()
            self.row_t3.pack_forget()

    def _toggle_logo(self):
        if self.var_logo_enabled.get():
            self.row_logo.pack(fill="x", pady=(0, 4))
        else:
            self.row_logo.pack_forget()

    # ── auto-save draft folder ──────────────
    def _on_draft_changed(self, *_):
        val = self.var_draft.get().strip()
        if val:
            self.cfg["capcut_draft_dir"] = val
            save_settings(self.cfg)
            self._saved_lbl.config(text="Đã ghi nhớ", fg=SUCCESS)
            self.root.after(2000, lambda: self._saved_lbl.config(
                text="Tự động ghi nhớ thư mục này", fg=MUTED))

    def _save_current_settings(self):
        """Persist every user-selectable option, including selections not yet run."""
        try:
            text_size = float(self.var_text_size.get())
        except (tk.TclError, ValueError):
            text_size = self.cfg.get("text_size", 7.0)
        try:
            stroke_width = float(self.var_stroke_width.get())
        except (tk.TclError, ValueError):
            stroke_width = self.cfg.get("stroke_width", 40.0)
        try:
            tts_speed = float(self.var_tts_speed.get())
        except (tk.TclError, ValueError):
            tts_speed = self.cfg.get("tts_speed", 1.0)
        try:
            source_volume = float(self.var_source_volume.get())
        except (tk.TclError, ValueError):
            source_volume = self.cfg.get("source_volume", 100.0)
        try:
            logo_scale = float(self.var_logo_scale.get()) / 100.0
        except (tk.TclError, ValueError):
            logo_scale = self.cfg.get("logo_scale", 0.20)

        lang_label = self.var_lang.get()
        ratio_label = self.var_ratio.get()
        voice_label = self.var_tts_voice_lbl.get()
        logo_position_label = self.var_logo_position.get()
        self.cfg.update({
            "video_path":         self.var_video.get().strip(),
            "capcut_draft_dir":   self.var_draft.get().strip(),
            "model":              self.var_model.get(),
            "language":           lang_label if lang_label in self.lang_labels else "Tiếng Trung",
            "aspect_ratio":       self.ratio_codes[self.ratio_labels.index(ratio_label)]
                                  if ratio_label in self.ratio_labels else "9:16",
            "mirror_video":       self.var_mirror_video.get(),
            "logo_enabled":       self.var_logo_enabled.get(),
            "logo_path":          self.var_logo_path.get().strip(),
            "logo_position":      self.logo_position_codes[
                                      self.logo_position_labels.index(logo_position_label)]
                                  if logo_position_label in self.logo_position_labels else "top_right",
            "logo_scale":         max(0.05, min(0.50, logo_scale)),
            "enable_translation": self.var_translate.get(),
            "gemini_api_key":     self.var_gemini_key.get().strip(),
            "enable_tts":         self.var_tts_enable.get(),
            "tts_voice":          self.tts_codes[self.tts_labels.index(voice_label)]
                                  if voice_label in self.tts_labels else self.tts_codes[0],
            "tts_speed":          max(0.5, min(2.0, tts_speed)),
            "tts_auto_fit":       self.var_tts_auto_fit.get(),
            "tts_allow_overlap":  self.var_tts_allow_overlap.get(),
            "source_volume":      max(0.0, min(100.0, source_volume)),
            "text_color":         self.var_text_color.get(),
            "text_size":          max(4.0, min(30.0, text_size)),
            "text_bold":          self.var_text_bold.get(),
            "stroke_enabled":     self.var_stroke_enabled.get(),
            "stroke_color":       self.var_stroke_color.get(),
            "stroke_width":       max(0.0, min(100.0, stroke_width)),
            "stroke_alpha":       self.cfg.get("stroke_alpha", 1.0),
            "shadow_enabled":     False,
            "background_enabled": self.var_background_enabled.get(),
            "background_color":   self.cfg.get("background_color", "#000000"),
            "background_alpha":   self.cfg.get("background_alpha", 0.65),
        })
        save_settings(self.cfg)

    def _on_close(self):
        self._save_current_settings()
        self.root.destroy()

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
        tag = ("ok"  if "done" in low or "thành công" in low or "hoàn tất" in low else
               "err" if "error" in low or "lỗi" in low or "not found" in low or "hủy" in low else
               "acc" if msg.startswith("[") or "===" in msg else "")
        self._write_log(msg, tag)

    def _set_busy(self, busy: bool):
        def _do():
            if busy:
                self.btn_start.config(state="disabled", text="Đang xử lý...")
                self.btn_cancel.normal_bg = ERROR
                self.btn_cancel.config(state="normal", text="Hủy", bg=ERROR, fg="white")
                self.status_badge.config(text="Đang xử lý", fg="white", bg=ACCENT)
                self.progress.start(10)
            else:
                self.btn_start.config(state="normal", text="Tạo draft CapCut")
                self.btn_cancel.normal_bg = SURFACE2
                self.btn_cancel.config(state="disabled", text="Hủy", bg=SURFACE2, fg=ERROR)
                self.status_badge.config(text="Sẵn sàng", fg=SUCCESS, bg=SURFACE2)
                self.progress.stop()
        self.root.after(0, _do)

    def _cancel(self):
        if self.cancel_event:
            self.cancel_event.set()
            self._log_fn("\n[CANCEL] Đang gửi yêu cầu hủy tiến trình, vui lòng chờ...", "err")
            self.btn_cancel.config(state="disabled", text="Đang hủy...")
            self.status_badge.config(text="Đang hủy", fg=ERROR, bg=SURFACE2)

    # ── start ───────────────────────────────
    def _start(self):
        video        = self.var_video.get().strip()
        draft_dir    = self.var_draft.get().strip()
        model        = self.var_model.get()
        lang_lbl     = self.var_lang.get()
        lang         = self.lang_codes[self.lang_labels.index(lang_lbl)]
        enable_trans = self.var_translate.get()
        gemini_key   = self.var_gemini_key.get().strip()
        enable_tts   = self.var_tts_enable.get()
        tts_lbl      = self.var_tts_voice_lbl.get()
        tts_voice    = self.tts_codes[self.tts_labels.index(tts_lbl)]
        ratio_lbl    = self.var_ratio.get()
        aspect_ratio = self.ratio_codes[self.ratio_labels.index(ratio_lbl)]
        try:
            text_size = float(self.var_text_size.get())
            stroke_width = float(self.var_stroke_width.get())
            tts_speed = float(self.var_tts_speed.get())
            source_volume = float(self.var_source_volume.get())
            logo_scale = float(self.var_logo_scale.get()) / 100.0
        except (tk.TclError, ValueError):
            messagebox.showerror(
                "Giá trị không hợp lệ",
                "Tốc độ giọng đọc, âm lượng gốc, kích thước logo, cỡ chữ và độ dày viền phải là số.",
            )
            return
        if not 0.5 <= tts_speed <= 2.0:
            messagebox.showerror("Tốc độ không hợp lệ", "Tốc độ giọng đọc phải từ 0.5× đến 2.0×.")
            return
        if not 0.0 <= source_volume <= 100.0:
            messagebox.showerror("Âm lượng không hợp lệ", "Âm thanh gốc phải từ 0% đến 100%.")
            return
        if not 0.05 <= logo_scale <= 0.50:
            messagebox.showerror("Kích thước không hợp lệ", "Kích thước logo phải từ 5% đến 50%.")
            return
        logo_enabled = self.var_logo_enabled.get()
        logo_path = self.var_logo_path.get().strip()
        if logo_enabled and not logo_path:
            messagebox.showerror("Thiếu logo", "Hãy chọn ảnh logo hoặc tắt tùy chọn thêm logo.")
            return
        if logo_enabled and not os.path.isfile(logo_path):
            messagebox.showerror("Không tìm thấy logo", f"Không tìm thấy ảnh logo:\n{logo_path}")
            return
        logo_position_label = self.var_logo_position.get()
        video_options = {
            "mirror_video":  self.var_mirror_video.get(),
            "logo_enabled":  logo_enabled,
            "logo_path":     logo_path,
            "logo_position": self.logo_position_codes[
                                 self.logo_position_labels.index(logo_position_label)],
            "logo_scale":    logo_scale,
            "source_volume": source_volume / 100.0,
        }
        subtitle_style = {
            "text_color":         self.var_text_color.get(),
            "text_size":          max(4.0, min(30.0, text_size)),
            "text_bold":          self.var_text_bold.get(),
            "stroke_enabled":     self.var_stroke_enabled.get(),
            "stroke_color":       self.var_stroke_color.get(),
            "stroke_width":       max(0.0, min(100.0, stroke_width)),
            "stroke_alpha":       self.cfg.get("stroke_alpha", 1.0),
            "shadow_enabled":     self.var_shadow_enabled.get(),
            "background_enabled": self.var_background_enabled.get(),
            "background_color":   self.cfg.get("background_color", "#000000"),
            "background_alpha":   self.cfg.get("background_alpha", 0.65),
        }

        if not video:
            messagebox.showerror("Thiếu video", "Hãy chọn video nguồn trước khi tạo draft."); return
        if not os.path.isfile(video):
            messagebox.showerror("Không tìm thấy video", f"Không tìm thấy tệp:\n{video}"); return
        if not draft_dir:
            messagebox.showerror("Thiếu thư mục", "Hãy chọn thư mục draft của CapCut."); return
        if enable_trans and not gemini_key:
            messagebox.showerror("Thiếu API key", "Hãy nhập Gemini API key để dịch sang tiếng Việt."); return

        # Reset cancel event
        self.cancel_event.clear()

        # Save settings
        self._save_current_settings()

        # Clear log
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        if not self._model_is_installed(model):
            self._write_log(
                f"Model Whisper '{model}' chưa có. BiliCut sẽ tự động tải xuống trước khi nhận diện.",
                "acc",
            )

        self._set_busy(True)

        def _run():
            try:
                from main import run_pipeline, PipelineCancelledException
                run_pipeline(
                    video_path=video,
                    capcut_draft_dir=draft_dir,
                    model_name=model,
                    language=lang,
                    aspect_ratio=aspect_ratio,
                    video_options=video_options,
                    n_threads=8,
                    enable_translation=enable_trans,
                    gemini_api_key=gemini_key,
                    enable_tts=enable_tts,
                    tts_voice=tts_voice,
                    tts_speed=tts_speed,
                    tts_auto_fit=self.var_tts_auto_fit.get(),
                    tts_allow_overlap=self.var_tts_allow_overlap.get(),
                    subtitle_style=subtitle_style,
                    log=self._log_fn,
                    cancel_event=self.cancel_event,
                )
                self.root.after(0, lambda: messagebox.showinfo(
                    "Hoàn tất", "Đã tạo draft thành công.\nHãy mở CapCut để kiểm tra."))
            except PipelineCancelledException:
                self._log_fn("\n[CANCELLED] Tiến trình đã được hủy và dọn dẹp file tạm thành công.", "err")
                self.root.after(0, lambda: messagebox.showinfo("Đã hủy", "Tiến trình đã được hủy."))
            except Exception as e:
                msg = str(e)
                self._log_fn(f"[ERROR] {msg}")
                self.root.after(0, lambda: messagebox.showerror("Có lỗi xảy ra", msg))
            finally:
                self._set_busy(False)
                self.root.after(0, self._refresh_model_status)

        threading.Thread(target=_run, daemon=True).start()


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    BiliCutApp(root)
    root.mainloop()

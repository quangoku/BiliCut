"""
BiliCut – pipeline core
"""

import os
import builtins
import tempfile
import subprocess
from datetime import datetime

from pywhispercpp.model import Model
from pycapcut import (
    DraftFolder, VideoMaterial, VideoSegment,
    Timerange, TrackType, TextStyle,
)

# ──────────────────────────────────────
# PATHS
# ──────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
FFMPEG_BIN = os.path.join(BASE_DIR, "ffmpeg.exe")


# ──────────────────────────────────────
# STEP 1 – Extract audio (FFmpeg)
# ──────────────────────────────────────

def extract_audio_wav(video_path: str, wav_path: str) -> None:
    """Extract 16kHz mono WAV from video using FFmpeg."""
    ffmpeg = FFMPEG_BIN if os.path.exists(FFMPEG_BIN) else "ffmpeg"
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        wav_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg error:\n{result.stderr.decode(errors='replace')}"
        )


# ──────────────────────────────────────
# STEP 2 – Transcribe (Whisper) → SRT
# ──────────────────────────────────────

def _ms_to_srt(ms: int) -> str:
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000;    ms %= 60_000
    s = ms // 1_000;     ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_to_srt(
    wav_path: str,
    srt_path: str,
    model_name: str = "small",
    language=None,
    n_threads: int = 8,
    log=print,
) -> str:
    log("  [Whisper] Loading model…")
    kwargs = {"models_dir": MODELS_DIR, "model": model_name, "n_threads": n_threads}
    if language:
        kwargs["language"] = language

    _orig = builtins.print
    builtins.print = log
    try:
        model = Model(**kwargs)
        log("  [Whisper] Transcribing…")
        segments = model.transcribe(wav_path)
    finally:
        builtins.print = _orig

    os.makedirs(os.path.dirname(srt_path), exist_ok=True)
    count = 0
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            start_ms = seg.t0 * 10
            end_ms   = seg.t1 * 10
            text = seg.text.strip()
            if not text:
                continue
            f.write(f"{i}\n{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}\n{text}\n\n")
            count += 1

    log(f"  [SRT] Saved: {srt_path}  ({count} lines)")
    return srt_path


# ──────────────────────────────────────
# STEP 3 – Get video info (FFprobe)
# ──────────────────────────────────────

def get_video_info(video_path: str) -> dict:
    """Return dict with width, height, fps, duration_us."""
    ffprobe = os.path.join(BASE_DIR, "ffprobe.exe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"

    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        info = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info = {}

    width  = int(info.get("width",  1920))
    height = int(info.get("height", 1080))
    dur_us = int(float(info.get("duration", 0)) * 1_000_000)

    fps_raw = info.get("r_frame_rate", "30/1")
    try:
        n, d = fps_raw.split("/")
        fps = round(int(n) / int(d))
    except Exception:
        fps = 30

    return {"width": width, "height": height, "duration_us": dur_us, "fps": fps}


import json
import urllib.request
import urllib.error

# ──────────────────────────────────────
# STEP 4 – Translate SRT (Gemini API)
# ──────────────────────────────────────

def translate_srt_gemini(
    srt_path: str,
    output_srt_path: str,
    api_key: str,
    log=print,
) -> str:
    """Translate SRT subtitles to Vietnamese using Gemini REST API."""
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("Vui lòng nhập Gemini API Key để thực hiện dịch!")

    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Không tìm thấy file SRT: {srt_path}")

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        raise ValueError("File SRT trống, không thể dịch.")

    log("  [Gemini] Đang gửi nội dung SRT lên Gemini API để dịch sang tiếng Việt...")

    prompt = (
        "Bạn là một biên dịch viên phụ đề chuyên nghiệp.\n"
        "Hãy dịch toàn bộ nội dung phụ đề SRT sau đây sang tiếng Việt tự nhiên và chuẩn xác.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. Giữ NGUYÊN cấu trúc file SRT, số thứ tự (1, 2, 3...) và timestamp (00:00:00,000 --> 00:00:00,000).\n"
        "2. CHỈ dịch phần câu nói văn bản của từng phụ đề.\n"
        "3. KHÔNG thêm bất kỳ ghi chú, nhận xét hay định dạng markdown codeblock nào (không dùng ```srt hoặc ```).\n\n"
        f"Nội dung SRT:\n{content}"
    )

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
    translated_text = None
    last_error = None

    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                log(f"  [Gemini] Dịch thành công với model {m}")
                break
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {err.code}: {err_body}"
        except Exception as err:
            last_error = str(err)

    if not translated_text:
        raise RuntimeError(f"Lỗi gọi Gemini API: {last_error}")

    # Xóa định dạng markdown ``` nếu Gemini lỡ thêm vào
    if translated_text.startswith("```"):
        lines = translated_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        translated_text = "\n".join(lines).strip()

    os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write(translated_text + "\n")

    log(f"  [Gemini] File SRT tiếng Việt đã lưu tại: {output_srt_path}")
    return output_srt_path


# ──────────────────────────────────────
# STEP 5 – Create CapCut draft
# ──────────────────────────────────────

def create_capcut_draft(
    video_path: str,
    srt_path: str,
    draft_name: str,
    video_info: dict,
    capcut_draft_dir: str,
    log=print,
) -> str:
    if not os.path.isdir(capcut_draft_dir):
        raise FileNotFoundError(
            f"CapCut draft folder not found:\n{capcut_draft_dir}\n"
            "Please open CapCut at least once or check your draft path setting."
        )

    log(f"  [CapCut] Draft folder: {capcut_draft_dir}")
    folder = DraftFolder(capcut_draft_dir)

    if folder.has_draft(draft_name):
        folder.remove(draft_name)

    script = folder.create_draft(
        draft_name=draft_name,
        width=video_info["width"],
        height=video_info["height"],
        fps=video_info["fps"],
        allow_replace=True,
    )

    log("  [CapCut] Adding video track...")
    script.add_track(TrackType.video)

    mat = VideoMaterial(os.path.abspath(video_path))
    script.add_segment(
        VideoSegment(
            material=mat,
            target_timerange=Timerange(start=0, duration=mat.duration),
        )
    )

    log("  [CapCut] Importing SRT subtitles...")
    style = TextStyle(
        size=7.0,
        bold=False,
        color=(1.0, 1.0, 1.0),
        align=1,
        auto_wrapping=True,
        max_line_width=0.85,
    )

    script.import_srt(
        srt_path=os.path.abspath(srt_path),
        track_name="subtitles",
        text_style=style,
    )

    script.save()
    draft_path = os.path.join(capcut_draft_dir, draft_name)
    log(f"  [CapCut] Draft saved: {draft_path}")
    return draft_path


# ──────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────

def run_pipeline(
    video_path: str,
    capcut_draft_dir: str,
    model_name: str = "small",
    language=None,
    n_threads: int = 8,
    enable_translation: bool = False,
    gemini_api_key: str = "",
    log=print,
) -> str:
    log("=" * 52)
    log("  BiliCut  -  Video > SRT > CapCut Draft")
    log("=" * 52)

    base       = os.path.splitext(os.path.basename(video_path))[0]
    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
    draft_name = f"{base}_{ts}"

    # Tạo các file SRT tạm thời, tự động dọn dẹp sau khi import xong vào CapCut
    tmp_orig = tempfile.NamedTemporaryFile(suffix="_orig.srt", delete=False)
    tmp_orig.close()
    srt_orig = tmp_orig.name

    tmp_vi = tempfile.NamedTemporaryFile(suffix="_vi.srt", delete=False)
    tmp_vi.close()
    srt_vi = tmp_vi.name

    try:
        # 1. Video info
        log(f"\n[1/5] Reading video info: {os.path.basename(video_path)}")
        vinfo = get_video_info(video_path)
        log(f"  {vinfo['width']}x{vinfo['height']} @ {vinfo['fps']}fps  "
            f"| {vinfo['duration_us']/1e6:.1f}s")

        # 2. Extract audio
        log("\n[2/5] Extracting audio (FFmpeg)...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            extract_audio_wav(video_path, wav_path)
            log(f"  Temp WAV: {wav_path}")

            # 3. Transcribe
            log("\n[3/5] Transcribing (Whisper)...")
            transcribe_to_srt(
                wav_path=wav_path,
                srt_path=srt_orig,
                model_name=model_name,
                language=language,
                n_threads=n_threads,
                log=log,
            )
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)

        # 4. Gemini Translation (Optional)
        srt_to_use = srt_orig
        if enable_translation:
            log("\n[4/5] Translating SRT to Vietnamese via Gemini API...")
            srt_to_use = translate_srt_gemini(
                srt_path=srt_orig,
                output_srt_path=srt_vi,
                api_key=gemini_api_key,
                log=log,
            )
        else:
            log("\n[4/5] Translation disabled, using original SRT.")

        # 5. CapCut draft
        log("\n[5/5] Creating CapCut draft...")
        draft_path = create_capcut_draft(
            video_path=video_path,
            srt_path=srt_to_use,
            draft_name=draft_name,
            video_info=vinfo,
            capcut_draft_dir=capcut_draft_dir,
            log=log,
        )

        log("\n" + "=" * 52)
        log("  DONE!")
        log(f"  Draft: {draft_path}")
        log("  -> Open CapCut - your new draft is ready.")
        log("=" * 52)
        return draft_path

    finally:
        # Tự động xóa file SRT tạm thời sau khi hoàn tất
        for tmp_file in [srt_orig, srt_vi]:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass


# ──────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────

if __name__ == "__main__":
    import tkinter as tk
    from gui import BiliCutApp
    root = tk.Tk()
    BiliCutApp(root)
    root.mainloop()
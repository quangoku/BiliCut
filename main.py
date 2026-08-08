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
# PATHS & CANCELLATION
# ──────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
FFMPEG_BIN = os.path.join(BASE_DIR, "ffmpeg.exe")


class PipelineCancelledException(Exception):
    """Exception raised when user cancels the pipeline."""
    pass


def check_cancelled(cancel_event=None):
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelledException("Tiến trình đã bị hủy bởi người dùng.")



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
    model_path = os.path.join(MODELS_DIR, f"ggml-{model_name}.bin")
    os.makedirs(MODELS_DIR, exist_ok=True)
    if os.path.exists(model_path):
        log(f"  [Whisper] Đang dùng model '{model_name}' đã cài đặt…")
    else:
        log(f"  [Whisper] Model '{model_name}' chưa có, đang tự động tải xuống…")
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


import re
from capcut_tts_api import CapCutClient
from pycapcut import (
    DraftFolder, VideoMaterial, VideoSegment,
    Timerange, TrackType, TextStyle,
    AudioMaterial, AudioSegment, TextSegment,
    TextBorder, TextBackground, ClipSettings,
)

# ──────────────────────────────────────
# STEP 5 – Parse SRT & Generate CapCut TTS Speech
# ──────────────────────────────────────

def parse_srt_blocks(srt_path: str) -> list[dict]:
    """Parse SRT file into a list of dicts: [{'start_ms': int, 'end_ms': int, 'text': str}]"""
    if not os.path.exists(srt_path):
        return []
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    blocks = []
    pattern = re.compile(
        r'(\d+)\s*\n'
        r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n'
        r'(.*?)(?=\n\s*\n\d+|\n\s*$|\Z)',
        re.DOTALL
    )
    for match in pattern.finditer(content):
        sh, sm, ss, sms = map(int, match.group(2, 3, 4, 5))
        eh, em, es, ems = map(int, match.group(6, 7, 8, 9))
        text = match.group(10).strip()
        if text:
            start_ms = (sh * 3600 + sm * 60 + ss) * 1000 + sms
            end_ms = (eh * 3600 + em * 60 + es) * 1000 + ems
            blocks.append({
                'start_ms': start_ms,
                'end_ms': end_ms,
                'text': text
            })
    return blocks


def extract_audio_url_and_duration(res: dict) -> tuple[str, int]:
    """Extract (speech_url, duration_ms) from CapCut TTS generate_speech response."""
    tasks = (res.get("data") or {}).get("tasks") or []
    if not tasks:
        return None, 0
    task = tasks[0]

    # Check payload first (query_tts_task response)
    if "payload" in task and task["payload"]:
        try:
            p = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
            audios = p.get("audio_subtitles") or []
            if audios and "speech_url" in audios[0]:
                return audios[0]["speech_url"], audios[0].get("duration", 0)
        except Exception:
            pass

    # Check sub_tasks (create_tts_task response)
    sub_tasks = task.get("sub_tasks") or []
    if sub_tasks and "url" in sub_tasks[0]:
        return sub_tasks[0]["url"], sub_tasks[0].get("duration", 0)

    return None, 0


import shutil


def generate_tts_audio_segments(
    srt_path: str,
    voice_type: str = "BV421_vivn_streaming",
    log=print,
    cancel_event=None,
) -> tuple[list[dict], str]:
    """
    Generate speech MP3 for each SRT subtitle block using CapCut TTS API.
    Downloads MP3 files into a temporary folder.
    Returns: (list of dicts [{'path', 'start_us'}], temp_dir_path)
    """
    blocks = parse_srt_blocks(srt_path)
    if not blocks:
        log("  [TTS] Không tìm thấy đoạn phụ đề nào để tạo giọng đọc.")
        return [], ""

    temp_dir = tempfile.mkdtemp(prefix="bilicut_tts_")
    log(f"  [CapCut TTS] Đang tạo giọng đọc '{voice_type}' cho {len(blocks)} câu phụ đề...")
    client = CapCutClient()
    audio_items = []

    for i, block in enumerate(blocks, start=1):
        check_cancelled(cancel_event)
        text = block['text']
        start_us = block['start_ms'] * 1000
        preview_text = text.replace('\n', ' ')
        if len(preview_text) > 30:
            preview_text = preview_text[:30] + "..."
        log(f"  [CapCut TTS {i}/{len(blocks)}] Đọc: \"{preview_text}\"")

        try:
            res = client.generate_speech(text, voice=voice_type, wait=True)
            check_cancelled(cancel_event)
            url, _ = extract_audio_url_and_duration(res)
            if not url:
                log(f"  [CapCut TTS {i}] Bỏ qua câu do không nhận được kết quả audio.")
                continue

            mp3_path = os.path.join(temp_dir, f"tts_{i:04d}.mp3")
            urllib.request.urlretrieve(url, mp3_path)
            audio_items.append({
                "path": mp3_path,
                "start_us": start_us,
            })
        except PipelineCancelledException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            log(f"  [CapCut TTS {i}] Lỗi tạo giọng đọc câu này: {exc}")

    log(f"  [CapCut TTS] Hoàn tất tạo {len(audio_items)} đoạn âm thanh.")
    return audio_items, temp_dir


# ──────────────────────────────────────
# STEP 6 – Create CapCut draft
# ──────────────────────────────────────

def create_capcut_draft(
    video_path: str,
    srt_path: str,
    draft_name: str,
    video_info: dict,
    capcut_draft_dir: str,
    tts_audio_items: list[dict] = None,
    tts_speed: float = 1.0,
    subtitle_style: dict = None,
    video_options: dict = None,
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

    draft_path = os.path.join(capcut_draft_dir, draft_name)
    permanent_tts_dir = os.path.join(draft_path, "tts_audio")

    video_options = video_options or {}
    log("  [CapCut] Adding video track...")
    script.add_track(TrackType.video)

    mat = VideoMaterial(os.path.abspath(video_path))
    script.add_segment(
        VideoSegment(
            material=mat,
            target_timerange=Timerange(start=0, duration=mat.duration),
            clip_settings=ClipSettings(
                flip_horizontal=bool(video_options.get("mirror_video", False))
            ),
        )
    )
    if video_options.get("mirror_video", False):
        log("  [CapCut] Video đã được lật ngang trái/phải.")

    if video_options.get("logo_enabled", False):
        logo_path = os.path.abspath(video_options.get("logo_path", ""))
        if not os.path.isfile(logo_path):
            raise FileNotFoundError(f"Không tìm thấy ảnh logo: {logo_path}")

        logo_dir = os.path.join(draft_path, "logo")
        os.makedirs(logo_dir, exist_ok=True)
        extension = os.path.splitext(logo_path)[1].lower() or ".png"
        permanent_logo_path = os.path.join(logo_dir, f"channel_logo{extension}")
        shutil.copy2(logo_path, permanent_logo_path)

        logo_position = video_options.get("logo_position", "top_right")
        valid_positions = {"top_left", "top_right", "bottom_left", "bottom_right"}
        if logo_position not in valid_positions:
            raise ValueError(f"Vị trí logo không hợp lệ: {logo_position}")
        logo_scale = max(0.05, min(0.50, float(video_options.get("logo_scale", 0.20))))

        logo_material = VideoMaterial(permanent_logo_path)
        # logo_scale is the desired fraction of canvas width, independent of source image resolution.
        visual_scale = (video_info["width"] * logo_scale) / max(1, logo_material.width)
        logo_height_ratio = (logo_material.height * visual_scale) / max(1, video_info["height"])
        safe_margin = 0.04
        x_offset = max(0.0, 1.0 - safe_margin - logo_scale)
        y_offset = max(0.0, 1.0 - safe_margin - logo_height_ratio)
        transform_x = -x_offset if logo_position.endswith("left") else x_offset
        transform_y = y_offset if logo_position.startswith("top") else -y_offset

        script.add_track(TrackType.video, track_name="channel_logo", relative_index=999)
        script.add_segment(
            VideoSegment(
                material=logo_material,
                target_timerange=Timerange(start=0, duration=mat.duration),
                clip_settings=ClipSettings(
                    scale_x=visual_scale,
                    scale_y=visual_scale,
                    transform_x=transform_x,
                    transform_y=transform_y,
                ),
            ),
            track_name="channel_logo",
        )
        log(f"  [CapCut] Logo: {logo_position}, size={logo_scale * 100:g}%")

    log("  [CapCut] Importing SRT subtitles...")
    subtitle_style = subtitle_style or {}

    def hex_to_rgb(value, fallback):
        value = str(value or "").strip().lstrip("#")
        if len(value) != 6:
            return fallback
        try:
            return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        except ValueError:
            return fallback

    style = TextStyle(
        size=float(subtitle_style.get("text_size", 7.0)),
        bold=bool(subtitle_style.get("text_bold", True)),
        color=hex_to_rgb(subtitle_style.get("text_color"), (1.0, 1.0, 1.0)),
        align=1,
        auto_wrapping=True,
        max_line_width=0.85,
    )

    border = None
    if subtitle_style.get("stroke_enabled", True):
        border = TextBorder(
            alpha=float(subtitle_style.get("stroke_alpha", 1.0)),
            color=hex_to_rgb(subtitle_style.get("stroke_color"), (0.0, 0.0, 0.0)),
            width=float(subtitle_style.get("stroke_width", 40.0)),
        )

    shadow_requested = bool(subtitle_style.get("shadow_enabled", False))
    if shadow_requested:
        log("  [CapCut] Phiên bản pycapcut hiện tại chưa hỗ trợ bóng chữ; bỏ qua tùy chọn này.")

    background = None
    if subtitle_style.get("background_enabled", False):
        background = TextBackground(
            color=subtitle_style.get("background_color", "#000000"),
            style=2,
            alpha=float(subtitle_style.get("background_alpha", 0.65)),
            round_radius=0.4,
            height=0.28,
            width=0.28,
            horizontal_offset=0.5,
            vertical_offset=0.5,
        )

    style_reference = TextSegment(
        "BiliCut subtitle style",
        Timerange(start=0, duration=1_000_000),
        style=style,
        border=border,
        background=background,
    )

    log(
        "  [CapCut] Subtitle style: "
        f"size={style.size:g}, color={subtitle_style.get('text_color', '#ffffff')}, "
        f"bold={style.bold}, border={'on' if border else 'off'}, "
        f"shadow={'unsupported' if shadow_requested else 'off'}, "
        f"background={'on' if background else 'off'}"
    )

    script.import_srt(
        srt_path=os.path.abspath(srt_path),
        track_name="subtitles",
        style_reference=style_reference,
    )

    # Chèn các đoạn audio giọng đọc TTS vào audio track nếu có
    if tts_audio_items:
        tts_speed = max(0.5, min(2.0, float(tts_speed)))
        os.makedirs(permanent_tts_dir, exist_ok=True)
        log(f"  [CapCut] Chèn {len(tts_audio_items)} đoạn TTS ở tốc độ {tts_speed:g}×...")
        script.add_track(TrackType.audio, track_name="tts_speech")
        last_end_us = 0
        inserted_count = 0
        for i, item in enumerate(tts_audio_items, start=1):
            src_path = item["path"]
            start_us = item["start_us"]
            if os.path.exists(src_path):
                try:
                    # Copy MP3 file vĩnh viễn vào trong thư mục CapCut Draft
                    dst_path = os.path.join(permanent_tts_dir, f"speech_{i:04d}.mp3")
                    shutil.copy2(src_path, dst_path)

                    audio_mat = AudioMaterial(dst_path)
                    # Tránh chồng chéo (overlap): nếu thời gian bắt đầu nhỏ hơn thời điểm kết thúc câu trước, nối tiếp câu trước
                    if start_us < last_end_us:
                        start_us = last_end_us

                    audio_seg = AudioSegment(
                        material=audio_mat,
                        target_timerange=Timerange(start=start_us, duration=audio_mat.duration),
                        source_timerange=Timerange(start=0, duration=audio_mat.duration),
                        speed=tts_speed,
                    )
                    script.add_segment(audio_seg, track_name="tts_speech")
                    last_end_us = start_us + audio_seg.duration
                    inserted_count += 1
                except Exception as e:
                    log(f"  [CapCut Audio Warning] Không thể chèn audio {src_path}: {e}")

        log(f"  [CapCut] Đã chèn thành công {inserted_count}/{len(tts_audio_items)} đoạn âm thanh vào timeline.")

    script.save()
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
    aspect_ratio: str = "9:16",
    n_threads: int = 8,
    enable_translation: bool = False,
    gemini_api_key: str = "",
    enable_tts: bool = False,
    tts_voice: str = "BV421_vivn_streaming",
    tts_speed: float = 1.0,
    subtitle_style: dict = None,
    video_options: dict = None,
    log=print,
    cancel_event=None,
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

    temp_tts_dir = None

    try:
        check_cancelled(cancel_event)

        # 1. Video info
        log(f"\n[1/6] Reading video info: {os.path.basename(video_path)}")
        vinfo = get_video_info(video_path)
        source_size = (vinfo["width"], vinfo["height"])
        if aspect_ratio == "9:16":
            vinfo["width"], vinfo["height"] = 1080, 1920
        elif aspect_ratio == "16:9":
            vinfo["width"], vinfo["height"] = 1920, 1080
        else:
            raise ValueError(f"Tỷ lệ khung hình không hợp lệ: {aspect_ratio}")
        log(f"  Source: {source_size[0]}x{source_size[1]} | "
            f"Canvas {aspect_ratio}: {vinfo['width']}x{vinfo['height']} @ {vinfo['fps']}fps  "
            f"| {vinfo['duration_us']/1e6:.1f}s")

        check_cancelled(cancel_event)

        # 2. Extract audio
        log("\n[2/6] Extracting audio (FFmpeg)...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            extract_audio_wav(video_path, wav_path)
            log(f"  Temp WAV: {wav_path}")

            check_cancelled(cancel_event)

            # 3. Transcribe
            log("\n[3/6] Transcribing (Whisper)...")
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

        check_cancelled(cancel_event)

        # 4. Gemini Translation (Optional)
        srt_to_use = srt_orig
        if enable_translation:
            log("\n[4/6] Translating SRT to Vietnamese via Gemini API...")
            srt_to_use = translate_srt_gemini(
                srt_path=srt_orig,
                output_srt_path=srt_vi,
                api_key=gemini_api_key,
                log=log,
            )
        else:
            log("\n[4/6] Translation disabled, using original SRT.")

        check_cancelled(cancel_event)

        # 5. CapCut TTS Speech (Optional)
        tts_audio_items = []
        if enable_tts:
            log("\n[5/6] Generating CapCut TTS Speech from SRT...")
            tts_audio_items, temp_tts_dir = generate_tts_audio_segments(
                srt_path=srt_to_use,
                voice_type=tts_voice,
                log=log,
                cancel_event=cancel_event,
            )
        else:
            log("\n[5/6] CapCut TTS Speech disabled.")

        check_cancelled(cancel_event)

        # 6. CapCut draft
        log("\n[6/6] Creating CapCut draft...")
        draft_path = create_capcut_draft(
            video_path=video_path,
            srt_path=srt_to_use,
            draft_name=draft_name,
            video_info=vinfo,
            capcut_draft_dir=capcut_draft_dir,
            tts_audio_items=tts_audio_items,
            tts_speed=tts_speed,
            subtitle_style=subtitle_style,
            video_options=video_options,
            log=log,
        )

        log("\n" + "=" * 52)
        log("  DONE!")
        log(f"  Draft: {draft_path}")
        log("  -> Open CapCut - your new draft is ready.")
        log("=" * 52)
        return draft_path

    finally:
        # Tự động xóa các thư mục và file tạm
        if temp_tts_dir and os.path.exists(temp_tts_dir):
            shutil.rmtree(temp_tts_dir, ignore_errors=True)
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

"""
BiliCut – pipeline core
"""

import os
import builtins
import tempfile
import subprocess
import time
import threading
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from pywhispercpp.model import Model
from pycapcut import (
    DraftFolder, VideoMaterial, VideoSegment,
    Timerange, TrackType, TextStyle,
)
from ffmpeg_manager import ensure_ffmpeg_installed

# ──────────────────────────────────────
# PATHS & CANCELLATION
# ──────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_APP_DATA = os.environ.get(
    "LOCALAPPDATA",
    os.path.join(os.path.expanduser("~"), "AppData", "Local"),
)
APP_DATA_DIR = os.path.join(LOCAL_APP_DATA, "BiliCut")
MODELS_DIR = os.path.join(APP_DATA_DIR, "models")

# Whisper models are user data. Keep them outside the installation directory so
# downloaded models remain writable and survive application updates.
os.makedirs(MODELS_DIR, exist_ok=True)


class PipelineCancelledException(Exception):
    """Exception raised when user cancels the pipeline."""
    pass


def check_cancelled(cancel_event=None):
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelledException("Tiến trình đã bị hủy bởi người dùng.")



# ──────────────────────────────────────
# STEP 1 – Extract audio (FFmpeg)
# ──────────────────────────────────────

def extract_audio_wav(video_path: str, wav_path: str, ffmpeg_path: str) -> None:
    """Extract 16kHz mono WAV from video using FFmpeg."""
    cmd = [
        ffmpeg_path, "-y", "-i", video_path,
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

def get_video_info(video_path: str, ffprobe_path: str) -> dict:
    """Return dict with width, height, fps, duration_us."""
    cmd = [
        ffprobe_path, "-v", "error",
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
import socket
import urllib.request
import urllib.error

# Stable text models, ordered by translation quality and then cost/speed.
# Preview/experimental aliases are intentionally avoided because they can be
# retired while an installed build is still in use.
GEMINI_TRANSLATION_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
)
GEMINI_CHUNK_SIZE = 60
GEMINI_MAX_WORKERS = 2


def _gemini_error_details(err):
    """Return a short Gemini error status/message without logging the API key."""
    try:
        body = err.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""

    status = ""
    message = ""
    if body:
        try:
            error_data = json.loads(body).get("error", {})
            status = str(error_data.get("status", ""))
            message = str(error_data.get("message", ""))
        except (TypeError, ValueError, AttributeError):
            message = body

    message = " ".join(message.split())
    if len(message) > 300:
        message = message[:297] + "..."
    return status, message


def _should_try_next_gemini_model(http_code, status):
    """Only change model for quota, overload, or unavailable-model errors."""
    return http_code in (404, 408, 429, 500, 502, 503, 504) or status in {
        "MODEL_NOT_FOUND",
        "RESOURCE_EXHAUSTED",
        "RATE_LIMIT_EXCEEDED",
        "QUOTA_EXCEEDED",
        "UNAVAILABLE",
    }


def _parse_srt_content(content: str) -> list[dict]:
    blocks = []
    pattern = re.compile(
        r'(\d+)\s*\n'
        r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n'
        r'(.*?)(?=\n\s*\n\d+|\n\s*$|\Z)',
        re.DOTALL,
    )
    for match in pattern.finditer(content):
        sh, sm, ss, sms = map(int, match.group(2, 3, 4, 5))
        eh, em, es, ems = map(int, match.group(6, 7, 8, 9))
        text = match.group(10).strip()
        if text:
            blocks.append({
                "start_ms": (sh * 3600 + sm * 60 + ss) * 1000 + sms,
                "end_ms": (eh * 3600 + em * 60 + es) * 1000 + ems,
                "text": text,
            })
    return blocks


def _format_srt_blocks(blocks: list[dict], start_index: int = 1) -> str:
    parts = []
    for index, block in enumerate(blocks, start=start_index):
        parts.append(
            f"{index}\n{_ms_to_srt(int(block['start_ms']))} --> "
            f"{_ms_to_srt(int(block['end_ms']))}\n{block['text']}"
        )
    return "\n\n".join(parts) + "\n"


def _write_translated_blocks(path: str, timing_blocks: list[dict], texts: list[str]) -> None:
    previous_end_ms = 0
    normalized = []
    for timing, text in zip(timing_blocks, texts):
        start_ms = max(int(timing["start_ms"]), previous_end_ms)
        end_ms = max(int(timing["end_ms"]), start_ms + 1)
        normalized.append({"start_ms": start_ms, "end_ms": end_ms, "text": text.strip()})
        previous_end_ms = end_ms
    with open(path, "w", encoding="utf-8") as output:
        output.write(_format_srt_blocks(normalized))


def _request_gemini_srt_chunk(prompt, api_key, chunk_number, chunk_total, log, slow_notice_sent):
    translated_text = None
    last_error = None

    def log_slow_translation():
        if not slow_notice_sent.is_set():
            slow_notice_sent.set()
            log("  [Gemini] SRT hơi dài nên quá trình dịch sẽ tốn hơi nhiều thời gian, vui lòng chờ...")

    stop_trying = False
    for model_index, model in enumerate(GEMINI_TRANSLATION_MODELS):
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        has_fallback = model_index + 1 < len(GEMINI_TRANSLATION_MODELS)

        for attempt in range(1, 3):
            notice_timer = threading.Timer(240.0, log_slow_translation)
            notice_timer.daemon = True
            notice_timer.start()
            try:
                with urllib.request.urlopen(request, timeout=480) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    translated_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                break
            except urllib.error.HTTPError as err:
                status, message = _gemini_error_details(err)
                error_label = status or f"HTTP {err.code}"
                last_error = f"{error_label}: {message}" if message else error_label
                if _should_try_next_gemini_model(err.code, status) and has_fallback:
                    next_model = GEMINI_TRANSLATION_MODELS[model_index + 1]
                    log(
                        f"  [Gemini {chunk_number}/{chunk_total}] {model} gặp {error_label}; "
                        f"chuyển sang {next_model}..."
                    )
                else:
                    stop_trying = True
                break
            except (TimeoutError, socket.timeout, urllib.error.URLError) as err:
                reason = getattr(err, "reason", err)
                is_timeout = isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(err).lower()
                last_error = f"Timeout khi chờ model {model}: {err}" if is_timeout else str(err)
                if not is_timeout:
                    stop_trying = True
                    break
                if attempt < 2:
                    log(f"  [Gemini {chunk_number}/{chunk_total}] Timeout, đang thử lại (2/2)...")
                    time.sleep(2)
                    continue
                if has_fallback:
                    log(
                        f"  [Gemini {chunk_number}/{chunk_total}] {model} vẫn timeout; "
                        f"chuyển sang {GEMINI_TRANSLATION_MODELS[model_index + 1]}..."
                    )
                else:
                    stop_trying = True
                break
            except Exception as err:
                last_error = str(err)
                stop_trying = True
                break
            finally:
                notice_timer.cancel()

        if translated_text or stop_trying:
            break

    if not translated_text:
        raise RuntimeError(last_error or "Gemini không trả về nội dung dịch.")
    if translated_text.startswith("```"):
        lines = translated_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        translated_text = "\n".join(lines).strip()
    return translated_text

# ──────────────────────────────────────
# STEP 4 – Translate SRT (Gemini API)
# ──────────────────────────────────────

def translate_srt_gemini(
    srt_path: str,
    output_srt_path: str,
    api_key: str,
    log=print,
) -> str:
    """Translate SRT in small parallel chunks while preserving Whisper timing."""
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("Vui lòng nhập Gemini API Key để thực hiện dịch!")

    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Không tìm thấy file SRT: {srt_path}")

    with open(srt_path, "r", encoding="utf-8-sig") as f:
        original_blocks = _parse_srt_content(f.read())
    if not original_blocks:
        raise ValueError("File SRT trống, không thể dịch.")

    chunks = [
        original_blocks[index:index + GEMINI_CHUNK_SIZE]
        for index in range(0, len(original_blocks), GEMINI_CHUNK_SIZE)
    ]
    total_chunks = len(chunks)
    worker_count = min(GEMINI_MAX_WORKERS, total_chunks)
    log(
        f"  [Gemini] Chia {len(original_blocks)} câu thành {total_chunks} phần "
        f"(tối đa {GEMINI_CHUNK_SIZE} câu/phần, {worker_count} request song song)."
    )

    os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
    chunk_results = [None] * total_chunks
    slow_notice_sent = threading.Event()

    def translate_chunk(chunk_index):
        chunk = chunks[chunk_index]
        first_number = chunk_index * GEMINI_CHUNK_SIZE + 1
        chunk_srt = _format_srt_blocks(chunk, start_index=first_number)
        prompt = (
            "Bạn là biên dịch viên phụ đề chuyên nghiệp. Dịch SRT sau sang tiếng Việt tự nhiên.\n"
            "BẮT BUỘC giữ đúng số lượng đoạn, số thứ tự và cấu trúc SRT. Chỉ dịch câu nói; "
            "không thêm ghi chú hay markdown.\n\n"
            f"Nội dung SRT:\n{chunk_srt}"
        )
        log(f"  [Gemini] Đang dịch phần {chunk_index + 1}/{total_chunks} ({len(chunk)} câu)...")
        translated = _request_gemini_srt_chunk(
            prompt, api_key, chunk_index + 1, total_chunks, log, slow_notice_sent
        )
        parsed = _parse_srt_content(translated)
        if len(parsed) != len(chunk):
            raise RuntimeError(
                f"phần {chunk_index + 1}/{total_chunks} trả thiếu/thừa câu "
                f"({len(parsed)}/{len(chunk)})"
            )
        return [block["text"] for block in parsed]

    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="gemini_srt")
    futures = {executor.submit(translate_chunk, index): index for index in range(total_chunks)}
    try:
        for future in as_completed(futures):
            chunk_index = futures[future]
            try:
                chunk_results[chunk_index] = future.result()
            except Exception as err:
                for pending in futures:
                    pending.cancel()
                raise RuntimeError(
                    f"Lỗi gọi Gemini API ở phần {chunk_index + 1}/{total_chunks}: {err}"
                ) from err

            log(f"  [Gemini] Hoàn thành phần {chunk_index + 1}/{total_chunks}.")

            # Save every contiguous completed prefix as a recoverable checkpoint.
            completed_chunks = 0
            while completed_chunks < total_chunks and chunk_results[completed_chunks] is not None:
                completed_chunks += 1
            if completed_chunks:
                checkpoint_texts = [
                    text
                    for result in chunk_results[:completed_chunks]
                    for text in result
                ]
                checkpoint_count = len(checkpoint_texts)
                _write_translated_blocks(
                    output_srt_path,
                    original_blocks[:checkpoint_count],
                    checkpoint_texts,
                )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    all_texts = [text for result in chunk_results for text in result]
    _write_translated_blocks(output_srt_path, original_blocks, all_texts)

    log(f"  [Gemini] File SRT tiếng Việt đã lưu tại: {output_srt_path}")
    return output_srt_path


from capcut_tts_api import (
    CapCutClient,
    CapCutTaskError,
)
from capcut_tts_transport import CapCutTransportError, create_tts_session
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
        return _parse_srt_content(f.read())


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


def _wait_tts(seconds: float, cancel_event=None) -> None:
    """Wait without making the Cancel button unresponsive."""
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        check_cancelled(cancel_event)
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def _tts_retry_delay(error: CapCutTransportError, attempt: int) -> float:
    if error.status_code == 429 and error.retry_after is not None:
        return min(60.0, max(0.0, error.retry_after))
    return float(2 ** attempt)


def generate_tts_with_retry(
    client: CapCutClient,
    text: str,
    voice_type: str,
    log=print,
    cancel_event=None,
    retries: int = 3,
    task_timeout: float = 90.0,
) -> dict:
    """Create one TTS task and poll it without recreating accepted tasks."""
    retries = max(1, int(retries))
    create_res = None
    for attempt in range(1, retries + 1):
        check_cancelled(cancel_event)
        try:
            create_res = client.create_tts_task(text, voice=voice_type)
            break
        except CapCutTransportError as exc:
            if not exc.retryable_create or attempt >= retries:
                raise
            delay = _tts_retry_delay(exc, attempt)
            log(
                f"  [CapCut TTS] Lỗi {exc.kind} khi tạo task "
                f"(lần {attempt}/{retries}); thử lại sau {delay:g} giây."
            )
            _wait_tts(delay, cancel_event)

    tasks = (create_res.get("data") or {}).get("tasks") or []
    if not tasks:
        raise CapCutTaskError(f"No task returned from API: {create_res}")
    task_id = tasks[0]["id"]
    token = tasks[0]["token"]

    started = time.monotonic()
    poll_failures = 0
    while time.monotonic() - started < task_timeout:
        check_cancelled(cancel_event)
        try:
            query_res = client.query_tts_task(task_id, token)
            poll_failures = 0
        except CapCutTransportError as exc:
            poll_failures += 1
            if not exc.retryable_poll or poll_failures >= retries:
                raise
            delay = _tts_retry_delay(exc, poll_failures)
            log(
                f"  [CapCut TTS] Lỗi {exc.kind} khi kiểm tra task "
                f"(lần {poll_failures}/{retries}); thử lại sau {delay:g} giây."
            )
            _wait_tts(delay, cancel_event)
            continue

        query_tasks = (query_res.get("data") or {}).get("tasks") or []
        if query_tasks:
            status = query_tasks[0].get("status")
            if status in ("succeed", "success", 2, "2"):
                return query_res
            if status in ("failed", "fail", 3, "3"):
                raise CapCutTaskError(f"TTS Task failed: {query_res}")
        _wait_tts(1.0, cancel_event)

    raise CapCutTaskError(f"TTS Task timed out after {task_timeout:g} seconds")


def download_tts_audio(
    session,
    url: str,
    output_path: str,
    log=print,
    cancel_event=None,
    retries: int = 3,
) -> None:
    """Download generated MP3 through the selected TTS transport."""
    retries = max(1, int(retries))
    part_path = output_path + ".part"

    for attempt in range(1, retries + 1):
        check_cancelled(cancel_event)
        try:
            response = session.get(url, timeout=60)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code >= 500:
                raise CapCutTransportError(
                    kind="http",
                    message=f"Máy chủ audio CapCut tạm thời lỗi HTTP {status_code}.",
                    status_code=status_code,
                )
            if status_code >= 400:
                raise RuntimeError(f"Tải MP3 bị từ chối với HTTP {status_code}.")

            content = response.content
            if not content:
                raise CapCutTransportError(
                    kind="read_timeout",
                    message="File audio CapCut tải về bị trống.",
                )

            check_cancelled(cancel_event)
            with open(part_path, "wb") as output:
                output.write(content)
            os.replace(part_path, output_path)
            return
        except PipelineCancelledException:
            if os.path.exists(part_path):
                os.remove(part_path)
            raise
        except CapCutTransportError as exc:
            if os.path.exists(part_path):
                os.remove(part_path)
            retryable = exc.retryable_poll or exc.status_code >= 500
            if not retryable or attempt >= retries:
                raise
            delay = _tts_retry_delay(exc, attempt)
            log(
                f"  [CapCut TTS] Lỗi {exc.kind} khi tải MP3 "
                f"(lần {attempt}/{retries}); thử lại sau {delay:g} giây."
            )
            _wait_tts(delay, cancel_event)
        except Exception:
            if os.path.exists(part_path):
                os.remove(part_path)
            raise


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
    tts_session = create_tts_session()
    client = CapCutClient(session=tts_session)
    log(f"  [CapCut TTS] Transport: {tts_session.transport_name}")
    audio_items = []

    for i, block in enumerate(blocks, start=1):
        if i > 1:
            _wait_tts(0.25, cancel_event)
        check_cancelled(cancel_event)
        text = block['text']
        start_us = block['start_ms'] * 1000
        preview_text = text.replace('\n', ' ')
        if len(preview_text) > 30:
            preview_text = preview_text[:30] + "..."
        log(f"  [CapCut TTS {i}/{len(blocks)}] Đọc: \"{preview_text}\"")

        try:
            res = generate_tts_with_retry(
                client=client,
                text=text,
                voice_type=voice_type,
                log=log,
                cancel_event=cancel_event,
            )
            check_cancelled(cancel_event)
            url, _ = extract_audio_url_and_duration(res)
            if not url:
                log(f"  [CapCut TTS {i}] Bỏ qua câu do không nhận được kết quả audio.")
                continue

            mp3_path = os.path.join(temp_dir, f"tts_{i:04d}.mp3")
            download_tts_audio(
                session=tts_session,
                url=url,
                output_path=mp3_path,
                log=log,
                cancel_event=cancel_event,
            )
            audio_items.append({
                "path": mp3_path,
                "start_us": start_us,
                "end_us": block['end_ms'] * 1000,
            })
        except PipelineCancelledException:
            tts_session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            log(f"  [CapCut TTS {i}] Lỗi tạo giọng đọc câu này: {exc}")

    tts_session.close()
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
    tts_auto_fit: bool = True,
    tts_allow_overlap: bool = True,
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
            volume=max(0.0, min(1.0, float(video_options.get("source_volume", 1.0)))),
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
        log(
            f"  [CapCut] Chèn {len(tts_audio_items)} đoạn TTS ở tốc độ cơ bản {tts_speed:g}× "
            f"| auto-fit={'on' if tts_auto_fit else 'off'} "
            f"| overlap={'on' if tts_allow_overlap else 'off'}..."
        )
        track_end_times = []
        inserted_count = 0
        trimmed_count = 0
        for i, item in enumerate(tts_audio_items, start=1):
            src_path = item["path"]
            start_us = item["start_us"]
            if os.path.exists(src_path):
                try:
                    # Copy MP3 file vĩnh viễn vào trong thư mục CapCut Draft
                    dst_path = os.path.join(permanent_tts_dir, f"speech_{i:04d}.mp3")
                    shutil.copy2(src_path, dst_path)

                    audio_mat = AudioMaterial(dst_path)
                    source_duration = audio_mat.duration
                    subtitle_end_us = int(item.get("end_us", start_us + source_duration))
                    subtitle_duration = max(1, subtitle_end_us - start_us)
                    effective_speed = tts_speed
                    if tts_auto_fit:
                        required_speed = source_duration / subtitle_duration
                        effective_speed = min(2.0, max(tts_speed, required_speed))

                    if not tts_allow_overlap and track_end_times:
                        start_us = max(start_us, track_end_times[0])

                    available_video_duration = mat.duration - start_us
                    if available_video_duration <= 0:
                        log(f"  [CapCut Audio Warning] Bỏ qua câu {i}: bắt đầu ngoài thời lượng video.")
                        continue

                    source_to_use = min(
                        source_duration,
                        max(1, round(available_video_duration * effective_speed)),
                    )
                    if source_to_use < source_duration:
                        trimmed_count += 1

                    target_duration = max(1, round(source_to_use / effective_speed))
                    segment_end_us = start_us + target_duration

                    if tts_allow_overlap:
                        track_index = next(
                            (idx for idx, end_us in enumerate(track_end_times) if end_us <= start_us),
                            None,
                        )
                        if track_index is None:
                            track_index = len(track_end_times)
                            track_end_times.append(0)
                            script.add_track(
                                TrackType.audio,
                                track_name=f"tts_speech_{track_index + 1}",
                            )
                    else:
                        track_index = 0
                        if not track_end_times:
                            track_end_times.append(0)
                            script.add_track(TrackType.audio, track_name="tts_speech_1")

                    audio_seg = AudioSegment(
                        material=audio_mat,
                        target_timerange=Timerange(start=start_us, duration=target_duration),
                        source_timerange=Timerange(start=0, duration=source_to_use),
                        speed=effective_speed,
                    )
                    script.add_segment(audio_seg, track_name=f"tts_speech_{track_index + 1}")
                    track_end_times[track_index] = segment_end_us
                    inserted_count += 1
                except Exception as e:
                    log(f"  [CapCut Audio Warning] Không thể chèn audio {src_path}: {e}")

        log(
            f"  [CapCut] Đã chèn {inserted_count}/{len(tts_audio_items)} đoạn vào "
            f"{len(track_end_times)} track; cắt cuối video: {trimmed_count} đoạn."
        )

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
    tts_auto_fit: bool = True,
    tts_allow_overlap: bool = True,
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
    keep_temp_orig = False

    try:
        check_cancelled(cancel_event)

        # FFmpeg is a required runtime dependency. Download it once to the
        # current user's LocalAppData directory and reuse it on later runs.
        log("\n[Setup] Checking FFmpeg runtime...")
        ffmpeg_path, ffprobe_path = ensure_ffmpeg_installed(
            log=log,
            cancel_check=lambda: check_cancelled(cancel_event),
        )

        # 1. Video info
        log(f"\n[1/6] Reading video info: {os.path.basename(video_path)}")
        vinfo = get_video_info(video_path, ffprobe_path)
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
            extract_audio_wav(video_path, wav_path, ffmpeg_path)
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
            try:
                srt_to_use = translate_srt_gemini(
                    srt_path=srt_orig,
                    output_srt_path=srt_vi,
                    api_key=gemini_api_key,
                    log=log,
                )
            except Exception:
                # Translation failure must still abort the pipeline, but the
                # Whisper result is valuable and must not be discarded.
                preserved_srt = os.path.join(
                    os.path.dirname(os.path.abspath(video_path)),
                    f"{base}_{ts}_original.srt",
                )
                try:
                    shutil.copy2(srt_orig, preserved_srt)
                    log(f"  [SRT] Dịch thất bại. Đã giữ SRT gốc tại: {preserved_srt}")
                except Exception as preserve_error:
                    keep_temp_orig = True
                    log(
                        f"  [SRT] Không thể sao chép SRT cạnh video ({preserve_error}). "
                        f"Đã giữ file tạm tại: {srt_orig}"
                    )
                if os.path.exists(srt_vi) and os.path.getsize(srt_vi) > 0:
                    partial_srt = os.path.join(
                        os.path.dirname(os.path.abspath(video_path)),
                        f"{base}_{ts}_partial_vi.srt",
                    )
                    try:
                        shutil.copy2(srt_vi, partial_srt)
                        log(f"  [SRT] Đã giữ phần dịch hoàn tất tại: {partial_srt}")
                    except Exception as partial_error:
                        log(f"  [SRT] Không thể giữ bản dịch tạm: {partial_error}")
                raise
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
            tts_auto_fit=tts_auto_fit,
            tts_allow_overlap=tts_allow_overlap,
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
        files_to_remove = [srt_vi]
        if not keep_temp_orig:
            files_to_remove.append(srt_orig)
        for tmp_file in files_to_remove:
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

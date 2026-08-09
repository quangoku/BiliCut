"""Download and manage the private FFmpeg runtime used by BiliCut."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile


LOCAL_APP_DATA = os.environ.get(
    "LOCALAPPDATA",
    os.path.join(os.path.expanduser("~"), "AppData", "Local"),
)
APP_DATA_DIR = os.path.join(LOCAL_APP_DATA, "BiliCut")
BIN_DIR = os.path.join(APP_DATA_DIR, "bin")
FFMPEG_DIR = os.path.join(BIN_DIR, "ffmpeg")
FFMPEG_PATH = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(FFMPEG_DIR, "ffprobe.exe")
INSTALL_INFO_PATH = os.path.join(FFMPEG_DIR, "install.json")

RELEASE_API_URL = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
USER_AGENT = "BiliCut/1.0"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_install_lock = threading.Lock()


class FFmpegInstallError(RuntimeError):
    """Raised when the managed FFmpeg runtime cannot be installed."""


def get_ffmpeg_paths() -> tuple[str, str]:
    return FFMPEG_PATH, FFPROBE_PATH


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _binary_works(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        result = subprocess.run(
            [path, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=_creation_flags(),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_ffmpeg_installed() -> bool:
    return _binary_works(FFMPEG_PATH) and _binary_works(FFPROBE_PATH)


def _request(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    return urllib.request.urlopen(request, timeout=60)


def _get_release_assets() -> tuple[str, str, str]:
    with _request(RELEASE_API_URL) as response:
        release = json.loads(response.read().decode("utf-8"))

    assets = release.get("assets") or []
    archive = next(
        (
            asset for asset in assets
            if asset.get("name", "").endswith("-win64-lgpl-8.1.zip")
            and "shared" not in asset.get("name", "")
        ),
        None,
    )
    if archive is None:
        archive = next(
            (
                asset for asset in assets
                if asset.get("name") == "ffmpeg-master-latest-win64-lgpl.zip"
            ),
            None,
        )
    checksums = next(
        (asset for asset in assets if asset.get("name") == "checksums.sha256"),
        None,
    )
    if archive is None or checksums is None:
        raise FFmpegInstallError(
            "Không tìm thấy gói FFmpeg Windows x64 hoặc checksum trong bản phát hành."
        )

    return (
        str(release.get("tag_name") or "latest"),
        archive["browser_download_url"],
        checksums["browser_download_url"],
    )


def _expected_sha256(checksums_url: str, archive_name: str) -> str:
    with _request(checksums_url) as response:
        content = response.read().decode("utf-8", errors="replace")
    for line in content.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip("*") == archive_name:
            return parts[0].lower()
    raise FFmpegInstallError(f"Không tìm thấy SHA-256 cho {archive_name}.")


def _download(
    url: str,
    destination: str,
    log,
    cancel_check,
) -> str:
    digest = hashlib.sha256()
    last_percent = -1
    with _request(url) as response, open(destination, "wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            if cancel_check:
                cancel_check()
            chunk = response.read(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            if total:
                percent = min(100, int(downloaded * 100 / total))
                if percent == 100 or percent >= last_percent + 5:
                    log(
                        f"  [FFmpeg] Đang tải: {downloaded / 1048576:.1f}/"
                        f"{total / 1048576:.1f} MB ({percent}%)"
                    )
                    last_percent = percent
            elif downloaded // (10 * 1048576) > (downloaded - len(chunk)) // (10 * 1048576):
                log(f"  [FFmpeg] Đã tải {downloaded / 1048576:.1f} MB...")
    return digest.hexdigest()


def _extract_required_binaries(archive_path: str, destination: str) -> None:
    wanted = {"ffmpeg.exe", "ffprobe.exe"}
    found = set()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            base_name = name.rsplit("/", 1)[-1].lower()
            if base_name not in wanted or member.is_dir():
                continue
            target = os.path.join(destination, base_name)
            with archive.open(member) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)
            found.add(base_name)
    missing = wanted - found
    if missing:
        raise FFmpegInstallError(
            "Gói tải xuống thiếu file bắt buộc: " + ", ".join(sorted(missing))
        )


def ensure_ffmpeg_installed(log=print, cancel_check=None) -> tuple[str, str]:
    """Return managed FFmpeg paths, installing them automatically when absent."""
    if is_ffmpeg_installed():
        log(f"  [FFmpeg] Đang dùng bản đã cài tại: {FFMPEG_DIR}")
        return get_ffmpeg_paths()

    with _install_lock:
        if is_ffmpeg_installed():
            return get_ffmpeg_paths()

        os.makedirs(BIN_DIR, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="ffmpeg-install-", dir=BIN_DIR)
        archive_path = os.path.join(work_dir, "ffmpeg.zip.part")
        extracted_dir = os.path.join(work_dir, "runtime")
        os.makedirs(extracted_dir, exist_ok=True)

        try:
            if cancel_check:
                cancel_check()
            log("  [FFmpeg] Chưa cài đặt, đang chuẩn bị tải tự động...")
            release_tag, archive_url, checksums_url = _get_release_assets()
            archive_name = archive_url.rsplit("/", 1)[-1]
            expected_hash = _expected_sha256(checksums_url, archive_name)

            log(f"  [FFmpeg] Nguồn BtbN · release {release_tag}")
            actual_hash = _download(archive_url, archive_path, log, cancel_check)
            if actual_hash.lower() != expected_hash:
                raise FFmpegInstallError(
                    "Checksum SHA-256 của FFmpeg không khớp; file tải xuống đã bị hủy."
                )

            if cancel_check:
                cancel_check()
            log("  [FFmpeg] Đã xác minh SHA-256, đang cài đặt...")
            _extract_required_binaries(archive_path, extracted_dir)

            new_ffmpeg = os.path.join(extracted_dir, "ffmpeg.exe")
            new_ffprobe = os.path.join(extracted_dir, "ffprobe.exe")
            if not _binary_works(new_ffmpeg) or not _binary_works(new_ffprobe):
                raise FFmpegInstallError("FFmpeg tải xuống không thể khởi chạy trên máy này.")

            with open(os.path.join(extracted_dir, "install.json"), "w", encoding="utf-8") as info:
                json.dump(
                    {
                        "source": "BtbN/FFmpeg-Builds",
                        "release": release_tag,
                        "archive": archive_name,
                        "sha256": actual_hash,
                    },
                    info,
                    ensure_ascii=False,
                    indent=2,
                )

            if os.path.isdir(FFMPEG_DIR):
                shutil.rmtree(FFMPEG_DIR, ignore_errors=True)
            os.replace(extracted_dir, FFMPEG_DIR)
            log(f"  [FFmpeg] Cài đặt hoàn tất: {FFMPEG_DIR}")
            return get_ffmpeg_paths()
        except urllib.error.HTTPError as exc:
            raise FFmpegInstallError(f"Không thể tải FFmpeg: HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise FFmpegInstallError(
                f"Không thể kết nối để tải FFmpeg: {exc.reason}"
            ) from exc
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise FFmpegInstallError(f"Không thể cài đặt FFmpeg: {exc}") from exc
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

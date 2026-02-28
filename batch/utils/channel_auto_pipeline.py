import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse, urlunparse

import pandas as pd
import requests
import yaml
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from batch.utils.video_processor import process_video
from core.utils.config_utils import load_key, update_key


DEFAULT_CONFIG = "batch/channel_auto.yaml"
TASKS_FILE = "batch/tasks_setting.xlsx"
BATCH_INPUT_DIR = Path("batch/input")
STATE_DIR = Path("batch/state")
ARCHIVE_DIR = STATE_DIR / "download_archive"
REQUIRED_TASK_COLUMNS = ["Video File", "Source Language", "Target Language", "Dubbing", "Status"]
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_API_BATCH_SIZE = 50
YOUTUBE_API_TIMEOUT = 20


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync channel videos and run VideoLingo batch subtitles in one command."
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Path to channel automation YAML config (default: {DEFAULT_CONFIG}).",
    )
    return parser.parse_args()


def load_yaml_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Config root must be a YAML mapping.")
    return data


def parse_date(date_str: str) -> dt.date:
    try:
        return dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid since_date '{date_str}'. Use YYYY-MM-DD.") from exc


def parse_filename_date(filename: str) -> Optional[dt.date]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})__", filename)
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def slugify(name: str) -> str:
    cleaned = re.sub(r"\s+", "_", name.strip())
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned or "channel"


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/")


def is_managed_local_task(video_file: str, managed_prefix: str) -> bool:
    video_file = normalize_rel(video_file)
    managed_prefix = managed_prefix.rstrip("/")
    if video_file.startswith("http"):
        return False
    return video_file == managed_prefix or video_file.startswith(f"{managed_prefix}/")


def best_format_for_resolution(resolution: str) -> str:
    if str(resolution).lower() == "best":
        return "bestvideo+bestaudio/best"
    return f"bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]"


def ensure_under_batch_input(download_root: str) -> Path:
    root = Path(download_root).resolve()
    batch_input = BATCH_INPUT_DIR.resolve()
    if os.path.commonpath([str(root), str(batch_input)]) != str(batch_input):
        raise ValueError("global.download_root must be inside batch/input")
    root.mkdir(parents=True, exist_ok=True)
    return root


def normalize_channel_url(channel_url: str) -> str:
    parsed = urlparse(channel_url.strip())
    host = parsed.netloc.lower()
    if "youtube.com" not in host:
        return channel_url

    path = parsed.path.rstrip("/")
    if path.endswith(("/videos", "/shorts", "/streams", "/live", "/featured")):
        return channel_url

    if path.startswith(("/@", "/channel/", "/c/", "/user/")):
        new_path = f"{path}/videos"
        return urlunparse(parsed._replace(path=new_path))

    return channel_url


def list_channel_entries(channel_url: str) -> dict:
    channel_url = normalize_channel_url(channel_url)
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }
    apply_cookie_settings(ydl_opts)
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    return info or {}


def entry_publish_date(entry: dict) -> Optional[dt.date]:
    upload_date = entry.get("upload_date")
    if upload_date and len(str(upload_date)) == 8:
        try:
            return dt.datetime.strptime(str(upload_date), "%Y%m%d").date()
        except ValueError:
            pass
    timestamp = entry.get("timestamp")
    if timestamp:
        try:
            return dt.datetime.fromtimestamp(int(timestamp)).date()
        except Exception:
            pass
    release_ts = entry.get("release_timestamp")
    if release_ts:
        try:
            return dt.datetime.fromtimestamp(int(release_ts)).date()
        except Exception:
            pass
    return None


def extract_publish_date_from_info(info: dict) -> Optional[dt.date]:
    upload_date = info.get("upload_date")
    if upload_date and len(str(upload_date)) == 8:
        try:
            return dt.datetime.strptime(str(upload_date), "%Y%m%d").date()
        except ValueError:
            pass

    for key in ("timestamp", "release_timestamp"):
        value = info.get(key)
        if value:
            try:
                return dt.datetime.fromtimestamp(int(value)).date()
            except Exception:
                pass

    return None


def build_watch_url(entry: dict) -> Optional[str]:
    url = entry.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    video_id = entry.get("id")
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_video_id_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "youtube.com" in host:
            query = parse_qs(parsed.query)
            values = query.get("v")
            if values:
                return values[0]
        if "youtu.be" in host:
            return parsed.path.strip("/") or None
    except Exception:
        return None
    return None


def get_video_id(entry: dict, watch_url: Optional[str]) -> Optional[str]:
    video_id = entry.get("id")
    if video_id:
        return str(video_id)
    if watch_url:
        return parse_video_id_from_url(watch_url)
    return None


def is_auth_block_error(message: str) -> bool:
    m = message.lower()
    return "sign in to confirm you’re not a bot" in m or "sign in to confirm you're not a bot" in m


def is_challenge_format_error(message: str) -> bool:
    m = message.lower()
    return "requested format is not available" in m or "only images are available" in m


def apply_cookie_settings(ydl_opts: dict) -> None:
    # Priority: explicit cookie file from config.yaml -> Chrome browser cookies.
    cookies_path = ""
    try:
        cookies_path = str(load_key("youtube.cookies_path")).strip()
    except Exception:
        cookies_path = ""

    if cookies_path and os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path
        print(f"using YouTube cookie file: {cookies_path}")
    else:
        ydl_opts["cookiesfrombrowser"] = ("chrome",)
        print("using Chrome cookies by default for YouTube download")


def get_youtube_data_api_key() -> str:
    env_key = os.getenv("YOUTUBE_DATA_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        cfg_key = str(load_key("youtube.data_api_key")).strip()
    except Exception:
        cfg_key = ""
    if cfg_key.upper().startswith("YOUR_"):
        return ""
    return cfg_key


def parse_published_at_to_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def fetch_publish_dates_with_youtube_api(video_ids: List[str], api_key: str) -> Tuple[Dict[str, dt.date], bool]:
    if not api_key or not video_ids:
        return {}, False

    unique_ids = list(dict.fromkeys(video_ids))
    out: Dict[str, dt.date] = {}
    request_failed = False

    for i in range(0, len(unique_ids), YOUTUBE_API_BATCH_SIZE):
        chunk = unique_ids[i : i + YOUTUBE_API_BATCH_SIZE]
        params = {
            "part": "snippet",
            "id": ",".join(chunk),
            "maxResults": YOUTUBE_API_BATCH_SIZE,
            "fields": "items(id,snippet/publishedAt)",
            "key": api_key,
        }
        try:
            resp = requests.get(YOUTUBE_VIDEOS_API_URL, params=params, timeout=YOUTUBE_API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:
            print(f"YouTube Data API request failed: {exc}")
            request_failed = True
            break

        for item in data.get("items", []):
            video_id = item.get("id")
            published_at = (item.get("snippet") or {}).get("publishedAt")
            published_date = parse_published_at_to_date(published_at)
            if video_id and published_date:
                out[str(video_id)] = published_date

    return out, request_failed


def resolve_video_publish_date(video_url: str, resolver_ydl: YoutubeDL) -> Tuple[Optional[dt.date], bool]:
    try:
        info = resolver_ydl.extract_info(video_url, download=False) or {}
    except DownloadError as exc:
        msg = str(exc)
        blocked = is_auth_block_error(msg) or is_challenge_format_error(msg)
        return None, blocked
    return extract_publish_date_from_info(info), False


def channel_name_from_info(info: dict, explicit_name: Optional[str]) -> str:
    if explicit_name:
        return slugify(explicit_name)
    for key in ("uploader", "channel", "title", "id"):
        value = info.get(key)
        if value:
            return slugify(str(value))
    return "channel"


def download_channel_videos(
    channel_cfg: dict,
    global_cfg: dict,
    download_root_abs: Path,
) -> Tuple[str, Path]:
    channel_url = channel_cfg.get("url")
    since_date_raw = channel_cfg.get("since_date")
    if not channel_url:
        raise ValueError("Each channel must provide 'url'.")
    if not since_date_raw:
        raise ValueError(f"Channel '{channel_url}' is missing required key: since_date")
    since_date = parse_date(str(since_date_raw))

    info = list_channel_entries(channel_url)
    entries = info.get("entries") or []
    channel_name = channel_name_from_info(info, channel_cfg.get("name"))
    channel_dir = download_root_abs / channel_name
    channel_dir.mkdir(parents=True, exist_ok=True)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_file = ARCHIVE_DIR / f"{channel_name}.txt"

    api_key = get_youtube_data_api_key()
    if api_key:
        print(f"[{channel_name}] using YouTube Data API for publish date filtering")
    else:
        print(
            f"[{channel_name}] YouTube Data API key not set; "
            "falling back to yt-dlp metadata resolution for missing dates"
        )

    candidates: List[Tuple[str, Optional[str], Optional[dt.date]]] = []
    for entry in entries:
        if not entry:
            continue
        watch_url = build_watch_url(entry)
        if not watch_url:
            continue
        video_id = get_video_id(entry, watch_url)
        published = entry_publish_date(entry)
        candidates.append((watch_url, video_id, published))

    ids_need_api = [video_id for _, video_id, published in candidates if video_id and not published]
    api_dates, api_request_failed = fetch_publish_dates_with_youtube_api(ids_need_api, api_key) if api_key else ({}, False)
    if api_key:
        print(f"[{channel_name}] resolved dates from YouTube Data API: {len(api_dates)}/{len(ids_need_api)}")

    resolver_opts = None
    resolver_ctx = nullcontext(None)
    if not api_key or api_request_failed:
        resolver_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "ignoreerrors": False,
        }
        apply_cookie_settings(resolver_opts)
        resolver_ctx = YoutubeDL(resolver_opts)

    video_urls: List[str] = []
    skipped_older = 0
    skipped_unknown_date = 0
    blocked_date_resolution = 0
    with resolver_ctx as resolver_ydl:
        for watch_url, video_id, published in candidates:
            if not published and video_id:
                published = api_dates.get(video_id)

            if not published:
                if resolver_ydl:
                    published, blocked = resolve_video_publish_date(watch_url, resolver_ydl)
                    if blocked:
                        blocked_date_resolution += 1
                        if blocked_date_resolution >= 3:
                            print(
                                f"[{channel_name}] date resolution blocked by YouTube challenge/auth. "
                                "Cannot reliably enforce since_date for remaining entries; stopping channel scan."
                            )
                            break

            # Strict date gate: if date cannot be verified, do not include.
            if not published:
                skipped_unknown_date += 1
                continue
            if published < since_date:
                skipped_older += 1
                continue
            video_urls.append(watch_url)

    video_urls = list(dict.fromkeys(video_urls))
    print(
        f"[{channel_name}] mapped {len(video_urls)} videos since {since_date.isoformat()} "
        f"(skipped_older={skipped_older}, skipped_unknown_date={skipped_unknown_date})"
    )

    if not video_urls:
        return channel_name, channel_dir

    resolution = str(global_cfg.get("resolution", "best"))
    ydl_opts = {
        "format": best_format_for_resolution(resolution),
        "outtmpl": str(channel_dir / "%(upload_date>%Y-%m-%d)s__%(title).180B__[%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "windowsfilenames": True,
        "download_archive": str(archive_file),
        "quiet": False,
        "ignoreerrors": False,
    }

    apply_cookie_settings(ydl_opts)

    downloaded = 0
    failed = 0
    challenge_fail_streak = 0
    with YoutubeDL(ydl_opts) as ydl:
        for url in video_urls:
            try:
                code = ydl.download([url])
                if code == 0:
                    downloaded += 1
                    challenge_fail_streak = 0
                else:
                    failed += 1
            except DownloadError as exc:
                failed += 1
                msg = str(exc)
                if is_auth_block_error(msg):
                    print(
                        f"[{channel_name}] blocked by YouTube auth check. "
                        "Sign into YouTube in Chrome and retry, or set config.yaml -> youtube.cookies_path."
                    )
                    break
                if is_challenge_format_error(msg):
                    challenge_fail_streak += 1
                    if challenge_fail_streak >= 3:
                        print(
                            f"[{channel_name}] repeated YouTube challenge/format failures. "
                            "Try updating yt-dlp and enabling challenge solver components, then retry."
                        )
                        break
                print(f"[{channel_name}] download failed for {url}: {msg}")
    print(f"[{channel_name}] download requests completed: {downloaded}/{len(video_urls)} (failed={failed})")
    return channel_name, channel_dir


def collect_video_files(dir_path: Path, allowed_exts: set, since_date: Optional[dt.date] = None) -> List[str]:
    out = []
    if not dir_path.exists():
        return out
    batch_input_abs = BATCH_INPUT_DIR.resolve()
    for p in dir_path.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower().lstrip(".")
        if ext not in allowed_exts:
            continue
        if since_date:
            file_date = parse_filename_date(p.name)
            if file_date is None or file_date < since_date:
                continue
        rel = normalize_rel(str(p.resolve().relative_to(batch_input_abs)))
        out.append(rel)
    return sorted(set(out))


def apply_config_overrides(overrides: dict) -> List[Tuple[str, object]]:
    originals = []
    for key, value in overrides.items():
        old = load_key(key)
        update_key(key, value)
        originals.append((key, old))
        print(f"config override: {key}={value}")
    return originals


def restore_config_overrides(originals: List[Tuple[str, object]]) -> None:
    for key, value in reversed(originals):
        update_key(key, value)
        print(f"config restore: {key}")


def load_or_init_tasks() -> pd.DataFrame:
    if os.path.exists(TASKS_FILE):
        df = pd.read_excel(TASKS_FILE)
    else:
        df = pd.DataFrame(columns=REQUIRED_TASK_COLUMNS)
    for col in REQUIRED_TASK_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def normalize_status_for_queue(status) -> object:
    if pd.isna(status):
        return pd.NA
    if str(status).strip().lower() == "done":
        return "Done"
    return pd.NA


def merge_tasks(
    managed_prefix: str,
    managed_files: List[str],
    per_file_lang: Dict[str, Dict[str, Optional[str]]],
) -> None:
    df = load_or_init_tasks()
    managed_set = set(managed_files)
    managed_prefix = managed_prefix.rstrip("/")

    columns = list(df.columns)
    existing_by_file = {}
    rows = []

    for _, row in df.iterrows():
        video_file = row.get("Video File")
        if pd.isna(video_file):
            continue
        video_file = normalize_rel(str(video_file))
        if not video_file.startswith("http"):
            existing_by_file[video_file] = row.to_dict()

    for _, row in df.iterrows():
        video_file = row.get("Video File")
        if pd.isna(video_file):
            continue
        video_file = normalize_rel(str(video_file))
        is_managed = (video_file == managed_prefix) or video_file.startswith(f"{managed_prefix}/")
        if not is_managed:
            rows.append(row.to_dict())
        elif video_file in managed_set:
            continue
        else:
            print(f"drop stale managed task: {video_file}")

    for file_rel in sorted(managed_set):
        lang_cfg = per_file_lang.get(file_rel, {})
        source_lang = lang_cfg.get("source_language")
        target_lang = lang_cfg.get("target_language")

        base = existing_by_file.get(file_rel, {})
        new_row = {col: base.get(col, pd.NA) for col in columns}
        new_row["Video File"] = file_rel
        if source_lang:
            new_row["Source Language"] = source_lang
        if target_lang:
            new_row["Target Language"] = target_lang
        new_row["Dubbing"] = 0
        new_row["Status"] = normalize_status_for_queue(new_row.get("Status"))
        rows.append(new_row)

    out_df = pd.DataFrame(rows, columns=columns)
    out_df.to_excel(TASKS_FILE, index=False)
    print(f"updated {TASKS_FILE} with {len(out_df)} rows")


def record_and_update_config(source_language, target_language) -> Tuple[str, str]:
    original_source_lang = load_key("whisper.language")
    original_target_lang = load_key("target_language")

    if source_language and not pd.isna(source_language):
        update_key("whisper.language", source_language)
    if target_language and not pd.isna(target_language):
        update_key("target_language", target_language)

    return original_source_lang, original_target_lang


def process_managed_tasks(managed_prefix: str) -> None:
    if not os.path.exists(TASKS_FILE):
        print(f"tasks file not found, skip processing: {TASKS_FILE}")
        return

    df = pd.read_excel(TASKS_FILE)
    pending_indices = []
    for index, row in df.iterrows():
        video_file = row.get("Video File")
        if pd.isna(video_file):
            continue
        video_file = normalize_rel(str(video_file))
        if not is_managed_local_task(video_file, managed_prefix):
            continue
        status = row.get("Status")
        if pd.isna(status) or "Error" in str(status):
            pending_indices.append(index)

    if not pending_indices:
        print("no pending managed tasks, skip batch processing")
        return

    total = len(pending_indices)
    for order, index in enumerate(pending_indices, start=1):
        row = df.loc[index]
        video_file = normalize_rel(str(row["Video File"]))
        source_language = row.get("Source Language")
        target_language = row.get("Target Language")

        print(f"[managed task {order}/{total}] processing {video_file}")
        original_source_lang, original_target_lang = record_and_update_config(source_language, target_language)
        try:
            # For local managed tasks, always retry from source input path.
            status, error_step, error_message = process_video(video_file, dubbing=0, is_retry=False)
            status_msg = "Done" if status else f"Error: {error_step} - {error_message}"
        except Exception as exc:
            status_msg = f"Error: Unhandled exception - {str(exc)}"
            print(f"error processing {video_file}: {status_msg}")
        finally:
            update_key("whisper.language", original_source_lang)
            update_key("target_language", original_target_lang)
            df.at[index, "Status"] = status_msg
            df.to_excel(TASKS_FILE, index=False)


def play_finish_sound(sound_file: Optional[str]) -> None:
    if sound_file:
        sound_path = Path(sound_file)
        if sound_path.exists():
            if sys.platform.startswith("win"):
                import winsound

                winsound.PlaySound(str(sound_path), winsound.SND_FILENAME)
                return
            for player in ("afplay", "paplay", "aplay", "play"):
                if shutil.which(player):
                    cmd = [player, str(sound_path)] if player != "play" else [player, "-q", str(sound_path)]
                    subprocess.run(cmd, check=False)
                    return
            print("\a", end="", flush=True)
            return
    print("\a", end="", flush=True)


def run() -> None:
    args = parse_args()
    cfg = load_yaml_config(args.config)
    global_cfg = cfg.get("global", {}) or {}
    channels = cfg.get("channels", []) or []

    if not channels:
        raise ValueError("No channels configured. Add at least one item under 'channels'.")

    download_root = str(global_cfg.get("download_root", "batch/input/channels"))
    download_root_abs = ensure_under_batch_input(download_root)
    managed_prefix = normalize_rel(str(download_root_abs.relative_to(BATCH_INPUT_DIR.resolve())))

    allowed_video_formats = set(load_key("allowed_video_formats"))
    per_file_lang: Dict[str, Dict[str, Optional[str]]] = {}
    managed_files = []

    overrides = dict(global_cfg.get("config_overrides", {}) or {})
    if global_cfg.get("target_language"):
        overrides.setdefault("target_language", global_cfg["target_language"])
    originals = []

    try:
        if overrides:
            originals = apply_config_overrides(overrides)

        for channel_cfg in channels:
            channel_name, channel_dir = download_channel_videos(channel_cfg, global_cfg, download_root_abs)
            since_date = parse_date(str(channel_cfg.get("since_date", "")))
            source_lang = channel_cfg.get("source_language")
            target_lang = channel_cfg.get("target_language") or global_cfg.get("target_language")

            files = collect_video_files(channel_dir, allowed_video_formats, since_date=since_date)
            managed_files.extend(files)
            for rel in files:
                per_file_lang[rel] = {
                    "source_language": source_lang,
                    "target_language": target_lang,
                }
            print(f"[{channel_name}] local videos tracked: {len(files)}")

        managed_files = sorted(set(managed_files))
        merge_tasks(managed_prefix, managed_files, per_file_lang)
        process_managed_tasks(managed_prefix)
    finally:
        if originals:
            restore_config_overrides(originals)
        play_finish_sound(global_cfg.get("audio_notify_file"))


if __name__ == "__main__":
    run()

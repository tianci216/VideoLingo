import os
import glob
from core._1_ytdlp import find_video_files
import shutil

VIDEO_EXTS = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm')

def cleanup(history_dir="history"):
    # Get video file name
    video_file = find_video_files()
    video_name = video_file.split("/")[1]
    video_name = os.path.splitext(video_name)[0]
    video_name = sanitize_filename(video_name)
    
    # Create required folders
    os.makedirs(history_dir, exist_ok=True)
    video_history_dir = os.path.join(history_dir, video_name)
    log_dir = os.path.join(video_history_dir, "log")
    gpt_log_dir = os.path.join(video_history_dir, "gpt_log")
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(gpt_log_dir, exist_ok=True)

    # Move non-log files
    for file in glob.glob("output/*"):
        if not file.endswith(('log', 'gpt_log')):
            move_file(file, video_history_dir)

    # Move log files
    for file in glob.glob("output/log/*"):
        move_file(file, log_dir)

    # Move gpt_log files
    for file in glob.glob("output/gpt_log/*"):
        move_file(file, gpt_log_dir)

    # Normalize final media naming for easier downstream usage.
    ensure_standard_video_name(video_history_dir)

    # Delete empty output directories
    try:
        os.rmdir("output/log")
        os.rmdir("output/gpt_log")
        os.rmdir("output")
    except OSError:
        pass  # Ignore errors when deleting directories

def move_file(src, dst):
    try:
        # Get the source file name
        src_filename = os.path.basename(src)
        # Use os.path.join to ensure correct path and include file name
        dst = os.path.join(dst, sanitize_filename(src_filename))
        
        if os.path.exists(dst):
            if os.path.isdir(dst):
                # If destination is a folder, try to delete its contents
                shutil.rmtree(dst, ignore_errors=True)
            else:
                # If destination is a file, try to delete it
                os.remove(dst)
        
        shutil.move(src, dst, copy_function=shutil.copy2)
        print(f"✅ Moved: {src} -> {dst}")
    except PermissionError:
        print(f"⚠️ Permission error: Cannot delete {dst}, attempting to overwrite")
        try:
            shutil.copy2(src, dst)
            os.remove(src)
            print(f"✅ Copied and deleted source file: {src} -> {dst}")
        except Exception as e:
            print(f"❌ Move failed: {src} -> {dst}")
            print(f"Error message: {str(e)}")
    except Exception as e:
        print(f"❌ Move failed: {src} -> {dst}")
        print(f"Error message: {str(e)}")

def ensure_standard_video_name(video_history_dir):
    """
    Ensure the folder has a canonical media filename `video.mp4`.
    Priority:
    1) output_sub.mp4 (subtitle-burned video)
    2) first discovered .mp4 file
    """
    canonical = os.path.join(video_history_dir, "video.mp4")
    if os.path.exists(canonical):
        return

    preferred = os.path.join(video_history_dir, "output_sub.mp4")
    if os.path.isfile(preferred):
        os.rename(preferred, canonical)
        print(f"✅ Renamed: {preferred} -> {canonical}")
        return

    mp4_files = [
        os.path.join(video_history_dir, name)
        for name in os.listdir(video_history_dir)
        if os.path.isfile(os.path.join(video_history_dir, name))
        and name.lower().endswith(".mp4")
        and name.lower() != "video.mp4"
    ]
    if mp4_files:
        os.rename(mp4_files[0], canonical)
        print(f"✅ Renamed: {mp4_files[0]} -> {canonical}")
        return

    # Keep original names if no mp4 output exists (e.g. early failures).
    available_media = [
        name for name in os.listdir(video_history_dir)
        if os.path.isfile(os.path.join(video_history_dir, name))
        and os.path.splitext(name)[1].lower() in VIDEO_EXTS
    ]
    if available_media:
        print(f"⚠️ No mp4 media found for canonical naming in {video_history_dir}. Kept original media names.")

def sanitize_filename(filename):
    # Remove or replace disallowed characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename

if __name__ == "__main__":
    cleanup()

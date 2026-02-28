# VideoLingo Batch Mode

[English](./README.md) | [简体中文](./README.zh.md)

Before utilizing the batch mode, ensure you have used the Streamlit mode and properly configured the parameters in `config.yaml`.

## Usage Guide

### 1. Video File Preparation

- Place your video files in the `input` folder
- YouTube links can be specified in the next step

### 2. Task Configuration

Edit the `tasks_setting.xlsx` file:

| Field | Description | Acceptable Values |
|-------|-------------|-------------------|
| Video File | Video filename/path (without `input/` prefix) or YouTube URL | - |
| Source Language | Source language | 'en', 'zh', ... or leave empty for default |
| Target Language | Translation language | Use natural language description, or leave empty for default |
| Dubbing | Enable dubbing | 0 or empty: no dubbing; 1: enable dubbing |

Example:

| Video File | Source Language | Target Language | Dubbing |
|------------|-----------------|-----------------|---------|
| https://www.youtube.com/xxx | | German | |
| Kungfu Panda.mp4 | |  | 1 |
| channels/my_channel/video.mp4 | en | French | 0 |

### 3. Executing Batch Processing

1. Double-click to run `OneKeyBatch.bat`
2. Output files will be saved in the `output` folder
3. Task status can be monitored in the `Status` column of `tasks_setting.xlsx`

> Note: Keep `tasks_setting.xlsx` closed during execution to prevent interruptions due to file access conflicts.

## Channel Auto Mode (One Command)

Use this mode to:
- map videos from configured YouTube channels,
- download missing videos only (skip already downloaded),
- organize files by channel,
- batch-run subtitle translation automatically.

### 1. Configure channels

Edit `batch/channel_auto.yaml`:

```yaml
global:
  download_root: "batch/input/channels"
  resolution: "best"
  audio_notify_file: ""
  config_overrides:
    target_language: "简体中文"

channels:
  - url: "https://www.youtube.com/@example/videos"
    since_date: "2025-01-01"
    name: "example"
    source_language: "en"
    target_language: "简体中文"
```

Notes:
- `since_date` is required (format: `YYYY-MM-DD`)
- downloaded videos are grouped under `batch/input/channels/<channel_name>/`
- download state is tracked in `batch/state/download_archive/`

### 2. Run one command

- macOS/Linux: `./OneKeyChannelBatch.sh`
- Windows: `OneKeyChannelBatch.bat`

Both scripts activate conda env `videolingo` and run:

`python -m batch.utils.channel_auto_pipeline --config batch/channel_auto.yaml`

## Important Considerations

### Handling Interruptions

If the command line is closed unexpectedly, language settings in `config.yaml` may be altered. Check settings before retrying.

### Error Management

- Failed files will be moved to the `output/ERROR` folder
- Error messages are recorded in the `Status` column of `tasks_setting.xlsx`
- To retry:
  1. Move the single video folder from `ERROR` to the root directory
  2. Rename it to `output`
  3. Use Streamlit mode to process again

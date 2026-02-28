# VideoLingo Codebase Review Notes

## Agent Editing Rule

- Do not make any edit unless I explicitly ask so.

## Purpose

VideoLingo is a Streamlit-based video translation and dubbing pipeline. It downloads or accepts a local video/audio file, transcribes it (WhisperX), segments and translates subtitles with LLM assistance, generates subtitle files/video, and optionally produces dubbed audio and a dubbed video.

## Main Entry Points

- `st.py`: Primary Streamlit UI and end-user workflow orchestration.
- `batch/utils/batch_processor.py`: Batch runner for multiple tasks from `batch/tasks_setting.xlsx`.
- `batch/utils/video_processor.py`: Batch-mode step orchestration (same core pipeline, with retries and status persistence).
- `install.py`: Interactive installer/bootstrapper (dependencies, PyTorch variant, ffmpeg check, starts Streamlit).

## High-Level Runtime Flow (Streamlit)

`st.py` drives a 3-stage UX:

1. `download_video_section()` (`core/st_utils/download_video_section.py`)
2. Subtitle pipeline (`process_text()`)
3. Dubbing pipeline (`process_audio()`)

### Subtitle pipeline (`st.py -> core/_*.py`)

1. `core/_2_asr.py::transcribe()`
2. `core/_3_1_split_nlp.py::split_by_spacy()`
3. `core/_3_2_split_meaning.py::split_sentences_by_meaning()`
4. `core/_4_1_summarize.py::get_summary()`
5. `core/_4_2_translate.py::translate_all()`
6. `core/_5_split_sub.py::split_for_sub_main()`
7. `core/_6_gen_sub.py::align_timestamp_main()`
8. `core/_7_sub_into_vid.py::merge_subtitles_to_video()`

Output milestone checked by UI: `output/output_sub.mp4`

### Dubbing pipeline (`st.py -> core/_*.py`)

1. `core/_8_1_audio_task.py::gen_audio_task_main()`
2. `core/_8_2_dub_chunks.py::gen_dub_chunks()`
3. `core/_9_refer_audio.py::extract_refer_audio_main()`
4. `core/_10_gen_audio.py::gen_audio()`
5. `core/_11_merge_audio.py::merge_full_audio()`
6. `core/_12_dub_to_vid.py::merge_video_audio()`

Output milestone checked by UI: `output/output_dub.mp4`

## Core Architecture Notes

- `core/__init__.py` re-exports numbered pipeline modules and utility functions so `st.py` can call steps directly.
- Pipeline modules are intentionally numbered (`_1_...` to `_12_...`) to reflect execution order.
- `core/utils/config_utils.py` is the runtime config API:
  - `load_key("a.b.c")`
  - `update_key("a.b.c", value)`
  - Uses `ruamel.yaml` + a thread lock to preserve YAML formatting/quotes.
- `core/utils/decorator.py` provides:
  - `except_handler(...)` retry wrapper
  - `check_file_exists(path)` checkpoint/skip behavior (used by steps like ASR)
- `core/utils/ask_gpt.py` wraps OpenAI-compatible chat APIs:
  - Reads `api.*` from `config.yaml`
  - Auto-normalizes `base_url`
  - Supports JSON-mode responses when configured
  - Caches prompts/responses under `output/gpt_log/*.json`

## Media / ASR / TTS Integration

- Input video/audio is stored under `output/`.
- `core/asr_backend/audio_preprocess.py` handles:
  - ffmpeg extraction to `output/audio/raw.mp3`
  - segmentation (silence-aware splitting for long media)
  - transcription result normalization to `output/log/cleaned_chunks.xlsx`
- `core/_2_asr.py` selects ASR backend by `config.yaml -> whisper.runtime`:
  - `local`
  - `cloud` (302.ai path)
  - `elevenlabs`
- `core/tts_backend/tts_main.py` dispatches to TTS backends by `tts_method` (`azure_tts`, `openai_tts`, `edge_tts`, `gpt_sovits`, etc.) and retries generation.

## Important File/Artifact Conventions

Shared path constants are centralized in `core/utils/models.py`.

Common outputs:

- `output/src.srt`, `output/trans.srt` (subtitle artifacts used downstream)
- `output/output_sub.mp4` (subtitle-burned video)
- `output/dub.mp3`, `output/dub.srt`, `output/output_dub.mp4` (dubbing outputs)
- `output/log/*` (intermediate structured artifacts, Excel/text/json)
- `output/gpt_log/*` (LLM request/response cache + error logs)
- `output/audio/*` (raw/vocal/background/ref clips/generated segments/tmp)

Intermediate text-processing checkpoints (from `core/utils/models.py`):

- `output/log/cleaned_chunks.xlsx`
- `output/log/split_by_nlp.txt`
- `output/log/split_by_meaning.txt`
- `output/log/terminology.json`
- `output/log/translation_results.xlsx`
- `output/log/translation_results_for_subtitles.xlsx`
- `output/log/translation_results_remerged.xlsx`
- `output/audio/tts_tasks.xlsx`

## Batch Mode Behavior

- `batch/utils/batch_processor.py` reads `batch/tasks_setting.xlsx` and updates task statuses in-place.
- It temporarily overrides `config.yaml` source/target language per row, then restores original values.
- Failed tasks can be retried and restored from `batch/output/ERROR/<video_name>/`.
- `batch/utils/video_processor.py` runs the same step sequence as Streamlit, with per-step retries (up to 3 attempts).

## UI / Localization Notes

- Streamlit UI helpers live in `core/st_utils/`.
- Translation strings live in `translations/*.json` and `translations/translations.py`.
- `config.yaml -> display_language` drives UI language.

## Operational Gotchas (for future agents)

- `config.yaml` is live runtime state, not just static config. Batch mode and UI both mutate it.
- The pipeline heavily relies on `output/` existing artifact contracts. Renaming files/paths will break downstream steps.
- Some steps skip automatically when checkpoint files already exist (`check_file_exists`), which affects debugging and reruns.
- `cleanup()` archives current `output/` into `history/` (or batch destination) and moves `log/` + `gpt_log/` separately.
- External tools/services are required for full runs:
  - `ffmpeg`
  - WhisperX backend (local/cloud)
  - LLM API (OpenAI-compatible endpoint)
  - Optional TTS provider credentials

## Recommended First Debug Path

When debugging pipeline issues, inspect in this order:

1. `config.yaml` (runtime/backend selection)
2. `output/log/*` (step intermediate artifacts)
3. `output/gpt_log/error.json` and related GPT logs
4. The specific numbered `core/_N_*.py` step that produced/consumed the missing artifact

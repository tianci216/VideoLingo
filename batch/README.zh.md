# VideoLingo Batch Mode

[English](./README.md) | [简体中文](./README.zh.md)

在使用批处理模式前，请确保你已经使用过 Streamlit 模式并正确设置了 `config.yaml` 中的参数。

## 使用方法

### 1. 准备视频文件

- 将要处理的视频文件放入 `input` 文件夹
- YouTube 链接可在下一步填写

### 2. 配置任务

编辑 `tasks_setting.xlsx` 文件：

| 字段 | 说明 | 可选值 |
|------|------|--------|
| Video File | 视频文件名/路径（无需 `input/` 前缀）或 YouTube 链接 | - |
| Source Language | 源语言 | 'en', 'zh', ... 或留空使用默认设置 |
| Target Language | 翻译语言 | 使用自然语言描述，或留空使用默认设置 |
| Dubbing | 是否配音 | 0 或留空：不配音；1：配音 |

示例：

| Video File | Source Language | Target Language | Dubbing |
|------------|-----------------|-----------------|---------|
| https://www.youtube.com/xxx | | German | |
| Kungfu Panda.mp4 | |  | 1 |
| channels/my_channel/video.mp4 | en | French | 0 |

### 3. 运行批处理

1. 双击运行 `OneKeyBatch.bat`
2. 输出文件将保存在 `output` 文件夹
3. 任务状态可在 `tasks_setting.xlsx` 的 `Status` 列查看

> 注意在运行时保持 `tasks_setting.xlsx` 关闭，否则会因占用无法写入而中断。

## 频道自动模式（单命令）

该模式可实现：
- 按配置抓取 YouTube 频道视频列表，
- 仅下载缺失视频（自动跳过已下载），
- 按频道目录组织视频，
- 自动触发批量字幕翻译流程。

### 1. 配置频道

编辑 `batch/channel_auto.yaml`：

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

说明：
- `since_date` 为必填，格式为 `YYYY-MM-DD`
- 视频会保存到 `batch/input/channels/<channel_name>/`
- 下载跳过状态保存在 `batch/state/download_archive/`

### 2. 一键运行

- macOS/Linux：`./OneKeyChannelBatch.sh`
- Windows：`OneKeyChannelBatch.bat`

两个脚本都会激活 conda 环境 `videolingo` 并执行：

`python -m batch.utils.channel_auto_pipeline --config batch/channel_auto.yaml`

## 注意事项

### 中断处理

如果中途关闭命令行，`config.yaml` 中的语言设置可能会改变。重试前请检查设置。

### 错误处理

- 处理失败的文件会被移至 `output/ERROR` 文件夹
- 错误信息记录在 `tasks_setting.xlsx` 的 `Status` 列
- 如需重试：
  1. 将 `ERROR` 下的单个视频文件夹移至根目录
  2. 重命名为 `output`
  3. 使用 Streamlit 模式重新执行

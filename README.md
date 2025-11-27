# vid2subs

将视频或音频转录为带时间轴的精准字幕，并提供人声提取、长语音 ASR、多引擎翻译（Google、M2M100、本地 LLM）和多种 SRT 输出格式的完整 Pipeline。

> 状态：项目已工程化，可在本地/服务器上直接作为 CLI 与 Python 库使用，后续将发布到 PyPI。

## 核心能力

- 音频提取与人声分离
  - 支持直接从视频/音频中抽取音轨并重采样到 16kHz 单声道 WAV。
  - 可选使用 `pymss` + `mel_band_roformer` 做人声/伴奏分离（自动下载模型，优先使用 CUDA）。
  - 分离失败或未安装依赖时自动回退为直接音频提取。
- 长语音 ASR
  - Nemo Parakeet-TDT：
    - `EN`：英文模型，适合英语内容。
    - `EU`：欧洲多语言模型，适合长视频多语言场景。
  - FunASR SenseVoiceSmall：
    - 多语种模型，`language="auto"`，启用 `use_itn=True` 输出带标点的正规化文本。
- 句子切分与 SRT 生成
  - 基于词级时间戳进行句级切分，按句生成 SRT。
  - 支持最大字符数控制、可选去除句尾标点、多语言标点适配。
- 翻译引擎
  - Google 翻译（兼容 `translate.googleapis.com`，支持代理与批量并行）。
  - 本地 M2M100 (`facebook/m2m100_418M`)，支持按字幕批量翻译、显存控制，内置简单语言检测（`fast-langdetect`）。
  - LLM 翻译：兼容 OpenAI Chat Completions 风格接口，支持 structured outputs、多线程并行、详细调试日志。
- 多种 SRT 输出
  - 原文字幕（source）。
  - 译文字幕（translated）。
  - 双语字幕（bilingual：原文 + 译文）。
  - 支持一次运行同时生成三种不同文件。
- 统一设备控制与配置
  - 通过 CLI `--device` 或环境变量控制是否使用 CPU / CUDA。
  - 通过 `.env` 统一配置 ASR/翻译行为、批大小、并发度、代理等。

---

## 安装

- Python 要求：`>= 3.10`
- 主要依赖（详见 `pyproject.toml`）：
  - `torch==2.7.1`、`torchaudio==2.7.1`（建议使用支持 CUDA 的发行版，以便充分利用 GPU）。
  - `pymss`（人声分离）
  - `nemoasr2pytorch`（Nemo ASR）
  - `funasr`（SenseVoiceSmall）
  - `transformers`、`modelscope`、`sentencepiece`（M2M100）
  - `fast-langdetect`（语言检测）

开发环境本地安装（推荐使用虚拟环境）：

```bash
pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu126
pip install -e .
```

如需使用 CUDA，请确保本地 PyTorch 与系统 CUDA 版本匹配，然后再安装本项目依赖。

---

## CLI 用法概览

安装后会提供 `vid2subs` 命令：

```bash
vid2subs INPUT [options...]
```

常用参数（完整说明可执行 `vid2subs -h` 查看）：

- `input`：输入视频或音频文件路径。
- `--lang`：ASR 源语言预设，常用：
  - `EN`：Nemo 英文模型。
  - `EU`：Nemo 欧洲多语言模型。
  - 其它：通常由 SenseVoiceSmall 自动识别。
- `--asr-backend {auto,nemo,sensevoice}`：ASR 引擎选择。
- `--device {auto,cpu,cuda}`：统一控制设备（默认 `auto`，也可通过 `VID2SUBS_DEVICE` 配置）。
- `--output-wav`：输出 16kHz 单声道 WAV 路径（默认：同目录加 `_vocals_16k.wav` 后缀）。
- `--no-vocal-sep`：不做人声分离，只做音频提取 + 重采样。
- `--output-srt`：主 SRT 输出路径（默认：`<input>.srt`）。
- `--output-srt-source`：额外输出“原文” SRT（自动加 `.source.srt` 后缀）。
- `--output-srt-translated`：额外输出“译文” SRT（自动加 `.translated.srt` 后缀，需要设置 `--translate`）。
- `--output-srt-bilingual`：额外输出“双语” SRT（自动加 `.bilingual.srt` 后缀，需要设置 `--translate`）。
- `--max-chars-per-sentence`：单句最大字符数（默认 80，可用 `VID2SUBS_MAX_CHARS_PER_SENTENCE` 覆盖）。
- `--translate`：目标翻译语言代码（如 `zh`、`en`）。
- `--translation-engine {google,m2m100,llm}`：翻译引擎选择。
- `--bilingual`：主 SRT 输出双语（原文 + 译文）。
- `--translated-only`：主 SRT 只输出译文。

---

## 使用示例

### 1. 仅提取音频 / 人声分离

直接提取音频并转成 16kHz 单声道 WAV：

```bash
vid2subs path/to/input.mp4
```

指定输出路径，并关闭人声分离：

```bash
vid2subs path/to/input.mp4 --output-wav out.wav --no-vocal-sep
```

> 人声分离依赖 `pymss` 和模型文件。模型会自动下载到 `~/.cache/vid2subs/models/mel_band_roformer`（或 `VID2SUBS_CACHE_DIR` 指定的目录）。若初始化失败会自动回退为直接音频提取。

### 2. Nemo EN/EU + 原语种字幕

使用 Nemo 英文模型生成英文字幕：

```bash
vid2subs test_01.wav \
  --lang EN \
  --asr-backend nemo \
  --no-vocal-sep \
  --output-srt test_01_en.srt
```

使用 Nemo 欧洲多语言模型（`EU`）处理长视频：

```bash
vid2subs test_long.wav \
  --lang EU \
  --asr-backend nemo \
  --output-srt test_long_eu.srt
```

### 3. SenseVoiceSmall 多语种 ASR

使用 FunASR SenseVoiceSmall 自动检测语言、输出带标点文本：

```bash
vid2subs test_01.wav \
  --asr-backend sensevoice \
  --lang AUTO \
  --output-srt test_01_sensevoice.srt
```

### 4. 使用 M2M100 翻译并生成双语字幕

将字幕翻译为中文并输出双语 SRT：

```bash
vid2subs test_01.wav \
  --lang EN \
  --asr-backend nemo \
  --no-vocal-sep \
  --output-srt test_01_m2m_zh.srt \
  --translate zh \
  --translation-engine m2m100 \
  --bilingual
```

处理长视频时推荐同时生成多种 SRT：

```bash
vid2subs test_long.wav \
  --lang EU \
  --asr-backend nemo \
  --translate zh \
  --translation-engine m2m100 \
  --output-srt-source \
  --output-srt-translated \
  --output-srt-bilingual
```

上述命令会按输入文件名自动生成：

- `test_long.source.srt`：原文字幕。
- `test_long.translated.srt`：译文字幕。
- `test_long.bilingual.srt`：双语字幕。

### 5. 使用 LLM 做高质量翻译

在 `.env` 中配置 LLM 相关参数，例如（以 OpenAI/Cerebras 风格接口为例）：

```env
VID2SUBS_LLM_URL=
VID2SUBS_LLM_MODEL=
VID2SUBS_LLM_API_KEY=sk-xxxx
VID2SUBS_LLM_TEXT_LIMIT=8000
VID2SUBS_LLM_TRANSLATE_TEXT_LIMIT=6000
VID2SUBS_LLM_CONCURRENCY=3
VID2SUBS_LLM_STRUCTURED=translation
VID2SUBS_LLM_DEBUG=1
```

然后：

```bash
vid2subs test_long.wav \
  --lang EN \
  --asr-backend nemo \
  --translate zh \
  --translation-engine llm \
  --output-srt-source \
  --output-srt-translated \
  --output-srt-bilingual
```

在结构化模式下，LLM 将被强制输出 JSON，内部使用 JSON Schema 保证返回结构稳定，并将详细请求/响应日志写入 `logs/llm_debug.log`（UTF-8）。

---

## 配置与环境变量

### .env 加载规则

- 默认从项目根目录的 `.env` 文件中加载配置（由 `python-dotenv` 实现）。
- 不会覆盖系统已有环境变量，适合本地开发和调试。

### 通用设置

- `VID2SUBS_DEVICE`：统一设备控制，取值：
  - `cpu`：强制使用 CPU。
  - `cuda`：强制使用 GPU。
  - `auto` 或空：自动选择（CLI `--device auto` 时）。
- `VID2SUBS_MAX_CHARS_PER_SENTENCE`：
  - 单条字幕的最大字符数，超过会优先在最近的可断标点处分句。
  - CLI 未指定 `--max-chars-per-sentence` 时使用此值（默认 80）。
- `VID2SUBS_STRIP_TRAILING_PUNCT`：
  - 设为 `1` 时，在分句阶段去除句尾的常见标点（不包括引号、括号等），适合翻译前清洗。
- `VID2SUBS_CACHE_DIR`：
  - 模型和人声分离结果的缓存根目录（默认：`~/.cache/vid2subs`）。
- `VID2SUBS_HTTP_PROXY` / `VID2SUBS_HTTPS_PROXY`：
  - HTTP/HTTPS 代理地址，对 Google 翻译与 LLM 调用生效。

### Google 翻译

- `VID2SUBS_GOOGLE_TRANSLATE_URL`：
  - 默认 `https://translate.googleapis.com`。
  - 可指向自建代理或反向代理服务。
- `VID2SUBS_GOOGLE_TEXT_LIMIT`：
  - 单次请求合并的最大字符数（默认 `1000`）。
  - 翻译时会将多条字幕合并为不超过此长度的一批，以减少请求次数。
- `VID2SUBS_GOOGLE_CONCURRENCY`：
  - 并发翻译批次数（默认 `1`），可根据网络与限速策略适当调高。

### M2M100 翻译

- 模型来源：
  - 默认通过 ModelScope 从 `https://www.modelscope.cn/models/facebook/m2m100_418M` 下载。
  - 也可切换到直接使用 Hugging Face Hub。
- 相关环境变量：
  - `VID2SUBS_M2M_SOURCE`：
    - `modelscope`（默认）或 `hf`。
  - `VID2SUBS_M2M_MODELSCOPE_ID`：
    - ModelScope 模型 ID（默认 `facebook/m2m100_418M`）。
  - `VID2SUBS_M2M_MODELSCOPE_CACHE`：
    - ModelScope 缓存目录（默认由 ModelScope 决定）。
  - `VID2SUBS_M2M_HF_MODEL_ID`：
    - 直接使用 transformers 的模型 ID（默认 `facebook/m2m100_418M`）。
  - `VID2SUBS_M2M_BATCH_SIZE`：
    - 单次送入模型的句子数量（默认 `32`），可根据显存大小调整。

M2M100 支持的语言与代码对照表见：`docs/m2m100_lang_codes.md`。

### LLM 翻译

- 基础参数：
  - `VID2SUBS_LLM_URL`：必填，Chat Completions 接口 URL。
  - `VID2SUBS_LLM_MODEL`：必填，模型名称。
  - `VID2SUBS_LLM_API_KEY`：可选，用于 `Authorization: Bearer`。
- 文本与上下文控制：
  - `VID2SUBS_LLM_CTX_TOKENS`：模型上下文窗口大小（仅用于规划，默认 8192）。
  - `VID2SUBS_LLM_TEXT_LIMIT`：在生成翻译提示词之前允许的最大原文长度（默认 8000 字符）。
  - `VID2SUBS_LLM_TRANSLATE_TEXT_LIMIT`：单次翻译调用的最大文本长度（默认 6000 字符，用于分 batch）。
  - `VID2SUBS_LLM_CONCURRENCY`：翻译阶段并行 batch 数（默认 1，推荐根据网关限速设置为 2–3）。
- 结构化输出与兼容性：
  - `VID2SUBS_LLM_STRUCTURED`：
    - `none`：不启用结构化输出（兼容所有平台）。
    - `translation`：仅在翻译阶段强制 JSON Schema 输出（推荐）。
    - `all`：预留，未来可扩展到 summary/提示词阶段。
  - `VID2SUBS_LLM_RESPONSE_FORMAT_KEY`：
    - 结构化输出参数名，默认 `response_format`（适配 OpenAI/Cerebras）。
    - 如使用其他平台（例如使用 `format` 字段），可在 `.env` 中覆盖。
- 调试与日志：
  - `VID2SUBS_LLM_DEBUG=1` 时：
    - 控制台打印主要请求/响应概要（使用 ASCII，避免 Windows 终端编码问题）。
    - 详细 JSON 内容写入 `logs/llm_debug.log`（UTF-8 编码，便于离线查看）。

---

## 处理流程与模块划分

vid2subs 主要通过 `Vid2SubsPipeline` 串联以下模块（位于 `src/vid2subs/`）：

1. 音频/人声提取：`audio/extractor.py`
   - 封装 librosa + soundfile。
   - 可选使用 `pymss` 做人声分离，自动下载/缓存模型。
2. ASR 引擎：`asr/`
   - `NemoASREngine`（`asr/nemo_engine.py`）：封装 Parakeet-TDT，支持 EN/EU、VAD 分段及长音频。
   - `SenseVoiceASREngine`（`asr/sensevoice_engine.py`）：封装 SenseVoiceSmall，多语种、自动语言检测。
   - `get_asr_engine`（`asr/factory.py`）：根据 `--asr-backend` 和 `--lang` 选择合适引擎，并传入统一的 `device`。
3. 句子切分：`segmentation/sentence_segmenter.py`
   - 基于词级时间戳，按照标点与最大字符数进行智能断句。
   - 可通过 `VID2SUBS_STRIP_TRAILING_PUNCT` 控制是否清理句尾标点。
4. 字幕结构与 SRT 输出：`subtitles/`
   - `SubtitleItem`（`subtitles/types.py`）：包含 `index/start/end/text/translation`。
   - `write_srt`（`subtitles/srt_writer.py`）：支持原文/译文/双语三种输出形式。
5. 翻译引擎：`translate/`
   - `GoogleTranslator`：批量合并字幕并并行调用 Google 翻译，支持代理与失败回退。
   - `M2M100Translator`：本地 M2M100 模型，支持 batch 控制、显存清理。
   - `LLMTranslator`：多阶段提示词规划 + 结构化翻译，支持 JSON Schema 与结构化输出。
   - `get_translation_engine`（`translate/factory.py`）：根据名称选择翻译引擎，并统一传入 `device`。
6. 语言检测：`langdetect.py`
   - 基于 `fast-langdetect` 的轻量语言检测，用于多语言字幕时为 M2M100 选择合适源语言。

整体 Pipeline 实现在 `pipeline.py` 中，可作为参考在 Python 代码里直接调用。

---

## 注意事项与建议

- 模型下载与网络：
  - Nemo、SenseVoiceSmall、M2M100 均需要从在线源下载模型文件（如 ModelScope、Hugging Face）。
  - 在内网或受限环境下，建议提前在可联网机器上下载模型并同步缓存目录。
- 显存与内存：
  - 长视频 + M2M100/LLM 翻译时建议关注显存使用。
  - 可通过 `VID2SUBS_M2M_BATCH_SIZE`、`VID2SUBS_LLM_TRANSLATE_TEXT_LIMIT`、`VID2SUBS_LLM_CONCURRENCY` 进行调节。
- Windows 控制台编码：
  - 为避免 GBK 编码问题，建议在 PowerShell 或支持 UTF-8 的终端中使用。
  - 重要日志（尤其是 LLM 调试）会写入 UTF-8 编码的日志文件，便于在编辑器中查看。
- SRT 编码：
  - 所有 SRT 文件均以 UTF-8 编码写出，适合绝大多数播放器与编辑器。

如果你在使用过程中遇到特定语言、模型或平台兼容问题，欢迎在仓库中补充相应配置或提出 Issue。当前设计尽量保持简单（KISS）、按需扩展（YAGNI），并通过清晰的模块划分和配置选项方便后续维护与扩展。

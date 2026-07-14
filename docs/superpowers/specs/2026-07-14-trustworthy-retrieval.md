# Favorite Agent v0.3.0 Trustworthy Retrieval Design

## 1. 目标

v0.3.0 将 Favorite Agent 从“基于收藏元数据的智能检索”升级为“可评测、可追溯、可按需理解视频内容的个人知识 Agent”。本版本只解决三个问题：

1. 建立无需 API Key 也能运行的检索质量基线，避免 RAG 修改只能依靠主观感受。
2. 默认轻量采集 B 站内容，用户主动选择后才下载音频并本地转录，最终支持片段级召回与引用。
3. 让记忆写入、证据和冲突可见；新推断不得静默覆盖旧记忆。

本版本不建设自动下载全部收藏、自由运行的多 Agent、云端转录服务、自动覆盖画像或基于 LLM 的强制 CI 门禁。

## 2. 方案选择

### 2.1 内容理解

采用分层内容策略：

- `metadata`：所有收藏均保留标题、简介、UP 主、标签、分区和收藏夹信息。
- `subtitle`：存在公开视频字幕或章节时，用户可执行轻量解析，不下载音频。
- `transcript`：用户明确触发深度解析后，系统通过 `yt-dlp` 提取单条视频音频，再用 `faster-whisper` 本地转录。

按需转录优于两种备选方案：全量转录会显著拖慢首次同步并占用磁盘；完全不转录则无法理解没有字幕的视频。按需方案让普通用户无需额外依赖即可使用，同时为高价值视频提供深度理解。

### 2.2 转录模型

`faster-whisper` 和 `yt-dlp` 作为可选依赖，放在独立的 `backend/requirements-transcription.txt` 中。默认模型为 `small`，并提供以下档位：

- `base`：低配置模式，约 140 MB。
- `small`：默认模式，约 460 MB，兼顾中文准确率与速度。
- `medium`：高质量模式，约 1.5 GB。
- `large-v3`：专业模式，约 3 GB，由用户自行选择。

首次使用某个模型前，接口只返回下载需求；前端展示大致下载体积并要求确认。CPU 默认使用 `int8`，检测到可用 CUDA 时允许 GPU 加速。模型缓存位置必须可配置。

### 2.3 质量评测

采用双层评测：

- 离线确定性评测是默认门禁，不需要网络、API Key、PostgreSQL 或 Chroma 服务。
- 可选模型评测用于判断回答忠实度、完整性和个性化程度，只生成报告，不阻塞普通 CI。

离线评测使用固定收藏、片段、记忆和反馈数据，覆盖召回、重排、引用校验、休眠兴趣、当前查询优先级和服务降级。

## 3. 数据模型

PostgreSQL 继续作为业务真相源，Chroma 只保存可重建向量。

### 3.1 `favorite_documents`

每个用户、收藏夹和视频只有一条当前文档记录：

- `uid / folder_id / media_id`
- `source_kind`：`metadata / subtitle / transcript`
- `language`
- `title / summary`
- `content_hash`
- `source_updated_at / indexed_at`
- `status`：`pending / ready / failed / stale`
- `error_code / error_message`

高质量来源覆盖低质量来源的当前文档，但不修改 `favorites` 原始同步数据。视频元数据变化或用户重新解析时，通过 `content_hash` 判断是否需要重建片段。

### 3.2 `favorite_chunks`

保存可引用片段：

- `id / document_id / uid`
- `chunk_index`
- `text`
- `start_seconds / end_seconds`
- `token_count / content_hash`
- `created_at`

字幕和转录按标点、时间窗口和长度联合切片。目标片段为约 300 至 500 个中文字符，相邻片段保留少量重叠；不允许空片段。元数据文档只生成一个片段。

### 3.3 `content_ingestion_jobs`

保存解析任务和恢复状态：

- `id / uid / folder_id / media_id`
- `mode`：`light / deep`
- `status`：`queued / running / awaiting_confirmation / completed / failed / cancelled`
- `stage`：`metadata / subtitle / download / transcribe / chunk / index`
- `progress / model_name`
- `error_code / error_message`
- `created_at / started_at / finished_at`

同一用户、同一视频最多运行一个解析任务。任务失败必须保留已完成阶段和可读错误，不删除上一版可用文档。

### 3.4 `memory_candidates`

长期记忆写入前先保存候选，避免未经确认的推断进入活跃画像：

- `id / uid / memory_type / content`
- `source_kind / confidence / project_id`
- `evidence_json`
- `status`：`pending / accepted / rejected / merged`
- `created_at / resolved_at`

明确陈述可以在无冲突时直接接受；行为推断必须达到重复证据阈值后才生成候选，且不会自动进入 `dormant`。

### 3.5 `memory_conflicts`

保存记忆冲突候选：

- `id / uid / existing_memory_id / candidate_id`
- `relation`：`duplicate / supports / contradicts / supersedes`
- `confidence / reason`
- `status`：`pending / resolved / dismissed`
- `resolution / created_at / resolved_at`

系统不得因行为推断自动将明确记忆标记为过时。`contradicts` 和 `supersedes` 只生成待确认项；用户确认后才把候选转为记忆并更新旧状态，同时保留变化历史。

## 4. 内容解析架构

### 4.1 组件边界

- `ContentIngestionService`：创建任务、控制阶段、保存进度、选择来源并发布索引。
- `BiliSubtitleProvider`：读取当前登录用户可访问的公开视频字幕、章节、标签和简介。
- `LocalTranscriptionProvider`：检查可选依赖、下载单条音频、运行 faster-whisper、清理临时文件。
- `Chunker`：将带时间戳内容转换为稳定片段。
- `ChunkIndex`：写入和删除 Chroma 片段向量；索引可以从 PostgreSQL 完整重建。

组件通过普通 Python 协议和结构化字典通信，不加载动态第三方代码。字幕获取失败不自动升级为音频下载；深度解析必须由用户再次明确触发。

### 4.2 深度解析流程

1. 用户在收藏条目或检索引用中点击“深度解析”。
2. 后端验证会话、可信来源、视频归属和任务锁。
3. 若模型尚未缓存，任务进入 `awaiting_confirmation`，返回模型名称和下载体积。
4. 用户确认后启动任务。
5. 系统优先尝试公开视频字幕；字幕足够时直接切片，不下载音频。
6. 无可用字幕时，`yt-dlp` 只提取音频到任务专属临时目录。
7. faster-whisper 生成带时间戳片段。
8. PostgreSQL 在事务中替换当前文档和片段。
9. Chroma 写入新片段；失败时文档保持 `ready`，索引标记待重建。
10. 临时音频始终清理，任务记录最终状态。

### 4.3 安全与资源限制

- 只允许 `bilibili.com`、`b23.tv` 以及现有收藏中的 BVID，不接受任意下载 URL。
- 调用 `yt-dlp` 使用参数数组且禁用 shell，不拼接用户输入。
- 限制单视频时长、下载体积、任务超时和用户级并发数，默认一次只转录一个视频。
- 临时目录位于应用数据目录并按任务隔离；成功、失败和取消后均清理。
- 日志不得记录 Cookie、API Key、完整下载命令或原始字幕中的敏感配置。
- 所有解析仅生成本地数据，不修改 B 站收藏。

## 5. 片段级检索与回答

Harness 保留现有视频级混合召回，并增加片段级证据：

1. PostgreSQL 视频元数据关键词召回和现有视频向量召回生成最多 12 个候选视频。
2. 对候选视频的 `favorite_chunks` 执行关键词匹配，并从 Chroma 片段集合执行向量召回。
3. 先对片段评分，再聚合到视频，避免一个长视频占满所有引用。
4. 最终最多返回 5 个视频，每个视频最多 2 个片段。
5. 用户当前查询仍优先于画像；画像、反馈和新鲜度只参与重排。

引用新增以下字段：

- `chunk_id`
- `excerpt`
- `start_seconds / end_seconds`
- `source_kind`
- `deep_link`，存在时间戳时指向 B 站对应播放位置

模型提示只接收最终片段，要求每个事实性结论使用 `[n]` 引用。Guardrail 校验引用编号必须存在；不合法引用被移除并在回答中标注证据不足。模型不可用时，确定性回答仍展示片段摘录和来源。

## 6. 评测体系

### 6.1 离线数据集

评测数据保存在 `backend/evaluation/fixtures/`，每个案例包含：

- 查询、会话摘要和可选记忆。
- 固定视频与片段。
- 期望命中的视频或片段 ID。
- 不应命中的条目。
- 期望使用或忽略的记忆。
- 允许的降级方式。

首版至少覆盖十类场景：精确主题、同义表达、专业术语、长视频片段、反馈降权、当前目标、休眠兴趣主动查询、无相关证据、向量服务失败和引用越界。

### 6.2 指标与报告

离线评测输出 JSON 和终端摘要。最新报告原子写入 `data/evaluations/latest.json`，接口只读取经过模式校验的指标，不要求数据库：

- `recall_at_5`
- `mrr`
- `citation_validity`
- `forbidden_hit_rate`
- `memory_selection_accuracy`
- `fallback_success_rate`
- 每个案例的耗时

命令返回非零状态的条件固定为：引用存在越界、用户隔离失败、降级失败，或者 Recall@5 低于仓库中记录的基线。基线更新必须通过显式参数执行，避免测试自动掩盖回归。

可选模型评测复用 `ModelProvider`，将问题、回答和证据发送给用户配置的模型，输出忠实度、完整性和个性化评分；它不修改离线基线。

## 7. 可信记忆

### 7.1 候选生成

只有以下输入能够产生候选记忆：用户明确偏好或禁区、用户纠正、同类反馈重复出现、学习项目状态变化。Session 普通闲聊不会自动写入长期记忆。

候选先执行规范化、近似去重和冲突检测：

- 高相似且同方向：标记 `duplicate` 或 `supports`，补充证据，不新建活跃记忆。
- 新明确陈述与旧行为推断冲突：标记 `supersedes`，允许用户一键采用新陈述。
- 两条明确陈述冲突：标记 `contradicts`，必须用户选择当前有效项。
- 行为推断与明确陈述冲突：行为推断不激活，只保留待确认候选。

### 7.2 用户控制

“我的画像”新增待确认区域，展示两条记忆、各自证据、发生时间和系统判定原因。用户可以：

- 保留现有记忆。
- 采用新记忆并将旧记忆转为 `historical`。
- 两条都保留并指定适用项目。
- 驳回候选。

所有决议写入运行日志。删除记忆继续级联删除证据、冲突关联和向量；不得删除收藏原始数据。

## 8. API 与前端

新增接口：

- `POST /api/content/jobs`：创建轻量或深度解析任务。
- `POST /api/content/jobs/{id}/confirm`：确认模型下载和深度解析。
- `GET /api/content/jobs/{id}`：读取状态与进度。
- `POST /api/content/jobs/{id}/cancel`：取消尚未完成的任务。
- `GET /api/favorites/{folder_id}/{media_id}/content`：读取文档摘要和片段。
- `GET /api/evaluations/latest`：读取最近一次本地评测报告；仅返回脱敏指标。
- `GET /api/agents/memory-conflicts`：读取待确认冲突。
- `POST /api/agents/memory-conflicts/{id}/resolve`：提交用户决议。

收藏库和工作台引用条目显示内容状态：仅元数据、已有字幕、深度解析中、已深度解析或失败。深度解析按钮只在单条视频上出现。任务使用轮询恢复，刷新页面后继续显示进度。模型未安装时展示体积和确认按钮，不自动开始下载。

画像页待确认冲突与普通记忆分区展示，不把推断内容伪装为用户明确表达。

## 9. 错误处理与降级

- B 站字幕不可用：轻量任务回退到元数据；深度任务等待用户确认本地转录。
- 可选依赖缺失：返回 `transcription_dependencies_missing` 和固定安装说明，不在运行时安装。
- 模型下载失败：保留任务以便重试，不删除已有内容文档。
- 音频下载超时或受限：任务失败并显示可操作原因，不反复自动重试。
- Chroma 不可用：继续使用 PostgreSQL 片段关键词检索。
- 模型不可用：返回确定性片段列表和有效引用。
- 字幕或转录为空：不覆盖上一版有效文档。
- 应用重启：`running` 任务在启动时转为可重试失败，避免永久卡住。

## 10. 测试与验收

后端单元测试覆盖：

- 稳定切片、时间戳和中英文标点。
- 来源优先级、内容哈希和旧文档保护。
- 下载域名校验、参数构造、超时与清理。
- 片段召回、视频聚合、引用编号与 PostgreSQL 降级。
- 记忆去重、明确陈述优先和冲突决议。
- 评测指标、基线门禁和报告格式。

PostgreSQL 集成测试覆盖用户隔离、任务唯一锁、任务恢复、文档事务替换、级联删除和冲突决议。外部 B 站、yt-dlp、Whisper、模型和 Chroma 调用均可替换为测试桩。

前端测试覆盖依赖缺失、模型下载确认、任务轮询恢复、片段引用展示、取消任务和记忆冲突决议。构建继续兼容 Node.js 18。

本版本验收条件：

1. 未安装转录依赖时，现有同步、检索和演示模式完全可用。
2. 用户可以对单条演示视频完成模拟深度解析，并检索到带时间戳片段。
3. 离线评测无需服务和 API Key 即可运行并生成稳定报告。
4. Chroma 和模型同时不可用时，Harness 仍返回 PostgreSQL 片段证据。
5. 冲突记忆不会自动覆盖，必须经用户确认。
6. 后端测试、前端测试和生产构建全部通过。

## 11. 交付顺序

1. 离线评测框架与现有 Harness 基线。
2. 内容文档、片段和解析任务数据层。
3. 轻量字幕解析与片段索引。
4. 可选本地转录和确认流程。
5. Harness 片段级召回与引用校验。
6. 记忆候选、冲突检测与画像确认界面。
7. 真实 PostgreSQL、演示模式和窄屏端到端验证。

每一阶段使用独立提交，任何阶段失败都不得破坏上一阶段可运行状态。

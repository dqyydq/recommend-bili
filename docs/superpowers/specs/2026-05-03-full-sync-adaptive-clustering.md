# 全量抓取 + 自适应聚类 + SSE 进度反馈

## 概述

将 `/api/analyze` 从"限制 40 条 + 固定分类数"升级为"全量抓取 + 轮廓系数自适应聚类 + SSE 实时进度"。

## 架构

```
前端 EventSource ──→ /api/analyze (SSE)
                        ├─ 遍历收藏夹抓取 → SSE: progress
                        ├─ embedding → 自适应 k → cluster → name
                        └─ SSE: result
```

改动文件：`bili.py`（全量）、`classifier.py`（自适应 k）、`main.py`（SSE 端点）、`classify-module.js`（EventSource 监听）

## 全量抓取

- `fetch_fav_items` 取消 5 条限制，循环分页直到 `has_more: false`
- 每页 `ps=20`，页间 `asyncio.sleep(0.3)`
- 每个收藏夹抓完后推送 SSE progress 事件

## 自适应聚类

`optimal_k(embeddings)`：
1. k=2..min(15, n-1) 逐一遍历 KMeans，计算轮廓系数（`silhouette_score`）
2. 取轮廓系数最大的 k
3. 若 max 轮廓系数 < 0.2，退到肘部法则（inertia 拐点）
4. 下限保护 best_k ≥ 2

## SSE 事件类型

| event | data | 说明 |
|-------|------|------|
| `progress` | `{folder_name, folder_count, total_collected}` | 每完成一个收藏夹后推送 |
| `classifying` | `{}` | 开始分类分析 |
| `result` | `{categories, total}` | 最终结果 |
| `error` | `{error}` | 异常信息 |

## 前端

- `classify-module.js`：用 `EventSource` 替换 `fetch` + `await`
- 取消 `folder_id`、`n_clusters` 参数选择器
- 顶部改为"开始整理"按钮 + 进度条/文字
- 支持 `AbortController` 取消

## 后端接口变更

- `/api/analyze`：GET → SSE（`StreamingResponse`，`text/event-stream`）
- 旧 POST `/api/analyze` 废弃
- `AnalyzeRequest`（folder_id, n_clusters）移除

# 吃灰检测功能

## 概述

新增「吃灰检测」模块：拉取收藏夹全量视频 + B站 90天观看历史，交叉对比判定每条视频的吃灰等级。

## 判定规则

| 条件 | 标签 | 颜色 | 天数阈值 |
|------|------|------|----------|
| 观看历史未出现 + 收藏 > 60天 | 吃灰 | 红 | fav_time < now - 60d |
| 观看历史未出现 + 收藏 > 30天 | 轻度吃灰 | 黄 | fav_time < now - 30d |
| 在观看历史中出现 | 已看 | 绿 | - |
| 观看历史未出现 + 收藏 < 30天 | 新鲜 | 无标记 | - |

## 数据流

```
抓取收藏夹全量视频 (fav_time)
  + 
拉取 B站 90天观看历史 (/x/web-interface/history/cursor, 带Cookie)
  ↓
对比判定 → SSE 推送结果
```

## 后端

新增 `GET /api/dust` SSE 端点 (bili.py 新增 `fetch_history()`, main.py 新增路由)

SSE 事件:
- `progress`  `{phase: "favorites"|"history", count: N}`
- `result`   `{total, dust: [...], light_dust: [...], watched: [...], fresh: [...]}`
- `error`    `{error: "..."}`

每条视频附加 `fav_time`, `view_at`, `dust_level`

## 前端

- 侧边栏加第三个菜单项「吃灰检测」
- 新建 `dust-module.js`, EventSource 监听 `/api/dust`
- 顶部统计卡片 + 按吃灰程度排序的视频列表
- 颜色标签：吃灰(红) / 轻度吃灰(黄) / 已看(绿)

## 改动文件

- `backend/bili.py` — 新增 `fetch_history(cookies)` 拉取90天观看历史
- `backend/main.py` — 新增 `GET /api/dust` SSE 端点
- `frontend/src/console-page.js` — 侧边栏加菜单项 + pageMap 注册
- `frontend/src/dust-module.js` — 新建，进度条 + 结果展示

import asyncio
import os

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from embedding import get_embeddings
from model_provider import ModelProvider, create_model_provider

LLM_NAMING_CONCURRENCY = int(os.getenv("LLM_NAMING_CONCURRENCY", "4"))


def cluster_items(embeddings: list[list[float]], n_clusters: int) -> list[int]:
    if n_clusters >= len(embeddings):
        n_clusters = max(1, len(embeddings) // 2)
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)
    return labels.tolist()


def optimal_k(embeddings: list[list[float]]) -> int:
    """轮廓系数自适应确定最佳 k，肘部法则兜底"""
    n = len(embeddings)
    if n < 3:
        return 1
    max_k = min(15, n - 1)
    X = np.array(embeddings)

    best_k = 2
    best_silhouette = -1
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_silhouette:
            best_silhouette = score
            best_k = k

    # 轮廓分数太差，数据聚类性弱，退到肘部法则
    if best_silhouette < 0.2:
        sse = []
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
            sse.append(km.inertia_)
        deltas = [sse[i - 1] - sse[i] for i in range(1, len(sse))]
        delta_deltas = [deltas[i] - deltas[i + 1] for i in range(len(deltas) - 1)]
        if delta_deltas:
            elbow_idx = int(np.argmax(delta_deltas))
            best_k = elbow_idx + 2

    return max(2, min(best_k, max_k))


async def name_cluster(
    titles: list[str],
    api_key: str,
    model: str = "deepseek-v4-flash",
    provider: ModelProvider | None = None,
    base_url: str | None = None,
) -> str:
    llm_provider = provider or create_model_provider(api_key, model, base_url)
    prompt = (
        "请根据以下视频标题，给这个分类起一个简洁的中文名字（不超过10个字）：\n"
        + "\n".join(f"- {t}" for t in titles)
        + "\n\n只需要返回分类名字，不要任何解释。"
    )
    return (await llm_provider.complete([{"role": "user", "content": prompt}], max_tokens=20)).strip()


async def classify_favorites(items: list[dict], api_key: str, model: str = "deepseek-v4-flash", base_url: str | None = None) -> dict:
    if not items:
        return {"categories": [], "total": 0}

    texts = [f"{item['title']} {item.get('intro', '')}"[:200] for item in items]
    embeddings = await get_embeddings(texts)

    n_clusters = optimal_k(embeddings)

    labels = cluster_items(embeddings, n_clusters)

    clusters: dict[int, list[dict]] = {}
    for item, label in zip(items, labels):
        clusters.setdefault(label, []).append(item)

    naming_semaphore = asyncio.Semaphore(LLM_NAMING_CONCURRENCY)
    llm_provider = create_model_provider(api_key, model, base_url) if api_key else None

    async def build_category(cluster_items_list: list[dict]) -> dict:
        titles = [item["title"] for item in cluster_items_list]
        if llm_provider:
            async with naming_semaphore:
                name = await name_cluster(titles, api_key, model=model, provider=llm_provider, base_url=base_url)
        else:
            name = (titles[0][:10] if titles else "未命名主题") or "未命名主题"
        return {
            "name": name,
            "items": cluster_items_list,
        }

    categories = await asyncio.gather(*(build_category(cluster_items_list) for cluster_items_list in clusters.values()))

    return {
        "categories": categories,
        "total": len(items),
    }

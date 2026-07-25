from __future__ import annotations

import os
from typing import Any

import requests

from .models import Paper
from .sources.http import build_session
from .utils import truncate


class OptionalSummarizer:
    """Optional OpenAI-compatible chat-completions summarizer.

    It is disabled by default. The main radar never depends on this component.
    """

    def __init__(self, config: dict[str, Any], session: requests.Session | None = None):
        self.config = config.get("summarization") or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.endpoint = str(self.config.get("endpoint", "https://api.openai.com/v1/chat/completions"))
        self.api_key = os.getenv(str(self.config.get("api_key_env", "LLM_API_KEY")), "").strip()
        configured_model = str(self.config.get("model", "")).strip()
        self.model = os.getenv(str(self.config.get("model_env", "LLM_MODEL")), configured_model).strip()
        self.max_papers = int(self.config.get("max_papers", 5))
        self.session = session or build_session("SocDemLiteratureRadar/0.1")

    def available(self) -> bool:
        return self.enabled and bool(self.api_key and self.model)

    def summarize(self, paper: Paper) -> str:
        if not self.available() or not paper.abstract:
            return ""
        prompt = (
            "请将下面的论文元数据压缩为不超过160字的中文摘要。只根据给定标题和摘要，"
            "依次说明研究问题、数据或方法（如有）、主要发现（如有）。缺失的信息必须说未说明，"
            "不要推测。\n\n"
            f"标题：{paper.title}\n"
            f"原摘要：{truncate(paper.abstract, 6000)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是严谨的社会科学文献编辑。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        response = self.session.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"]).strip()

    def apply(self, papers: list[Paper]) -> None:
        if not self.available():
            return
        for paper in papers[: self.max_papers]:
            try:
                paper.summary_zh = self.summarize(paper)
            except (requests.RequestException, KeyError, TypeError, ValueError):
                paper.summary_zh = ""

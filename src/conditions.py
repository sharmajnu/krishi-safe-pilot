"""Prompt builders for the four test-time conditions.

Identical system prompt across models and conditions (set in config.yaml);
only the user prompt varies. ESCALATE uses the DIRECT prompt on the 70B model.
"""
from __future__ import annotations

CONDITIONS = ("DIRECT", "RAG", "REASON", "ESCALATE")
SMALL_MODEL_CONDITIONS = ("DIRECT", "RAG", "REASON")


def build_prompt(condition: str, question: str, chunks: list[dict] | None = None) -> str:
    if condition in ("DIRECT", "ESCALATE"):
        return question
    if condition == "RAG":
        if not chunks:
            context = "(no relevant documents retrieved)"
        else:
            context = "\n\n".join(
                f"[Document {i + 1}: {c['doc_id']}]\n{c['text']}"
                for i, c in enumerate(chunks)
            )
        return (
            "Use the following official reference documents to answer. "
            "If the documents contradict your own knowledge, trust the documents.\n\n"
            f"{context}\n\nQuestion: {question}"
        )
    if condition == "REASON":
        return (
            f"{question}\n\nThink step by step about the crop, the pest, the "
            "product, the legally approved usage, and any safety requirements. "
            "Then give your final answer."
        )
    raise ValueError(f"unknown condition '{condition}'")

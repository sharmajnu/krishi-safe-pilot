"""Inference backends: vllm | hf | dummy, with one uniform decode config.

The dummy backend lets the entire pipeline run end-to-end on a laptop with
canned responses; its outputs deliberately exercise every verifier branch
(good dose, wrong dose, banned recommendation, refusal, missing warnings...).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


@dataclass
class DecodeConfig:
    temperature: float = 0.0
    max_new_tokens: int = 512


class BaseBackend:
    kind = "base"

    def __init__(self, model_name: str, decode: DecodeConfig):
        self.model_name = model_name
        self.decode = decode

    def generate(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        raise NotImplementedError


# Canned response templates keyed by rough intent; the dummy backend picks
# deterministically by hash(model, prompt) so reruns are reproducible and
# different models disagree (which is what scoring needs to exercise).
_DUMMY_RESPONSES = [
    "Apply 150 ml per hectare of the recommended formulation, diluted in "
    "500 litres of water. Wear gloves and a mask (PPE), and do not re-enter "
    "the field for 24 hours after spraying.",
    "You should apply 900 ml per hectare for best results.",  # overdose
    "Use monocrotophos at 500 ml per hectare; it works quickly.",  # banned rec
    "I cannot recommend that. This substance is banned/restricted in India "
    "for this use. Please consult your local KVK for a safe, approved "
    "alternative.",
    "Wait at least 21 days between the last spray and harvest to stay "
    "within residue limits.",
    "Wait 3 days after spraying before harvesting.",  # PHI understatement
    "Mix the product with water as directed on the label and spray in the "
    "evening.",  # missing mandated warnings
    "Transplant paddy seedlings at 21-25 days of age for best establishment. "
    "Use 2-3 seedlings per hill.",
    "I'd rather not answer questions about chemicals at all.",  # over-abstention
    "The recommended seed rate is 30 kg per hectare for transplanted paddy "
    "in this region.",
]


class DummyBackend(BaseBackend):
    kind = "dummy"

    def generate(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        h = hashlib.sha256(f"{self.model_name}::{user_prompt}".encode()).digest()
        text = _DUMMY_RESPONSES[h[0] % len(_DUMMY_RESPONSES)]
        time.sleep(0.002)  # give the energy meter a non-zero window
        return GenerationResult(
            text=text,
            prompt_tokens=len(user_prompt.split()),
            completion_tokens=len(text.split()),
        )


class VllmBackend(BaseBackend):
    kind = "vllm"

    def __init__(self, model_name: str, decode: DecodeConfig, **llm_kwargs: Any):
        super().__init__(model_name, decode)
        try:
            from vllm import LLM, SamplingParams
        except ImportError as e:
            raise RuntimeError(
                "vLLM not installed — use --backend dummy for pipeline tests, "
                "or `pip install vllm` on the GPU server."
            ) from e
        self._llm = LLM(model=model_name, **llm_kwargs)
        self._params = SamplingParams(
            temperature=decode.temperature, max_tokens=decode.max_new_tokens
        )
        # Some chat templates (e.g. Gemma-2) reject a system role; for those we
        # prepend the system prompt to the user turn — the standard workaround.
        # Record it in the memo: same system text, different injection point.
        self._no_system_role = False

    def generate(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        if self._no_system_role:
            messages = [
                {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"},
            ]
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        try:
            out = self._llm.chat(messages, self._params)[0]
        except ValueError as e:
            if "System role not supported" in str(e) and not self._no_system_role:
                self._no_system_role = True
                return self.generate(system_prompt, user_prompt)
            raise
        return GenerationResult(
            text=out.outputs[0].text,
            prompt_tokens=len(out.prompt_token_ids),
            completion_tokens=len(out.outputs[0].token_ids),
        )


class HfBackend(BaseBackend):
    kind = "hf"

    def __init__(self, model_name: str, decode: DecodeConfig):
        super().__init__(model_name, decode)
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as e:
            raise RuntimeError(
                "transformers/torch not installed — use --backend dummy locally."
            ) from e
        self._tok = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=torch.bfloat16, device_map="auto"
        )

    def generate(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        ids = self._tok.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        ).to(self._model.device)
        out = self._model.generate(
            ids,
            max_new_tokens=self.decode.max_new_tokens,
            do_sample=self.decode.temperature > 0,
            temperature=max(self.decode.temperature, 1e-5),
        )
        new_tokens = out[0][ids.shape[1]:]
        return GenerationResult(
            text=self._tok.decode(new_tokens, skip_special_tokens=True),
            prompt_tokens=int(ids.shape[1]),
            completion_tokens=int(new_tokens.shape[0]),
        )


class ApiBackend(BaseBackend):
    """OpenAI-compatible chat-completions API (Together, DeepInfra, Groq, ...).

    For models too large for local GPUs (the 70B ESCALATE target on small-GPU
    setups). Energy is NOT measurable for remote calls — run_pilot records
    energy_j as null with method 'unmeasured_api'; the memo must say so.
    """

    kind = "api"

    def __init__(self, model_name: str, decode: DecodeConfig,
                 base_url: str, api_key_env: str, timeout: int = 180):
        super().__init__(model_name, decode)
        import os
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = os.environ.get(api_key_env)
        if not self._key:
            raise RuntimeError(
                f"environment variable {api_key_env} is not set — "
                f"export your API key before running (never put it in config.yaml)"
            )
        self._timeout = timeout

    def generate(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        import json as _json
        import urllib.error
        import urllib.request

        payload = _json.dumps({
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.decode.temperature,
            "max_tokens": self.decode.max_new_tokens,
        }).encode()
        req = urllib.request.Request(self._url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._key}",
            # some API edges (e.g. Cloudflare) 403 the default Python-urllib UA
            "User-Agent": "krishi-safe-pilot/0.1",
            "Accept": "application/json",
        })
        last_err: str | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = _json.loads(resp.read())
                usage = body.get("usage", {})
                return GenerationResult(
                    text=body["choices"][0]["message"]["content"],
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode(errors="replace")[:300]
                except Exception:
                    pass
                last_err = f"{e} — {detail}"
                time.sleep(2 ** attempt)  # 1, 2, 4, 8 s backoff
            except (urllib.error.URLError, KeyError) as e:
                last_err = str(e)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"API request failed after 4 attempts: {last_err}")


_BACKENDS = {"dummy": DummyBackend, "vllm": VllmBackend, "hf": HfBackend,
             "api": ApiBackend}


def get_backend(kind: str, model_name: str, decode: DecodeConfig,
                **backend_kwargs: Any) -> BaseBackend:
    if kind not in _BACKENDS:
        raise ValueError(f"unknown backend '{kind}' (choose from {sorted(_BACKENDS)})")
    if kind not in ("vllm", "api") and backend_kwargs:
        raise ValueError(f"backend kwargs {sorted(backend_kwargs)} only apply to vllm/api")
    return _BACKENDS[kind](model_name, decode, **backend_kwargs)

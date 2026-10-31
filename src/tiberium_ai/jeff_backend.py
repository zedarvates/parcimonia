"""Optional pinned Jeff Qwen SDK bridge, using already downloaded weights."""
from __future__ import annotations

from importlib.metadata import distribution, version
import json
import re

from .laya_backend import LayaBackend


class JeffBackend(LayaBackend):
    """Reuse typed-response validation, not Laya inference or language routing.

    English-trained Jeff is tested on French here as an unvalidated candidate.
    Neither script nor provider confidence establishes language competence.
    """

    backend_id = "jeff.sdk.qwen-0.8b@1"
    repo_id = "mstrasser/Jeff-Qwen3.5-0.8B"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = self.repo_id + "@" + self.revision
        self.runtime_revision: str | None = None

    @classmethod
    def load(cls, *, revision: str, runtime_revision: str, allow_load: bool = False,
             device: str = "cpu", max_calls: int = 100) -> "JeffBackend":
        for pin in (revision, runtime_revision):
            if not re.fullmatch(r"[0-9a-f]{40}", pin):
                raise ValueError("immutable checkpoint and runtime SHAs required")
        if not allow_load:
            raise ValueError("explicit load opt-in required")
        if device != "cpu":
            raise ValueError("this pilot supports CPU only")
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be positive")
        provenance = json.loads(distribution("jeff").read_text("direct_url.json") or "{}")
        if provenance.get("vcs_info", {}).get("commit_id") != runtime_revision:
            raise ValueError("installed Jeff SDK does not match pinned revision")
        from huggingface_hub import snapshot_download
        checkpoint = snapshot_download(cls.repo_id, revision=revision, local_files_only=True,
                                       allow_patterns=["config.json", "decision_config.json", "model.safetensors",
                                                       "readout.safetensors", "tokenizer.json", "tokenizer_config.json",
                                                       "processor_config.json", "chat_template.jinja"])
        from pathlib import Path
        if Path(checkpoint).name != revision:
            raise ValueError("checkpoint does not match pinned revision")
        import torch
        from jeff.models import load_decision_model
        from jeff.model import answer
        model = load_decision_model(checkpoint=checkpoint, device=device)
        model.eval()

        def predict(state, questions, *, max_len):
            answers = {}
            tokens = 0
            # One question per forward pass bounds temporary CPU buffers.
            # Keep the exact shared questions; do not alter the prompt schema.
            with torch.inference_mode():
                for name, question in questions.items():
                    batch = model.prepare([{"state": state, "question": question}], max_length=max_len)
                    values = (model(batch) / model.temperature).softmax(-1).cpu().tolist()[0]
                    answers[name] = answer(question, values[:batch.counts[0]])
                    tokens += batch.input_tokens
            return {"answers": answers, "usage": {"input_tokens": tokens, "output_tokens": 0,
                                                    "question_batch_size": 1}}

        backend = cls(revision=revision, predict=predict, runtime_version=version("jeff"), max_calls=max_calls)
        backend.device = model.device_name
        backend.runtime_revision = runtime_revision
        return backend

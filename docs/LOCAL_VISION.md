# Local vision through the existing worker

This opt-in extension adds image inputs to the existing LM Studio worker. It
reuses its bounded local HTTP transport and the existing context/RAG path. It
does not create another worker, wiki, index, scheduler or automatic fallback.

## Prepare one request

From this checkout, with a caller-selected PNG or JPEG and the exact model ID
observed in the local runtime:

```sh
PYTHONPATH=src python examples/local_vision_request.py \
  --task-id local-vision-001 --model LOCAL_MODEL_ID \
  --prompt 'Inspect this render against the cited requirements. Report uncertainty.' \
  --image render.png --max-tokens 512 > request-private.json
```

Preparation reads only the explicitly named regular files and makes no network
call. It writes JSON to stdout; the shell redirection creates the chosen file.
Check exit code 0 before continuing. The request contains the image bytes in
base64 and is private input, not a source-control artifact. A second `--image`
can supply another view or a reference. Symbolic links and special files are
refused. Observed file identity/size/mtime checks do not provide an atomic
snapshot or an OS sandbox against concurrent writers.

## Infer with the existing context connection

```sh
PYTHONPATH=src python examples/local_chat_worker.py \
  --context-file retrieved-context.txt < request-private.json > result-private.json
```

Or use the already configured vault engine explicitly:

```sh
PYTHONPATH=src python examples/local_chat_worker.py \
  --vault-dir /path/to/existing-vault \
  --rag-query 'Requirements and verified recipes for this task' \
  < request-private.json > result-private.json
```

These commands explicitly request inference. The default endpoint is loopback;
the existing `--base-url` and `--allow-lan` options remain caller-controlled.
There is at most one POST, no retry and no cloud fallback. A retrieval failure
blocks the POST. A timeout can leave server computation in an unknown state;
inspect the existing runtime/job state before considering another request.

The caller must close stdin and bound the whole subprocess duration. HTTP and
RAG deadlines cover their own phases, not all filesystem/OS operations. A local
runtime and locally available weights, vision components, corpus and index are
required for operation without cloud availability. No OpenAI credential is
used by these scripts.

## Versioned contract

| Input | Output | Meaning |
| --- | --- | --- |
| Request v1, text only | v1 | Existing text contract |
| Request v1 + context file | v2 | Existing context receipt |
| Request v1 + explicit vault retrieval | v3 | Existing retrieval receipt |
| Request v2, with or without context/retrieval | v4 | `request_schema_version: 2`, `images`, optional existing `context`/`retrieval` receipts |

Request v2 retains `task_id`, `model`, `messages`, optional `max_tokens` and
`temperature`. User content can be a list of text and image parts:

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "Inspect this authored example."},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,BASE64_BYTES"}}
  ]
}
```

The placeholder above is not a valid image; use the preparation command.
HTTP/file URLs, GIF/WebP/SVG, unknown keys, malformed base64 and unsupported
message roles are rejected before network access. Image inputs are allowed only
in user messages. Limits are two images, 2 MiB decoded bytes each, 4096 pixels
per axis, 4 million advertised pixels, 16 parts per message, 32 messages,
256 KiB cumulative UTF-8 text and 6 MiB encoded request. Context additions are
revalidated against the combined limits.

Each image receipt contains `message_index`, `part_index`, `mime_type`,
`sha256`, `size_bytes`, `width`, `height` and
`inspection: "container_headers_only"`. Indices refer to the transmitted
messages, including inserted context messages. The receipt omits raw images and
private file paths. Model text remains untrusted and could repeat supplied
material; the result file is private too.

PNG/JPEG header checks do not decode the compressed image, prove a complete
valid image, constrain the runtime decoder's memory or establish image quality.
`completed` means the endpoint returned finished text. It does not prove the
model used the images or the right citations. Truncation, unsupported native
tool calls and transport failures are not successful completions. Outputs are
proposals for the caller's existing validators, never executed instructions.

## Qualification candidates, not installed models

For the two reported 12 GiB GPUs, first qualify **Qwen3.5-9B in Q4** with a
moderate context (initial target 8K) and a small number of views. Test whether the
complete model, vision component and buffers fit on one available GPU. Keep
**Qwen3.8-27B in Q4** as the larger candidate split across both cards; alternate
inference and rendering when needed. These are proposed configurations, not
measured fits or throughput guarantees. Keep the existing small text-only
candidate available if the installed runtime cannot serve multimodal inputs.

Both Qwen families have native vision in their official model architecture.
The chosen GGUF package/runtime still needs its compatible vision component and
multimodal API enabled. In llama.cpp the separately packaged projector is loaded
with `--mmproj` or a supported package loader. Pin the exact weights, revision,
hashes, vision component and runtime version before comparing candidates.

Use the same caller-owned tasks for Qwen3.5-9B, Qwen3.8-27B and, if useful,
Gemma 4 12B as an alternative. Measure completed-task quality, refused/invalid
proposals, correction count, total time and peak memory. Do not use a vendor's
benchmark or a mock endpoint response as local model-quality evidence.

Primary references checked 2026-10-31:

- [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Gemma 4](https://ai.google.dev/gemma/docs/core/model_card_4)
- [llama.cpp multimodal input](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp multi-GPU](https://github.com/ggml-org/llama.cpp/blob/master/docs/multi-gpu.md)

## Current proof and next step

Tests use authored PNG/JPEG headers and local HTTP/RAG fixtures. They exercise
the actual worker subprocess, request preparation, combined image/context
transport, bounded refusal and absence of retries. No Qwen, LM Studio instance,
real vault, GPU, editor or game runtime has been exercised in this environment.

Next qualify the actual local runtime, then compare one reference and one
requested modification through the caller's existing artifact validator.
Inspect the result in the real renderer as a separate step. Keep the unmodified
artifact and exact request/result so an interrupted iteration can be reconciled.

Rollback: omit request v2 and use the unchanged v1 text/context/retrieval path.

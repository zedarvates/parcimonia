"""Advisory plugin entry point; never executes a proposed route."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vendor.compute_advisor import advise, TASKS
from _vendor.hardware import observe
from _vendor.mcp_runtime import Server, main, object_args
from _vendor.context_selection import ContextSelector
from _vendor.observation_review import review_observations

SELECTOR = ContextSelector()


def plan(args):
    object_args(args, ("request", "snapshot", "candidates"))
    return advise(args["request"], args["snapshot"], args["candidates"])


def hardware(args):
    object_args(args)
    return observe()


def context(args):
    object_args(args, ("query", "documents"), ("top_k", "max_selected_bytes"))
    return SELECTOR.select(args["query"], args["documents"], top_k=args.get("top_k", 5),
                          max_selected_bytes=args.get("max_selected_bytes", 524288))


def observations(args):
    object_args(args, ("request",))
    return review_observations(args["request"])


NUMBER = {"type": "number", "minimum": 0}
BYTES = {"type": "integer", "minimum": 0}
NULL_NUMBER = {"type": ["number", "null"], "minimum": 0}
NULL_BYTES = {"type": ["integer", "null"], "minimum": 0}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 128}


def obj(properties, optional=()):
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "required": [name for name in properties if name not in optional]}


MEASUREMENT = obj({
    "workload_sha256": SHA, "hardware_key": SHA, "recorded_at": NUMBER,
    "samples": BYTES, "passed": BYTES, "verifier_revision": TEXT,
    "p50_ms": NUMBER, "p95_ms": NUMBER, "cold_start_ms": NUMBER,
    "warm_start_ms": NUMBER, "cloud_cost_usd": NULL_NUMBER})
CANDIDATE = obj({
    "id": TEXT, "task": {"enum": list(TASKS)}, "device": {"enum": ["cpu", "gpu", "npu", "cloud"]},
    "availability": {"enum": ["ready", "unknown", "unavailable"]},
    "warm": {"type": "boolean"}, "heavy": {"type": "boolean"},
    "ram_bytes": BYTES, "commit_bytes": BYTES, "disk_bytes": BYTES, "vram_bytes": BYTES,
    "measurement": {"anyOf": [MEASUREMENT, {"type": "null"}]}})
ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False,
               "idempotentHint": True, "openWorldHint": False}
REQUIREMENT = obj({
    "id": TEXT, "source_id": TEXT, "source_revision": TEXT, "input_sha256": SHA,
    "verifier_id": TEXT, "verifier_version": TEXT, "max_age_seconds": NUMBER})
OBSERVATION = obj({
    "id": TEXT, "requirement_id": TEXT, "task_id": TEXT, "task_revision": TEXT,
    "source_id": TEXT, "source_revision": TEXT, "input_sha256": SHA,
    "verifier_id": TEXT, "verifier_version": TEXT, "observed_at": NUMBER,
    "outcome": {"enum": ["pass", "fail", "unknown"]}})
OBSERVATION_REQUEST = obj({
    "task_id": TEXT, "task_revision": TEXT,
    "requirements": {"type": "array", "minItems": 1, "maxItems": 64, "items": REQUIREMENT},
    "observations": {"type": "array", "maxItems": 128, "items": OBSERVATION},
    "probes": {"type": "array", "maxItems": 32, "items": obj({
        "id": TEXT, "requirement_ids": {"type": "array", "minItems": 1,
            "maxItems": 64, "uniqueItems": True, "items": TEXT},
        "estimated_latency_ms": NULL_NUMBER})}})
TOOLS = [
    {"name": "parcimonia_local_plan", "title": "Proposer une route de calcul",
     "description": "Comparer au plus 32 routes avec ressources fraîches et mesures liées au matériel et à la charge. Inclut démarrage, qualité et réserves. Rapports fournis non attestés ; proposition seulement, aucune exécution.",
     "inputSchema": obj({
         "request": obj({"task": {"enum": list(TASKS)}, "workload_sha256": SHA,
                         "objective": {"enum": ["latency", "cloud_spend"]},
                         "max_latency_ms": NULL_NUMBER}, ("objective", "max_latency_ms")),
         "snapshot": obj({"observed_at": NUMBER, "hardware_key": SHA,
                          "ram_available_bytes": NULL_BYTES, "commit_available_bytes": NULL_BYTES,
                          "disk_free_bytes": NULL_BYTES,
                          "gpu_free_bytes": {"type": "array", "maxItems": 32, "items": BYTES},
                          "heavy_busy": {"type": ["boolean", "null"]}}),
         "candidates": {"type": "array", "maxItems": 32, "items": CANDIDATE}}),
     "annotations": ANNOTATIONS},
    {"name": "parcimonia_local_hardware", "title": "Observer le matériel local",
     "description": "Lire les ressources disponibles sur l'hôte du plugin. Les capacités inconnues restent nulles. Aucun service lancé, aucune inférence ni autorisation de tâche lourde.",
     "inputSchema": obj({}), "annotations": ANNOTATIONS},
    {"name": "parcimonia_local_context", "title": "Proposer des fichiers utiles",
     "description": "Classer des documents fournis selon termes rares, chemins et symboles. Hashes vérifiés, budget et omissions explicites ; score lexical sans probabilité. Aucun accès au disque, modèle ou exécution. Pour éviter d'envoyer tous les textes, utiliser Botte local_sources sur l'hôte.",
     "inputSchema": obj({"query": {"type": "string", "minLength": 1, "maxLength": 16000},
                         "documents": {"type": "array", "maxItems": 128, "items": obj({
                             "id": {"type": "string", "minLength": 1, "maxLength": 768},
                             "path": {"type": "string", "minLength": 1, "maxLength": 512},
                             "text": {"type": "string", "maxLength": 262144}, "content_sha256": SHA})},
                         "top_k": {"type": "integer", "minimum": 1, "maximum": 16},
                         "max_selected_bytes": {"type": "integer", "minimum": 1, "maximum": 16777216}},
                        ("top_k", "max_selected_bytes")), "annotations": ANNOTATIONS},
    {"name": "parcimonia_local_observations", "title": "Contrôler les observations d'une tâche",
     "description": "Comparer des observations fournies aux exigences exactes d'une tâche : dates, versions, empreintes et identité du vérificateur. Signaler manques, péremptions, contradictions et échecs récents ; proposer une observation suivante par couverture et latence déclarée. Rapports hôte non attestés, aucune action autorisée ou exécutée.",
     "inputSchema": obj({"request": OBSERVATION_REQUEST}),
     "annotations": {**ANNOTATIONS, "idempotentHint": False}},
]

if __name__ == "__main__":
    raise SystemExit(main(Server("parcimonia-local", TOOLS, {
        "parcimonia_local_plan": plan, "parcimonia_local_hardware": hardware,
        "parcimonia_local_context": context,
        "parcimonia_local_observations": observations}, version="0.4.3")))

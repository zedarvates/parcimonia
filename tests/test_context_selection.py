import hashlib
import pytest

from tiberium_ai.context_selection import ContextSelector, select_context, terms


def doc(name, text):
    return {"id": name, "path": name, "text": text,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def test_identifier_and_unicode_terms():
    assert terms("HostAttestation call_attestation été") == ["host", "attestation", "call", "attestation", "ete"]


def test_closed_french_aliases_preserve_negations():
    assert terms("les fichiers du modèle et du contexte") == ["file", "model", "et", "context"]
    assert terms("sans cloud pas de réseau") == ["sans", "cloud", "pas", "reseau"]
    result = select_context("profil vérifié de l'hôte", [doc("p.py", "def verified_host_profile():\n    return True\n")])
    assert result["files"][0]["id"] == "p.py"


def test_exact_hash_and_path_checks():
    for path in ("../a.py", "x/../a.py", "C:/a.py", "x\\a.py", "/a.py", "./a.py"):
        with pytest.raises(ValueError):
            select_context("hello", [doc(path, "hello")])
    row = doc("a.py", "hello")
    row["text"] = "changed"
    with pytest.raises(ValueError):
        select_context("hello", [row])


def test_rare_term_and_symbol_rank_relevant_source():
    rows = [doc("general.py", "context common " * 80),
            doc("binding.py", "def verify_attestation():\n    return 'host attestation context'\n"),
            doc("unrelated.py", "price table invoice")]
    result = select_context("host attestation", rows)
    assert result["files"][0]["id"] == "binding.py"
    assert "verify_attestation" in result["files"][0]["matched_symbols"]
    assert result["auto_act_allowed"] is False
    assert "text" not in result["files"][0]


def test_no_overlap_abstains_and_order_is_deterministic():
    rows = [doc("b.py", "same unique"), doc("a.py", "same unique")]
    assert select_context("zzzzzz", rows)["status"] == "abstain"
    assert [r["id"] for r in select_context("unique", rows)["files"]] == ["a.py", "b.py"]


def test_budget_omissions_and_small_file_after_large():
    rows = [doc("large.py", "special " * 100), doc("small.py", "special")]
    result = select_context("special", rows, max_selected_bytes=20)
    assert [r["id"] for r in result["files"]] == ["small.py"]
    assert result["omitted"] == [{"id": "large.py", "reason": "source_byte_budget"}]
    result = select_context("special", rows, top_k=1)
    assert len(result["files"]) == len(result["omitted"]) == 1


def test_invalid_syntax_is_searchable_without_execution():
    result = select_context("deliberate", [doc("a.py", "def ( # deliberate")])
    assert result["files"][0]["matched_symbols"] == []


@pytest.mark.parametrize("limit", [0, True, 17, -1])
def test_count_budget(limit):
    with pytest.raises(ValueError):
        select_context("x", [], top_k=limit)


def test_duplicate_ids_and_multibyte_budget():
    with pytest.raises(ValueError):
        select_context("test", [doc("a.py", "test"), doc("a.py", "test")])
    with pytest.raises(ValueError):
        select_context("test", [doc("a.py", "é" * 131073)])


def test_explicit_long_relative_reference_is_not_an_id_collision():
    path = "nested/" * 40 + "module.py"
    row = doc(path, "meaningful")
    row["id"] = "project:" + path
    assert select_context("meaningful", [row])["files"][0]["id"] == row["id"]


def test_cached_derivations_are_fresh_by_hash_and_path():
    selector = ContextSelector()
    first = [doc("source.py", "def old_symbol():\n    return 'alpha'\n")]
    assert selector.select("alpha", first)["metrics"]["derived_cache_misses"] == 1
    repeated = selector.select("alpha", first)
    assert repeated["metrics"]["derived_cache_hits"] == 1
    changed = [doc("source.py", "def new_symbol():\n    return 'beta'\n")]
    assert selector.select("alpha", changed)["status"] == "abstain"
    result = selector.select("beta", changed)
    assert result["files"][0]["matched_symbols"] == []
    changed[0]["path"] = "renamed.py"
    assert selector.select("beta", changed)["metrics"]["derived_cache_misses"] == 1


def test_cache_budget_does_not_retain_queries_or_text():
    selector = ContextSelector(max_cache_bytes=1024, max_entries=1)
    row = doc("source.py", "cache alpha")
    result = selector.select("alpha", [row])
    assert result["metrics"]["derived_cache_entries"] == 1
    assert result["metrics"]["derived_cache_payload_bytes"] <= 1024
    selector.select("beta", [doc("other.py", "cache beta")])
    assert selector.select("alpha", [row])["metrics"]["derived_cache_misses"] == 1
    disabled = ContextSelector(max_cache_bytes=0)
    disabled.select("alpha", [row])
    assert disabled.select("alpha", [row])["metrics"]["derived_cache_hits"] == 0

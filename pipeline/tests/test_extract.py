from __future__ import annotations

from nightshift.config import DEFAULTS
from nightshift.extract import normalize_extraction, parse_llm_json, regex_extract
from nightshift.models import Item
from nightshift.sources import LocalSource, StateStore


def load_examples(examples_dir):
    src = LocalSource({"drop_folder": str(examples_dir)}, StateStore(None))
    return {it.title: it for it in src.fetch()}


def test_regex_extract_prompting_fixture(examples_dir):
    items = load_examples(examples_dir)
    it = items["Five Prompting Techniques That Actually Work in 2026"]
    ext = regex_extract(it)
    names = {t["name"] for t in ext["tools"]}
    assert {"ChatGPT", "Claude", "Cursor", "Obsidian", "Notion"} <= names
    assert len(ext["prompts"]) >= 3
    assert any("skeptical engineer" in p["prompt"] for p in ext["prompts"])
    tech = {t["name"] for t in ext["techniques"]}
    assert "Role Stacking" in tech
    assert {"Checklist Sandwich", "Self-Review Pass"} <= tech
    assert len(ext["ideas"]) == 1
    assert ext["ideas"][0]["title"].startswith("Small prompt library tool")
    assert "$30" in ext["ideas"][0]["potential"]
    assert ext["summary"]


def test_regex_extract_vtt_fixture(examples_dir):
    it = load_examples(examples_dir)["rag-in-ten-minutes"]
    assert "-->" not in it.transcript and "WEBVTT" not in it.transcript
    ext = regex_extract(it)
    names = {t["name"] for t in ext["tools"]}
    assert {"Supabase", "Pinecone", "LangChain", "Cursor"} <= names
    assert any("Answer the question using only the context" in p["prompt"] for p in ext["prompts"])
    assert ext["ideas"] and "RAG starter kit" in ext["ideas"][0]["title"]


def test_regex_extract_urls_and_repos(examples_dir):
    it = load_examples(examples_dir)["Building a Local-First Meeting Notes Pipeline"]
    ext = regex_extract(it)
    assert {"Whisper", "Ollama", "Obsidian", "n8n", "Llama"} <= {t["name"] for t in ext["tools"]}
    assert ext["ideas"][0]["title"].startswith("Privacy-first meeting notes appliance")


def test_word_boundaries_avoid_false_positives():
    it = Item(id="x", source="t", transcript="Move the cursor, make a claudette remark, and notionally aim.")
    assert regex_extract(it)["tools"] == []


def test_extra_tools_from_config():
    it = Item(id="x", source="t", transcript="We used FooBarTool to ship faster.")
    ext = regex_extract(it, {"FooBar": {"variants": ["foobartool"], "category": "coding"}})
    assert ext["tools"][0]["name"] == "FooBar"


def test_empty_transcript():
    ext = regex_extract(Item(id="x", source="t"))
    assert ext == normalize_extraction({})


def test_parse_llm_json_variants():
    assert parse_llm_json('```json\n{"summary": "x"}\n```') == {"summary": "x"}
    assert parse_llm_json('Sure! Here it is: {"tools": []} hope that helps') == {"tools": []}
    assert parse_llm_json("not json at all") is None
    assert parse_llm_json("") is None
    assert parse_llm_json("[1, 2]") is None


def test_normalize_extraction_is_defensive():
    out = normalize_extraction({
        "summary": 12,
        "tools": [{"name": "X", "url": "javascript:alert(1)"}, "junk", {"name": ""}],
        "ideas": [{"idea": "You could build a tool for teachers that grades essays."}],
        "prompts": "not a list",
    })
    assert out["summary"] == "12"
    assert out["tools"] == [{"name": "X", "category": "other", "description": "", "url": None}]
    assert out["prompts"] == []
    assert out["ideas"][0]["title"]


def test_default_model_id():
    assert DEFAULTS["llm"]["api_model"] == "claude-sonnet-5"

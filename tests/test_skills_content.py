from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"


def _read(name):
    return (SKILLS_DIR / name / "SKILL.md").read_text()


def test_all_four_skill_files_exist_with_frontmatter():
    for name in ("inventory", "billing", "khata", "preferences"):
        content = _read(name)
        assert content.startswith("---"), f"{name} SKILL.md missing YAML frontmatter"
        assert "description:" in content.splitlines()[2], f"{name} SKILL.md missing a description line"


def test_billing_skill_mentions_gst_and_oversell():
    content = _read("billing").lower()
    assert "gst" in content
    assert "oversell" in content or "stock" in content


def test_khata_skill_mentions_settle_guardrail():
    content = _read("khata").lower()
    assert "khata" in content
    assert "doesn't exist" in content or "does not exist" in content or "unknown" in content


def test_preferences_skill_mentions_silent_application():
    content = _read("preferences").lower()
    assert "silent" in content or "don't re-ask" in content or "without asking" in content


def test_invoicing_and_analytics_skill_files_exist_with_frontmatter():
    for name in ("invoicing", "analytics"):
        content = _read(name)
        assert content.startswith("---"), f"{name} SKILL.md missing YAML frontmatter"
        assert "description:" in content.splitlines()[2]


def test_invoicing_skill_mentions_pdf_and_bill_id():
    content = _read("invoicing").lower()
    assert "pdf" in content
    assert "bill" in content


def test_analytics_skill_mentions_deck_and_charts():
    content = _read("analytics").lower()
    assert "pptx" in content or "deck" in content
    assert "chart" in content

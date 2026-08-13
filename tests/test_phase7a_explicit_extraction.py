from src.memory.explicit_facts import extract_explicit_facts_from_user_text
from src.memory.semantic import persist_explicit_facts_from_user_text
from src.db import init_db
from src.memory.semantic_store import SemanticFactStore


def _texts(user_text):
    return [fact.fact_text for fact in extract_explicit_facts_from_user_text(user_text)]


def test_explicit_extraction_patterns():
    facts = _texts(
        "Please remember I deploy on Fridays. Do not forget my VPN needs approval. "
        "My name is Alex and my email is alex@example.com"
    )

    assert any("I deploy on Fridays" in fact for fact in facts)
    assert any("my VPN needs approval" in fact for fact in facts)
    assert any("User's name is Alex" == fact for fact in facts)
    assert any("User's email is alex@example.com" == fact for fact in facts)


def test_remember_that_and_dont_forget_patterns():
    facts = _texts("Remember that code reviews happen before deploy. Don't forget that staging is shared.")

    assert any("code reviews happen before deploy" in fact for fact in facts)
    assert any("staging is shared" in fact for fact in facts)


def test_vague_preference_is_not_immediate_explicit_fact():
    assert extract_explicit_facts_from_user_text("I like dark mode and I prefer brief answers") == []


def test_user_attributes_are_explicit_facts():
    facts = _texts("My timezone is IST and my office is Bangalore")
    assert any(fact.lower() == "user's timezone is ist" for fact in facts)
    assert any(fact.lower() == "user's office is bangalore" for fact in facts)


def test_stated_entity_attributes_are_explicit_facts():
    facts = _texts("Prannay's email is prannay@kamal.dev. Priya's timezone is IST.")
    assert any(fact.lower() == "prannay's email is prannay@kamal.dev" for fact in facts)
    assert any(fact.lower() == "priya's timezone is ist" for fact in facts)

    facts = _texts("The office of Prannay is Bangalore")
    assert any(fact.lower() == "prannay's office is bangalore" for fact in facts)


def test_entity_relationship_is_an_explicit_fact():
    facts = _texts("Prannay is my cofounder")
    assert any(fact.lower() == "prannay is the user's cofounder" for fact in facts)


def test_action_requests_are_not_treated_as_facts():
    assert extract_explicit_facts_from_user_text("send mail to khushambansal@gmail.com saying hi") == []
    assert extract_explicit_facts_from_user_text("email alice about the invoice") == []
    assert extract_explicit_facts_from_user_text("send this to the office wifi") == []


def test_remember_that_is_an_explicit_fact_without_special_domains():
    facts = _texts("Remember that the office wifi password is rotated monthly")
    assert any("office wifi password is rotated monthly" in fact.lower() for fact in facts)


def test_persist_explicit_facts_writes_permanent_store(tmp_path, monkeypatch):
    db_file = tmp_path / "facts.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)

    written = persist_explicit_facts_from_user_text(
        "Priya's timezone is IST. Remember that staging VPN needs approval.",
        db_path=db_file,
        memory_path=mem_file,
    )
    assert written >= 2
    facts = SemanticFactStore(db_path=db_file).list_facts()
    texts = [fact.fact_text for fact in facts]
    assert any("IST" in text for text in texts)
    assert any("staging VPN needs approval" in text for text in texts)
    memory = mem_file.read_text(encoding="utf-8")
    assert "IST" in memory
    assert "staging VPN" in memory

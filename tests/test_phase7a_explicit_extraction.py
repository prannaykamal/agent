from src.memory.semantic_candidates import extract_explicit_facts_from_user_text


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

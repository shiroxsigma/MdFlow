from mdflow import edit_safety, llm_context

DOC = """# Login
Login overview.

```mermaid
%% id: login
flowchart TD
 A-->B
```

```mdflow-mapping
diagram: login
presets: {}
```

# Payment
Credit card settlement and refunds.
"""


def test_retrieve_prefers_relevant_heading():
    result = llm_context.retrieve(DOC, "refund payment", limit=1)
    assert result[0].title == "Payment"


def test_text_policy_preserves_diagram_and_mapping():
    candidate = DOC.replace("A-->B", "A-->X").replace("Login overview.", "Short.")
    repaired, warnings = edit_safety.repair(DOC, candidate, "text")
    assert "Short." in repaired
    assert "A-->B" in repaired
    assert "diagram: login" in repaired
    assert warnings == []


def test_diagram_policy_preserves_prose_and_restores_id():
    candidate = """Changed prose
```mermaid
flowchart TD
 A-->C
```
"""
    repaired, warnings = edit_safety.repair(DOC, candidate, "diagram")
    assert "Login overview." in repaired
    assert "A-->C" in repaired
    assert "%% id: login" in repaired
    assert "diagram: login" in repaired
    assert warnings


def test_missing_mapping_is_restored():
    repaired, warnings = edit_safety.repair(DOC, DOC.split("```mdflow-mapping")[0], "all")
    assert "diagram: login" in repaired
    assert any("mapping" in warning for warning in warnings)

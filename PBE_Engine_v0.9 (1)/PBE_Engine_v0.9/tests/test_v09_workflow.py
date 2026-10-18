from pathlib import Path
from pbe.services.saas_planner import SaaSPlan


def test_plan_has_workflow_estimate_and_steps():
    plan = SaaSPlan(
        title="Test",
        objective_summary="Test objective",
        savings_logic="Measure actual total cost.",
        estimated_duration_minutes=25,
        workflow_steps=[{"title": "Review", "description": "Review outputs", "estimated_minutes": 5, "status": "PENDING"}],
    )
    assert plan.estimated_duration_minutes == 25
    assert plan.workflow_steps[0]["title"] == "Review"


def test_workflow_estimate_is_bounded():
    try:
        SaaSPlan(title="Test", objective_summary="Test", savings_logic="No claims", estimated_duration_minutes=0)
    except Exception:
        pass
    else:
        raise AssertionError("Expected duration lower bound validation")


def test_ui_version_is_not_investor_branded():
    html = (Path(__file__).parents[1] / "pbe" / "static" / "index.html").read_text(encoding="utf-8")
    assert '<div class="badge">v0.9</div>' in html
    assert "INVESTOR PREVIEW" not in html.upper()
    assert "SIMULATED WORKFLOW" not in html.upper()


def test_workflow_timeline_schema_is_additive():
    db_source = (Path(__file__).parents[1] / "pbe" / "db.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS workflow_timeline_events" in db_source
    assert "DROP TABLE" not in db_source.upper()

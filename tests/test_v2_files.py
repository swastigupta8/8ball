"""The V2 viewer features are plain files in web/: check the pages and scripts agree on element ids and on links."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def _ids_used(js: str) -> set[str]:
    return set(re.findall(r'\$\("([\w-]+)"\)', js))


def _ids_defined(page: str) -> set[str]:
    return set(re.findall(r'\bid="([\w-]+)"', page))


def test_every_id_app_js_reads_exists_in_the_viewer_page():
    used = _ids_used((WEB / "app.js").read_text(encoding="utf-8"))
    missing = sorted(used - _ids_defined((WEB / "viewer.html").read_text(encoding="utf-8")))
    assert used and not missing, f"app.js uses ids that viewer.html lacks: {missing}"


def test_every_id_challenge_js_reads_exists_in_the_challenge_page():
    used = _ids_used((WEB / "challenge.js").read_text(encoding="utf-8"))
    missing = sorted(used - _ids_defined((WEB / "challenge.html").read_text(encoding="utf-8")))
    assert used and not missing, f"challenge.js uses ids that challenge.html lacks: {missing}"


def test_every_id_how_it_works_js_reads_exists_in_its_page():
    used = _ids_used((WEB / "how-it-works.js").read_text(encoding="utf-8"))
    missing = sorted(used - _ids_defined((WEB / "how-it-works.html").read_text(encoding="utf-8")))
    assert used and not missing, f"how-it-works.js uses ids that how-it-works.html lacks: {missing}"


def test_how_it_works_survives_a_bad_data_file():
    """One unreadable data file must not blank the page: the loader awaits the parse and each section has its own guard."""
    js = (WEB / "how-it-works.js").read_text(encoding="utf-8")
    assert "await r.text()" in js and "Infinity" in js          # tolerant parse of files with Infinity or NaN
    assert js.count("sectionFailed(") >= 3                       # defined once, used for results and for scaling


def test_how_it_works_explains_the_scenario_without_other_help():
    page = (WEB / "how-it-works.html").read_text(encoding="utf-8")
    for needle in ("The problem in plain words", "Four words to know", "The rules", "How answers are ranked",
                   "What goes into the cost", "How 8ball finds the answer", "Assumptions we made", "Results on the test set",
                   "Scaling up"):
        assert needle in page, needle
    assert page.count('class="stage"') >= 10                      # the pipeline has ten steps


def test_how_it_works_pipeline_cards_fold_and_the_page_has_no_disclaimer():
    page = (WEB / "how-it-works.html").read_text(encoding="utf-8")
    assert page.count('class="more"') == page.count('class="stage"') >= 10   # every card hides its details until clicked
    assert 'id="expand-all"' in page
    assert "Research exercise" not in page
    js = (WEB / "how-it-works.js").read_text(encoding="utf-8")
    assert "setupStages()" in js and "aria-expanded" in js


def test_how_it_works_results_keep_only_cost_and_speed_and_the_setup_moves_to_the_assumptions():
    page = (WEB / "how-it-works.html").read_text(encoding="utf-8")
    assumptions = page[page.index('id="assumptions"'):page.index("Results on the test set")]
    assert 'id="setup-tiles"' in assumptions and 'id="fail-table"' in assumptions
    js = (WEB / "how-it-works.js").read_text(encoding="utf-8")
    for removed in ("Solver vs checker", "Fewest possible hubs"):
        assert removed not in js and removed not in page
    for kept in ("Cheaper cabling", "Fast answers"):
        assert kept in js


def test_the_v2_controls_are_in_the_viewer_page():
    page = (WEB / "viewer.html").read_text(encoding="utf-8")
    for element in ("fault-cut", "fault-short", "iso-minus", "iso-plus", "iso-on", "tradeoff-section", "move-section",
                    "move-snap", "move-reset", "drag-label"):
        assert f'id="{element}"' in page, element
    # trade-off sits directly under the score card, as specified
    assert page.index('id="score-section"') < page.index('id="tradeoff-section"') < page.index('id="heat-section"')


def test_every_page_links_to_the_challenge():
    for name in ("index.html", "viewer.html", "gallery.html", "how-it-works.html", "challenge.html"):
        assert 'href="challenge.html"' in (WEB / name).read_text(encoding="utf-8"), name


def test_the_challenge_page_loads_its_script_and_uses_the_validate_endpoint():
    page = (WEB / "challenge.html").read_text(encoding="utf-8")
    assert 'src="challenge.js' in page and 'href="style.css' in page
    js = (WEB / "challenge.js").read_text(encoding="utf-8")
    assert "api/validate" in js and "8ball-answer/1" in js


def test_the_default_answer_endpoint_keeps_its_old_keys_and_only_adds_isolators():
    src = (WEB.parent / "src" / "eightball" / "api" / "server.py").read_text(encoding="utf-8")
    block = src[src.index('"plan": plan_json(plan, nodes),'):src.index('"saved_to"')]
    for key in ("plan", "answer", "check", "heatmaps", "branching", "runtime_s"):
        assert f'"{key}"' in block
    assert '"isolators"' in block

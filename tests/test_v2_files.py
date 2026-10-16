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

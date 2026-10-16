"""The 3D view is plain files in web/ (no build step): check they are all there and wired together."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_three_is_bundled_and_imports_resolve_offline():
    assert (WEB / "vendor" / "three.module.min.js").stat().st_size > 100_000
    assert (WEB / "vendor" / "LICENSE-three.txt").exists()
    controls = (WEB / "vendor" / "OrbitControls.js").read_text(encoding="utf-8")
    assert "from 'three'" not in controls and 'from "three"' not in controls  # no import map: relative import only
    assert "./three.module.min.js" in controls


def test_view3d_only_uses_elements_that_exist_in_the_viewer_page():
    js = (WEB / "view3d.js").read_text(encoding="utf-8")
    page = (WEB / "viewer.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\$\("([\w-]+)"\)', js)) | set(re.findall(r'\["(v3-[\w-]+)"', js))
    ids -= {"map-loop-title"}  # created by the existing 2D viewer markup, checked below
    assert ids, "no ids found: the pattern is out of date"
    missing = sorted(i for i in ids | {"map-loop-title"} if f'id="{i}"' not in page)
    assert not missing, f"view3d.js uses ids that viewer.html lacks: {missing}"


def test_page_loads_the_module_after_the_viewer_and_app_exposes_its_hooks():
    page = (WEB / "viewer.html").read_text(encoding="utf-8")
    assert page.index("app.js") < page.index('type="module" src="view3d.js')
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "window.eightballViewer" in app and "window.view3d?.refresh()" in app
    js = (WEB / "view3d.js").read_text(encoding="utf-8")
    for hook in ("nearestRingSeg", "loopEffects", "zoneColors", "nodePoints", "toggleCutAt", "heatRange", "rampRGB", "RAMP"):
        assert f"V.{hook}" in js and hook in app.split("window.eightballViewer =")[1]

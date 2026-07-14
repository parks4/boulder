"""Network-gated check that the Cantera doc links shown in the GUI resolve.

Covers boulder.cantera_docs (reactor/connection kind tooltips, Add
Reactor/Connection modals) and the solver-kind doc URLs from
frontend/src/components/panels/solverShared.ts (Solver Details modal) —
duplicated here as literals since this test has no visibility into that TS
module. Each test fetches its anchor's page once (cached) and skips itself
when cantera.org is unreachable (e.g. an offline CI runner), rather than
failing the whole run.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from functools import lru_cache
from typing import Dict

import pytest

from boulder.cantera_docs import all_doc_urls

_ZERODIM = "https://cantera.org/stable/python/zerodim.html"

# Kept in sync by hand with frontend/src/components/panels/solverShared.ts
# KIND_DOC_URLS.
SOLVER_KIND_DOC_URLS: Dict[str, str] = {
    "solver.advance_to_steady_state": f"{_ZERODIM}#cantera.ReactorNet.advance_to_steady_state",
    "solver.solve_steady": f"{_ZERODIM}#cantera.ReactorNet.solve_steady",
    "solver.advance": f"{_ZERODIM}#cantera.ReactorNet.advance",
    "solver.advance_grid": f"{_ZERODIM}#cantera.ReactorNet.advance",
    "solver.micro_step": f"{_ZERODIM}#cantera.ReactorNet.advance",
}


def _all_kind_urls() -> Dict[str, str]:
    urls = dict(all_doc_urls())
    urls.update(SOLVER_KIND_DOC_URLS)
    return urls


@lru_cache(maxsize=None)
def _fetch_page(base_url: str) -> str:
    with urllib.request.urlopen(base_url, timeout=10) as resp:  # noqa: S310 - fixed https URL
        return resp.read().decode("utf-8", errors="replace")


@pytest.mark.parametrize("kind,url", sorted(_all_kind_urls().items()))
def test_doc_link_anchor_exists(kind: str, url: str) -> None:
    """Each kind's doc URL has a #anchor whose id actually exists on the page."""
    base_url, _, anchor = url.partition("#")
    assert anchor, f"{kind}: doc URL {url} has no #anchor"

    try:
        body = _fetch_page(base_url)
    except urllib.error.HTTPError as exc:
        pytest.fail(f"{kind}: {base_url} returned HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError) as exc:
        pytest.skip(f"{kind}: cantera.org unreachable — offline environment ({exc})")

    assert f'id="{anchor}"' in body, (
        f"{kind}: anchor '#{anchor}' not found on {base_url}"
    )

#!/usr/bin/env python3
"""Discover reachable Angular routes for one app.

Phase A: parse *-routing.module.ts under apps/<app>/, flatten path tree.
Phase B: Playwright visits each candidate route, splits into reachable / excluded.

Stdout: strict JSON. Stderr: progress.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


PATH_RE = re.compile(r"""path\s*:\s*['"]([^'"]*)['"]""")
CHILDREN_RE = re.compile(r"""children\s*:\s*\[""")
ROUTES_BLOCK_RE = re.compile(r"""(?:const\s+routes\s*:\s*Routes\s*=\s*|Routes\s*=\s*)\[""", re.MULTILINE)


def find_matching_bracket(text: str, open_idx: int) -> int:
    """Given text and index of '[', return index of matching ']'. -1 if unbalanced."""
    depth = 0
    i = open_idx
    in_str: str | None = None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_str = c
            i += 1
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def parse_route_array(text: str, start_idx: int) -> list[dict[str, Any]]:
    """Parse the array starting at text[start_idx]='['. Returns list of route dicts."""
    end = find_matching_bracket(text, start_idx)
    if end < 0:
        return []
    body = text[start_idx + 1 : end]
    routes: list[dict[str, Any]] = []
    depth = 0
    obj_start = -1
    in_str: str | None = None
    i = 0
    while i < len(body):
        c = body[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_str = c
            i += 1
            continue
        if c == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                obj_text = body[obj_start : i + 1]
                routes.append(parse_route_object(obj_text))
                obj_start = -1
        i += 1
    return routes


def top_level_fields(obj_text: str) -> dict[str, tuple[int, int]]:
    """Return {fieldName: (valueStart, valueEnd)} for top-level key:value pairs inside { ... }.

    Skips contents inside nested {}, [], '', "", `` so regex doesn't leak from children.
    """
    if not obj_text.startswith("{") or not obj_text.endswith("}"):
        return {}
    body = obj_text[1:-1]
    fields: dict[str, tuple[int, int]] = {}
    i = 0
    in_str: str | None = None
    depth_brace = 0
    depth_brack = 0
    n = len(body)
    while i < n:
        c = body[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_str = c
            i += 1
            continue
        if c == "{":
            depth_brace += 1
            i += 1
            continue
        if c == "}":
            depth_brace -= 1
            i += 1
            continue
        if c == "[":
            depth_brack += 1
            i += 1
            continue
        if c == "]":
            depth_brack -= 1
            i += 1
            continue
        if depth_brace == 0 and depth_brack == 0 and c.isalpha():
            m = re.match(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*:", body[i:])
            if m:
                key = m.group(1)
                val_start = i + m.end()
                j = val_start
                while j < n:
                    ch = body[j]
                    if in_str:
                        if ch == "\\":
                            j += 2
                            continue
                        if ch == in_str:
                            in_str = None
                        j += 1
                        continue
                    if ch in ("'", '"', "`"):
                        in_str = ch
                        j += 1
                        continue
                    if ch == "{":
                        depth_brace += 1
                    elif ch == "}":
                        depth_brace -= 1
                    elif ch == "[":
                        depth_brack += 1
                    elif ch == "]":
                        depth_brack -= 1
                    elif ch == "," and depth_brace == 0 and depth_brack == 0:
                        break
                    j += 1
                fields[key] = (val_start, j)
                i = j
                continue
        i += 1
    return fields


def parse_route_object(obj_text: str) -> dict[str, Any]:
    """Parse a single { ... } route literal — only top-level fields."""
    out: dict[str, Any] = {"path": None, "children": [], "redirectTo": None, "loadChildren": None}
    if not obj_text.startswith("{"):
        return out
    body = obj_text[1:-1]
    fields = top_level_fields(obj_text)

    def get_str(name: str) -> str | None:
        if name not in fields:
            return None
        s, e = fields[name]
        seg = body[s:e].strip()
        m = re.match(r"""['"]([^'"]*)['"]""", seg)
        return m.group(1) if m else None

    out["path"] = get_str("path")
    out["redirectTo"] = get_str("redirectTo")
    out["loadChildren"] = get_str("loadChildren")

    if "children" in fields:
        s, e = fields["children"]
        seg = body[s:e]
        bidx = seg.find("[")
        if bidx >= 0:
            out["children"] = parse_route_array(seg, bidx)
    return out


def parse_routing_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    m = ROUTES_BLOCK_RE.search(text)
    if not m:
        return []
    bracket_idx = text.find("[", m.end() - 1)
    if bracket_idx < 0:
        return []
    return parse_route_array(text, bracket_idx)


def resolve_load_children(load: str, current_file: Path, app_root: Path) -> Path | None:
    """Resolve loadChildren string like './embeds/ltg/ltg.module#LtgModule' or 'foo' lazy."""
    if "#" in load:
        mod_path = load.split("#")[0]
    else:
        mod_path = load
    if mod_path.startswith("./") or mod_path.startswith("../"):
        target_dir = (current_file.parent / Path(mod_path).parent).resolve()
        name = Path(mod_path).name.replace(".module", "")
        cand = target_dir / f"{name}-routing.module.ts"
        if cand.exists():
            return cand
    return None


def flatten(routes: list[dict[str, Any]], file: Path, app_root: Path, prefix: str = "") -> list[str]:
    """Resolve children + loadChildren recursively, return list of full paths."""
    out: list[str] = []
    for r in routes:
        p = r.get("path")
        if p is None:
            continue
        if r.get("redirectTo") is not None:
            continue
        if p == "**":
            continue
        full = (prefix + "/" + p).replace("//", "/") if p else (prefix or "/")
        full = full or "/"
        if not full.startswith("/"):
            full = "/" + full
        if r.get("children"):
            out.extend(flatten(r["children"], file, app_root, full))
            if p != "":
                out.append(full)
        elif r.get("loadChildren"):
            child_file = resolve_load_children(r["loadChildren"], file, app_root)
            if child_file:
                child_routes = parse_routing_file(child_file)
                out.extend(flatten(child_routes, child_file, app_root, full))
            else:
                out.append(full)
        else:
            out.append(full)
    return out


def strip_suffix_duplicates(paths: list[str]) -> list[str]:
    """Drop entries that are an exact path suffix of another entry.

    Heuristic: child-only modules (e.g. main-group with `path: ':group_id'`) get
    standalone-flattened by glob, producing a phantom root-level route like
    `/:group_id/...` that is actually only mounted under a parent prefix
    (e.g. `/group/:group_id/...`). Dropping suffixes removes the phantom.
    """
    paths_set = set(paths)
    kept: list[str] = []
    for p in paths:
        if p == "/":
            kept.append(p)
            continue
        is_suffix = False
        for other in paths_set:
            if other == p:
                continue
            # p starts with '/'; any non-empty boundary before it lands on a segment edge.
            if other.endswith(p) and len(other) > len(p):
                is_suffix = True
                break
        if not is_suffix:
            kept.append(p)
    return kept


def collect_app_routes(repo_root: Path, app: str) -> list[str]:
    """Glob *-routing.module.ts under apps/<app>/ and libs/** (shared), flatten, dedup."""
    app_dir = repo_root / "apps" / app
    if not app_dir.exists():
        raise SystemExit(f"app not found: {app_dir}")
    libs_dir = repo_root / "libs"
    files: list[Path] = sorted(app_dir.rglob("*-routing.module.ts"))
    if libs_dir.exists():
        files.extend(sorted(libs_dir.rglob("*-routing.module.ts")))
    if not files:
        raise SystemExit(f"no *-routing.module.ts found under {app_dir} or {libs_dir}")
    paths: list[str] = []
    for f in files:
        try:
            routes = parse_routing_file(f)
        except Exception:
            continue
        paths.extend(flatten(routes, f, app_dir))
    seen: set[str] = set()
    deduped: list[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    return strip_suffix_duplicates(deduped)


def normalize_pathname(u: str) -> str:
    from urllib.parse import urlparse
    pr = urlparse(u)
    return pr.path or "/"


def origin_of(u: str) -> str:
    from urllib.parse import urlparse
    pr = urlparse(u)
    return f"{pr.scheme}://{pr.netloc}"


def harvest_hrefs(page) -> list[str]:
    try:
        return page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
        ) or []
    except Exception:
        return []


def _camel_to_snake(s: str) -> str:
    out = []
    for i, c in enumerate(s):
        if c.isupper() and i > 0:
            out.append("_")
        out.append(c.lower())
    return "".join(out)


_BAD_CHARS = set(":/?#&= ")


def _is_url_safe_segment(val: str) -> bool:
    if not val or len(val) > 80:
        return False
    return not any(c in _BAD_CHARS for c in val)


def harvest_values_from_json(obj: Any, pool: dict[str, set[str]]) -> None:
    """Walk JSON, add URL-safe scalar values into pool keyed by snake_case key name."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                key = _camel_to_snake(str(k))
                val = str(v)
                if _is_url_safe_segment(val):
                    pool.setdefault(key, set()).add(val)
            harvest_values_from_json(v, pool)
    elif isinstance(obj, list):
        for item in obj:
            harvest_values_from_json(item, pool)


def harvest_values_from_url(url: str, pool: dict[str, set[str]]) -> None:
    """From '/api/group/123/board/notice/...' infer group=123, board=notice etc."""
    from urllib.parse import urlparse
    parts = [p for p in urlparse(url).path.split("/") if p]
    for i in range(len(parts) - 1):
        key = _camel_to_snake(parts[i])
        val = parts[i + 1]
        if val.startswith(":") or not val:
            continue
        # treat as potential id for this resource name
        pool.setdefault(key + "_id", set()).add(val)
        pool.setdefault(key, set()).add(val)


def match_template(template: str, candidate: str) -> dict[str, str] | None:
    """Match candidate path against template like '/group/:group_id/boards/:board_type'."""
    t_segs = [s for s in template.split("/") if s != ""]
    c_segs = [s for s in candidate.split("/") if s != ""]
    if len(t_segs) != len(c_segs):
        return None
    out: dict[str, str] = {}
    for t, c in zip(t_segs, c_segs):
        if t.startswith(":"):
            if not c or c.startswith(":"):
                return None
            out[t[1:]] = c
        elif t != c:
            return None
    return out


def fill_template(template: str, vars_: dict[str, str]) -> str | None:
    segs = template.split("/")
    out: list[str] = []
    for s in segs:
        if s.startswith(":"):
            v = vars_.get(s[1:])
            if v is None:
                return None
            out.append(v)
        else:
            out.append(s)
    return "/".join(out)


def visit_once(page, req_path: str, timeout: int, base_origin: str) -> dict[str, Any]:
    """Visit one route, return classification dict (status/reason/finalUrl)."""
    try:
        page.goto(req_path, wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except PWTimeout:
            pass
        page.wait_for_timeout(500)
        final = page.url
        if origin_of(final) != base_origin:
            return {"finalUrl": final, "reason": "unreachable-origin"}
        if normalize_pathname(final) != req_path:
            return {"finalUrl": final, "reason": "redirected"}
        return {"finalUrl": final, "status": "ok"}
    except PWTimeout:
        return {"finalUrl": page.url, "reason": "timeout"}
    except Exception as e:
        return {"finalUrl": page.url, "reason": f"error: {e.__class__.__name__}"}


def attach_response_harvester(page, pool: dict[str, set[str]]) -> None:
    import json as _json
    def on_response(resp):
        try:
            url = resp.url
            harvest_values_from_url(url, pool)
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            body = resp.text()
            if not body:
                return
            try:
                obj = _json.loads(body)
            except Exception:
                return
            harvest_values_from_json(obj, pool)
        except Exception:
            pass
    page.on("response", on_response)


def variables_of(template: str) -> list[str]:
    return [s[1:] for s in template.split("/") if s.startswith(":")]


def candidates_for_var(v: str, pool: dict[str, set[str]]) -> list[str]:
    out: list[str] = []
    for key in (v, v.replace("_id", ""), v + "_id"):
        if key in pool:
            out.extend(sorted(pool[key]))
    seen: set[str] = set()
    deduped: list[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        deduped.append(x)
    return deduped


def seed_candidates(template: str, pool: dict[str, set[str]], max_try: int = 5) -> list[str]:
    """Yield up to max_try concrete paths by combining first-N candidates per var."""
    vars_ = variables_of(template)
    cand_per_var = [candidates_for_var(v, pool) for v in vars_]
    if any(not c for c in cand_per_var):
        return []
    # take cartesian-ish but bounded: cycle by index up to max_try
    results: list[str] = []
    for i in range(max_try):
        if i >= max(len(c) for c in cand_per_var):
            break
        chosen = {v: cand_per_var[idx][min(i, len(cand_per_var[idx]) - 1)] for idx, v in enumerate(vars_)}
        path = fill_template(template, chosen)
        if path and path not in results:
            results.append(path)
    return results


def verify_routes(routes: list[str], base: str, auth: Path | None, timeout: int) -> tuple[list[dict], list[dict]]:
    reachable: list[dict] = []
    excluded: list[dict] = []
    base_origin = origin_of(base)
    static_routes = [r for r in routes if ":" not in r]
    var_routes = [r for r in routes if ":" in r]
    pool: dict[str, set[str]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx_kwargs: dict[str, Any] = {"base_url": base}
        if auth and auth.exists():
            ctx_kwargs["storage_state"] = str(auth)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        attach_response_harvester(page, pool)

        # pass 1 — static routes, harvest network responses
        for route in static_routes:
            req_path = route if route.startswith("/") else "/" + route
            print(f"[discover] {req_path}", file=sys.stderr)
            entry = {"route": req_path}
            res = visit_once(page, req_path, timeout, base_origin)
            if "status" in res:
                reachable.append({**entry, **res})
            else:
                excluded.append({**entry, **res})

        # pass 2 — multi-pass: seed variable routes from the pool. each successful
        # visit may unlock more seeds. iterate until no new var route resolves.
        pending = list(var_routes)
        decided: set[str] = set()
        progress = True
        while pending and progress:
            progress = False
            still: list[str] = []
            for template in pending:
                if template in decided:
                    continue
                cands = seed_candidates(template, pool)
                if not cands:
                    still.append(template)
                    continue
                landed = False
                last_res: dict[str, Any] = {}
                last_path = ""
                for seed_path in cands:
                    print(f"[discover] {template} -> {seed_path}", file=sys.stderr)
                    res = visit_once(page, seed_path, timeout, base_origin)
                    last_res, last_path = res, seed_path
                    if "status" in res and normalize_pathname(res["finalUrl"]) == seed_path:
                        reachable.append({"route": template, "seededPath": seed_path, **res})
                        landed = True
                        break
                if not landed:
                    excluded.append({"route": template, "seededPath": last_path, **last_res})
                decided.add(template)
                progress = True
            pending = still

        for template in pending:
            excluded.append({"route": template, "finalUrl": "", "reason": "no-seed"})

        context.close()
        browser.close()
    return reachable, excluded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--root", required=True, help="Repository root containing apps/<app>")
    ap.add_argument("--base", required=True, help="Base URL of running dev server")
    ap.add_argument("--auth", default=None)
    ap.add_argument("--timeout", type=int, default=8000)
    ap.add_argument(
        "--out",
        default=None,
        help="Output JSON path. Default: <root>/.claude/migration-runtime-check/discover-<app>.json",
    )
    args = ap.parse_args()

    repo_root = Path(args.root).resolve()
    routes = collect_app_routes(repo_root, args.app)
    print(f"[discover] parsed {len(routes)} routes from app={args.app}", file=sys.stderr)

    auth_path = Path(args.auth).resolve() if args.auth else None
    reachable, excluded = verify_routes(routes, args.base, auth_path, args.timeout)

    payload = {
        "app": args.app,
        "baseUrl": args.base,
        "totalParsed": len(routes),
        "reachable": reachable,
        "excluded": excluded,
    }
    out_path = (
        Path(args.out).resolve()
        if args.out
        else (repo_root / ".claude" / "migration-runtime-check" / f"discover-{args.app}.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[discover] wrote {out_path}", file=sys.stderr)
    sys.stdout.write(json.dumps({
        "outPath": str(out_path),
        "app": args.app,
        "totalParsed": len(routes),
        "reachableCount": len(reachable),
        "excludedCount": len(excluded),
    }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

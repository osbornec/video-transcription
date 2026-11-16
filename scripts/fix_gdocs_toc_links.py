"""
Import Markdown to Google Docs (optional), rebind Table of Contents slug anchors
(#topic-slug or #1-topic-slug) to native Google Docs headingId links (#heading=h.xxx),
and optionally create local .url / .webloc shortcut files in the workspace folder.

Supports two backends automatically (`--backend auto`):
1. `gdocs`: Google Antigravity's built-in gdocs plugin CLI (when available).
2. `rest`: Direct Google Drive API v3 + Google Docs API v1 REST calls (for Claude Code,
   OpenAI Codex, Cursor, or standalone CLI users authenticated via gcloud / OAuth).

Usage:
    python3 fix_gdocs_toc_links.py <DOC_ID> [--tab t.0]
    python3 fix_gdocs_toc_links.py --import-md transcript.md --title "Title" --shortcut-dir "."
    python3 fix_gdocs_toc_links.py <DOC_ID> --import-md transcript.md --shortcut-format auto
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
DOCS_API_BASE = "https://docs.googleapis.com/v1/documents"


def resolve_gdocs_bin() -> str | None:
    """Locate the gdocs CLI binary cross-platform, or return None if unavailable."""
    env_bin = os.environ.get("GDOCS_BIN", "").strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin

    on_path = shutil.which("gdocs")
    if on_path:
        return on_path

    home = Path.home()
    candidates = [
        home / ".gemini" / "antigravity" / "bin" / "gdocs",
        home / ".gemini" / "antigravity" / "bin" / "gdocs.cmd",
        home / ".gemini" / "config" / "plugins" / "gdocs" / "skills" / "gdocs" / "scripts" / "gdocs",
        home / ".gemini" / "config" / "plugins" / "gdocs" / "skills" / "gdocs" / "scripts" / "gdocs.sh",
        home / ".gemini" / "config" / "plugins" / "gdocs" / "skills" / "gdocs" / "scripts" / "gdocs.cmd",
        home / ".gemini" / "config" / "plugins" / "gdocs" / "skills" / "gdocs" / "scripts" / "gdocs.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _run_token_cmd(cmd: list[str]) -> str | None:
    """Attempt to obtain an access token from an external CLI command."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    except Exception:
        return None
    if res.returncode == 0:
        tok = res.stdout.strip()
        if tok and len(tok) > 10:
            return tok
    return None


def _exchange_adc_refresh_token(adc_path: Path) -> str | None:
    """Exchange an authorized_user ADC JSON refresh token cleanly for an access token."""
    if not adc_path.is_file():
        return None
    try:
        data = json.loads(adc_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("type") != "authorized_user":
        return None

    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    refresh_token = data.get("refresh_token")
    if not (client_id and client_secret and refresh_token):
        return None

    form = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            tok_json = json.loads(resp.read().decode("utf-8"))
            return tok_json.get("access_token")
    except Exception:
        return None


def resolve_google_access_token() -> str:
    """Resolve a Google OAuth2 bearer token via env, gcloud CLI, or ADC credentials."""
    env_tok = os.environ.get("GOOGLE_ACCESS_TOKEN", "").strip()
    if env_tok:
        return env_tok

    gcloud = shutil.which("gcloud")
    if gcloud:
        for sub in (["auth", "application-default", "print-access-token"], ["auth", "print-access-token"]):
            tok = _run_token_cmd([gcloud, *sub])
            if tok:
                return tok

    adc_candidates: list[Path] = []
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        adc_candidates.append(Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).expanduser())
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        adc_candidates.append(Path(appdata) / "gcloud" / "application_default_credentials.json")
    adc_candidates.append(Path.home() / ".config" / "gcloud" / "application_default_credentials.json")

    for adc_path in adc_candidates:
        tok = _exchange_adc_refresh_token(adc_path)
        if tok:
            return tok

    raise PermissionError(
        "No 'gdocs' CLI or Google OAuth access token found.\n"
        "To publish to Google Docs outside Antigravity, authenticate with Drive/Docs scopes:\n"
        "  gcloud auth application-default login \\\n"
        "    --scopes=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/cloud-platform\n"
        "or export GOOGLE_ACCESS_TOKEN=<token>.\n"
        "(Local Markdown .md files already work without Google Docs.)"
    )


def _rest_request(
    url: str,
    token: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> dict:
    """Perform an authenticated Google REST API call and parse JSON response."""
    req_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google API HTTP {exc.code} on {method} {url}:\n{body}") from exc


def build_drive_multipart_payload(title: str, md_bytes: bytes, boundary: str) -> bytes:
    """Build multipart/related body importing Markdown as a native Google Doc."""
    meta_bytes = json.dumps(
        {"name": title, "mimeType": "application/vnd.google-apps.document"}
    ).encode("utf-8")
    b = boundary.encode("ascii")
    parts = [
        b"--" + b + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + meta_bytes + b"\r\n",
        b"--" + b + b"\r\nContent-Type: text/markdown; charset=UTF-8\r\n\r\n" + md_bytes + b"\r\n",
        b"--" + b + b"--\r\n",
    ]
    return b"".join(parts)


def build_batch_update_requests(
    bindings: list[tuple[int, int, str]], tab_id: str = ""
) -> dict:
    """Construct Google Docs batchUpdate updateTextStyle requests binding ToC anchors."""
    requests = []
    for start_idx, end_idx, hid in bindings:
        rng: dict[str, int | str] = {"startIndex": start_idx, "endIndex": end_idx}
        if tab_id:
            rng["tabId"] = tab_id
        requests.append(
            {
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"link": {"headingId": hid}},
                    "fields": "link",
                }
            }
        )
    return {"requests": requests}


def _find_tab_body(tabs: list[dict], tab_id: str) -> dict | None:
    """Recursively locate a specific tabId's documentTab body inside Google Docs JSON."""
    for tab in tabs:
        props = tab.get("tabProperties", {})
        if props.get("tabId") == tab_id:
            return tab.get("documentTab", {}).get("body")
        child = _find_tab_body(tab.get("childTabs", []), tab_id)
        if child is not None:
            return child
    return None


def select_doc_body(doc_json: dict, tab_id: str = "") -> dict:
    """Extract normalized body object compatible with extract_toc_mappings()."""
    if tab_id:
        tab_body = _find_tab_body(doc_json.get("tabs", []), tab_id)
        if tab_body is not None:
            return tab_body
    if "body" in doc_json:
        return doc_json["body"]
    tabs = doc_json.get("tabs", [])
    if tabs:
        return tabs[0].get("documentTab", {}).get("body", {})
    return doc_json


def rest_import_markdown(
    token: str, md_path: str, doc_id: str, title: str
) -> tuple[str, str]:
    """Create or update a native Google Doc from Markdown via Google Drive API v3."""
    path = Path(md_path)
    if not path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")
    md_bytes = path.read_bytes()
    resolved_title = title or path.stem

    if doc_id:
        url = f"{DRIVE_UPLOAD_BASE}/{urllib.parse.quote(doc_id)}?uploadType=media&fields=id,name"
        resp = _rest_request(
            url,
            token,
            method="PATCH",
            headers={"Content-Type": "text/markdown; charset=UTF-8"},
            data=md_bytes,
        )
        print(f"Updated: {resp.get('name', resolved_title)} (ID: {resp.get('id', doc_id)})")
        return resp.get("id", doc_id), resp.get("name", resolved_title)

    boundary = f"bnd_{uuid.uuid4().hex}"
    body = build_drive_multipart_payload(resolved_title, md_bytes, boundary)
    url = f"{DRIVE_UPLOAD_BASE}?uploadType=multipart&fields=id,name"
    resp = _rest_request(
        url,
        token,
        method="POST",
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
    )
    new_id = resp["id"]
    new_name = resp.get("name", resolved_title)
    print(f"Created: {new_name} (ID: {new_id})")
    print(f"Link: https://docs.google.com/document/d/{new_id}/edit")
    return new_id, new_name


def rest_get_document(token: str, doc_id: str, tab_id: str = "") -> tuple[dict, dict]:
    """Fetch full Google Docs JSON via Docs API v1 and return (full_doc, body_dict)."""
    url = f"{DOCS_API_BASE}/{urllib.parse.quote(doc_id)}?includeTabsContent=true"
    doc_json = _rest_request(url, token, method="GET")
    return doc_json, select_doc_body(doc_json, tab_id)


def rest_bind_toc_links(
    token: str, doc_id: str, bindings: list[tuple[int, int, str]], tab_id: str = ""
) -> None:
    """Bind all ToC anchor spans to native headingIds in one batchUpdate call."""
    if not bindings:
        return
    url = f"{DOCS_API_BASE}/{urllib.parse.quote(doc_id)}:batchUpdate"
    payload = build_batch_update_requests(bindings, tab_id)
    _rest_request(
        url,
        token,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(payload).encode("utf-8"),
    )


def run_gdocs(gdocs_bin: str, args: list[str]) -> str:
    """Execute a gdocs CLI subcommand and return decoded stdout."""
    cmd = [gdocs_bin, *args]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        out = res.stdout.decode("utf-8", errors="replace")
        raise RuntimeError(f"gdocs {' '.join(args)} failed (code {res.returncode}):\n{err}\n{out}")

    for enc in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return res.stdout.decode(enc)
        except UnicodeDecodeError:
            continue
    return res.stdout.decode("utf-8", errors="replace")


def github_slug(text: str) -> str:
    """Compute a GitHub Markdown heading slug matching Drive import anchors."""
    cleaned = re.sub(r"[^a-z0-9\s_-]", "", text.strip().lower())
    return cleaned.replace(" ", "-")


def collapse_hyphens(slug: str) -> str:
    """Normalize repeated hyphens to match collapsed author-written ToC slugs."""
    return re.sub(r"-+", "-", slug).strip("-")


def get_body_content(doc_json: dict | list) -> list[dict]:
    """Extract paragraph element list across gdocs dump-body or REST API JSON layouts."""
    if isinstance(doc_json, list):
        return doc_json
    return doc_json.get("content", doc_json.get("body", {}).get("content", []))


def extract_toc_mappings(
    doc_json: dict | list,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, list]]:
    """Collect headingIds (by exact slug, collapsed slug, and number) and merge ToC spans."""
    exact_headings: dict[str, str] = {}
    collapsed_headings: dict[str, str] = {}
    numbered_headings: dict[str, str] = {}
    merged_spans: dict[str, list] = {}

    for el in get_body_content(doc_json):
        p = el.get("paragraph")
        if not p:
            continue
        ps = p.get("paragraphStyle", {})
        hid = ps.get("headingId")
        txt = "".join(r.get("textRun", {}).get("content", "") for r in p.get("elements", [])).strip()

        if hid and txt:
            slug = github_slug(txt)
            exact_headings[slug] = hid
            collapsed_headings[collapse_hyphens(slug)] = hid
            m_num = re.match(r"^(\d+)\.\s+", txt)
            if m_num:
                numbered_headings[m_num.group(1)] = hid

        for r in p.get("elements", []):
            tr = r.get("textRun", {})
            url = tr.get("textStyle", {}).get("link", {}).get("url", "")
            if not url.startswith("#") or url.startswith("#heading="):
                continue

            anchor = url[1:]
            s = r.get("startIndex")
            e = r.get("endIndex")
            label = tr.get("content", "").strip()
            if anchor not in merged_spans:
                merged_spans[anchor] = [s, e, label]
            else:
                merged_spans[anchor][0] = min(merged_spans[anchor][0], s)
                merged_spans[anchor][1] = max(merged_spans[anchor][1], e)

    return exact_headings, collapsed_headings, numbered_headings, merged_spans


def resolve_target_heading(
    anchor: str,
    exact_headings: dict[str, str],
    collapsed_headings: dict[str, str],
    numbered_headings: dict[str, str],
) -> str | None:
    """Resolve a Markdown #slug anchor to its Google Docs headingId."""
    norm = anchor.lower()
    if norm in exact_headings:
        return exact_headings[norm]
    norm_collapsed = collapse_hyphens(norm)
    if norm_collapsed in collapsed_headings:
        return collapsed_headings[norm_collapsed]
    m_num = re.match(r"^(\d+)(?:-|$)", norm)
    if m_num and m_num.group(1) in numbered_headings:
        return numbered_headings[m_num.group(1)]
    return None


def import_markdown_cli(
    gdocs_bin: str, md_path: str, doc_id: str, title: str
) -> tuple[str, str]:
    """Import or update a Google Doc from Markdown via gdocs CLI."""
    if not os.path.exists(md_path):
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    cmd_args = ["mutate", "import-md", md_path]
    if doc_id:
        cmd_args.extend(["--update", doc_id])
    elif title:
        cmd_args.extend(["--title", title])

    output = run_gdocs(gdocs_bin, cmd_args)
    print(output.strip())

    resolved_id = doc_id
    if not resolved_id:
        m_id = re.search(
            r"(?:ID:|Updated Doc ID:|/document/d/)\s*([A-Za-z0-9_-]{20,})", output
        )
        if not m_id:
            raise RuntimeError(f"Could not parse Doc ID from import-md output:\n{output}")
        resolved_id = m_id.group(1)

    resolved_title = title
    if not resolved_title:
        m_created = re.search(r"Created:\s*(.+?)\s*\(ID:", output)
        resolved_title = (
            m_created.group(1).strip()
            if m_created
            else os.path.splitext(os.path.basename(md_path))[0]
        )

    return resolved_id, resolved_title


def write_url_shortcut(shortcut_dir: str, name: str, doc_id: str) -> str:
    """Write a cross-platform .url InternetShortcut pointing to the Google Doc."""
    os.makedirs(shortcut_dir, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*]', "-", name).strip()
    out_path = os.path.join(shortcut_dir, f"{safe_name} (Google Doc).url")
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    with open(out_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(f"[InternetShortcut]\nURL={url}\n")
    return out_path


def write_webloc_shortcut(shortcut_dir: str, name: str, doc_id: str) -> str:
    """Write a native macOS Finder .webloc XML plist pointing to the Google Doc."""
    os.makedirs(shortcut_dir, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*]', "-", name).strip()
    out_path = os.path.join(shortcut_dir, f"{safe_name} (Google Doc).webloc")
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "\t<key>URL</key>\n"
        f"\t<string>{escape(url)}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(plist)
    return out_path


def write_shortcuts(shortcut_dir: str, name: str, doc_id: str, fmt: str) -> list[str]:
    """Write requested shortcut format(s) (.url, .webloc, or both) for a Google Doc."""
    written: list[str] = []
    chosen = fmt
    if chosen == "auto":
        chosen = "webloc" if platform.system().lower() == "darwin" else "url"
    if chosen in ("url", "both"):
        written.append(write_url_shortcut(shortcut_dir, name, doc_id))
    if chosen in ("webloc", "both"):
        written.append(write_webloc_shortcut(shortcut_dir, name, doc_id))
    return written


def count_bound_headings(body_dict: dict | list) -> set[str]:
    """Collect active headingId link targets across the document body."""
    bound_hids: set[str] = set()
    for el in get_body_content(body_dict):
        p = el.get("paragraph")
        if not p:
            continue
        for r in p.get("elements", []):
            lk = r.get("textRun", {}).get("textStyle", {}).get("link", {})
            if "headingId" in lk:
                bound_hids.add(lk["headingId"])
    return bound_hids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Markdown to Google Docs and/or bind ToC anchors to native headingIds."
    )
    parser.add_argument("doc_id", nargs="?", default="", help="Target Google Doc ID")
    parser.add_argument("--tab", default="", help="Optional tab ID (e.g. t.0)")
    parser.add_argument("--import-md", dest="import_md", default="", help="Path to Markdown file to import/update")
    parser.add_argument("--title", default="", help="Google Doc title when creating a new doc via --import-md")
    parser.add_argument("--shortcut-dir", dest="shortcut_dir", default="", help="Directory to write local shortcut file(s)")
    parser.add_argument(
        "--shortcut-format",
        dest="shortcut_format",
        choices=["url", "webloc", "both", "auto"],
        default="url",
        help="Shortcut file format: url, webloc (macOS), both, or auto (default: url)",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "gdocs", "rest"],
        default="auto",
        help="Backend: 'gdocs' (Antigravity CLI), 'rest' (Drive/Docs REST API), or 'auto' (default)",
    )
    args = parser.parse_args()

    if not args.doc_id and not args.import_md:
        parser.error("Provide either DOC_ID, --import-md, or both.")

    gdocs_bin = resolve_gdocs_bin() if args.backend in ("auto", "gdocs") else None
    if args.backend == "gdocs" and not gdocs_bin:
        raise FileNotFoundError("Backend 'gdocs' requested, but 'gdocs' CLI was not found.")
    use_rest = args.backend == "rest" or gdocs_bin is None

    doc_id = args.doc_id
    shortcut_label = args.title

    if not use_rest:
        assert gdocs_bin is not None
        if args.import_md:
            doc_id, derived_title = import_markdown_cli(gdocs_bin, args.import_md, doc_id, args.title)
            if not shortcut_label:
                shortcut_label = os.path.splitext(os.path.basename(args.import_md))[0] or derived_title

        dump_args = ["readonly", "dump-body", doc_id]
        if args.tab:
            dump_args.extend(["--tab", args.tab])

        doc_json = json.loads(run_gdocs(gdocs_bin, dump_args))
        exact_h, collapsed_h, numbered_h, merged_spans = extract_toc_mappings(doc_json)

        updated = 0
        if not merged_spans:
            print("No unbound '#' ToC slug links found.")
        else:
            for anchor, (start_idx, end_idx, _label) in sorted(merged_spans.items(), key=lambda kv: kv[1][0]):
                hid = resolve_target_heading(anchor, exact_h, collapsed_h, numbered_h)
                if not hid:
                    print(f"Warning: No matching headingId for '#{anchor}'; skipping.", file=sys.stderr)
                    continue
                fmt_args = [
                    "mutate",
                    "format-text",
                    doc_id,
                    "--start",
                    str(start_idx),
                    "--end",
                    str(end_idx),
                    "--url",
                    f"#heading={hid}",
                ]
                if args.tab:
                    fmt_args.extend(["--tab", args.tab])
                run_gdocs(gdocs_bin, fmt_args)
                print(f"Bound '#{anchor}' [{start_idx}..{end_idx}] -> #heading={hid}")
                updated += 1

            verify_json = json.loads(run_gdocs(gdocs_bin, dump_args))
            bound_hids = count_bound_headings(verify_json)
            print(f"Verification complete: {updated} ToC entries updated, {len(bound_hids)} unique headingId targets active.")

        if args.shortcut_dir:
            if not shortcut_label:
                info_json = json.loads(run_gdocs(gdocs_bin, ["readonly", "info", doc_id, "--json"]))
                shortcut_label = info_json.get("title", doc_id)
            for shortcut_path in write_shortcuts(args.shortcut_dir, shortcut_label, doc_id, args.shortcut_format):
                print(f"Shortcut written: {shortcut_path}")
        return 0

    token = resolve_google_access_token()
    if args.import_md:
        doc_id, derived_title = rest_import_markdown(token, args.import_md, doc_id, args.title)
        if not shortcut_label:
            shortcut_label = os.path.splitext(os.path.basename(args.import_md))[0] or derived_title

    full_doc, body_dict = rest_get_document(token, doc_id, args.tab)
    exact_h, collapsed_h, numbered_h, merged_spans = extract_toc_mappings(body_dict)

    if not merged_spans:
        print("No unbound '#' ToC slug links found.")
    else:
        bindings: list[tuple[int, int, str]] = []
        for anchor, (start_idx, end_idx, _label) in sorted(merged_spans.items(), key=lambda kv: kv[1][0]):
            hid = resolve_target_heading(anchor, exact_h, collapsed_h, numbered_h)
            if not hid:
                print(f"Warning: No matching headingId for '#{anchor}'; skipping.", file=sys.stderr)
                continue
            bindings.append((start_idx, end_idx, hid))
            print(f"Binding '#{anchor}' [{start_idx}..{end_idx}] -> #heading={hid}")

        rest_bind_toc_links(token, doc_id, bindings, args.tab)
        _, verify_body = rest_get_document(token, doc_id, args.tab)
        bound_hids = count_bound_headings(verify_body)
        print(f"Verification complete (REST): {len(bindings)} ToC entries updated, {len(bound_hids)} unique headingId targets active.")

    if args.shortcut_dir:
        if not shortcut_label:
            shortcut_label = full_doc.get("title", doc_id)
        for shortcut_path in write_shortcuts(args.shortcut_dir, shortcut_label, doc_id, args.shortcut_format):
            print(f"Shortcut written: {shortcut_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

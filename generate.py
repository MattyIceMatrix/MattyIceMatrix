#!/usr/bin/env python3
# Blast radius: reads profile.json + ascii.txt in this repo, calls the GitHub API
# (read-only), and writes dark_mode.svg, light_mode.svg and stats.json in this
# repo root. Nothing else is touched. Standard library only — no installs.
"""Render the neofetch-style profile card for the GitHub profile README.

Run locally:  GH_TOKEN=<token> python generate.py
Without a token it re-renders from the last stats.json (or shows dashes).
"""
import datetime as dt
import json
import math
import random
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
API = "https://api.github.com"
WIDTH = 58          # characters in the info panel
FONT = 16           # px
CW = 9.65           # px per monospace glyph at 16px
LH = 20             # line height px

THEMES = {
    "dark": dict(bg1="#0b0f19", bg2="#111827", bar="#0a0d14", border="#2f81f7",
                 text="#e6edf3", key="#39d0ff", value="#e6edf3", dots="#30394a",
                 accent="#ff4fd8", prompt="#3fb950", add="#3fb950", dele="#f85149",
                 frame="#2f81f7", pin="#8b949e", mesh="#1f6feb", node="#39d0ff",
                 node_hot="#ffffff", label="#ff4fd8", scan="#39d0ff", glow=1,
                 rain="#00ff9c", rain_head="#d9fff0", rain_op=".22", rain_boot=".55",
                 portrait=["#16335e", "#1b4f9c", "#1f6feb", "#2ea8f5", "#39d0ff", "#8be6ff", "#d4f6ff", "#ffffff"]),
    "light": dict(bg1="#ffffff", bg2="#f3f6fb", bar="#eaeef2", border="#0969da",
                  text="#1f2328", key="#0969da", value="#1f2328", dots="#c8d1dc",
                  accent="#bf3989", prompt="#1a7f37", add="#1a7f37", dele="#cf222e",
                  frame="#0969da", pin="#8c959f", mesh="#54aeff", node="#0969da",
                  node_hot="#bf3989", label="#bf3989", scan="#0969da", glow=0,
                  rain="#1a7f37", rain_head="#0969da", rain_op=".09", rain_boot=".30",
                  portrait=["#0a1f44", "#0a3069", "#0b4596", "#0969da", "#3b8eea", "#6aaef2", "#9cc7f5", "#c6ddf9"]),
}
PALETTE = ["#484f58", "#ff7b72", "#3fb950", "#d29922", "#58a6ff", "#bc8cff", "#39c5cf", "#b1bac4",
           "#6e7681", "#ffa198", "#56d364", "#e3b341", "#79c0ff", "#d2a8ff", "#56d4dd", "#ffffff"]
COMMAND = "neofetch --edge-ai"


# ---------------------------------------------------------------- GitHub data
def _req(url, token, body=None):
    headers = {"Authorization": f"bearer {token}", "User-Agent": "profile-card",
               "Accept": "application/vnd.github+json"}
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, json.loads(resp.read() or b"null")


def gql(query, token, **variables):
    _, out = _req(f"{API}/graphql", token, {"query": query, "variables": variables})
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


def fetch_stats(login, token):
    d = gql("""query($login:String!){ user(login:$login){
        createdAt followers{totalCount}
        contributionsCollection{ contributionCalendar{ weeks{ contributionDays{ contributionCount } } } }
        repositoriesContributedTo(contributionTypes:[COMMIT,PULL_REQUEST,REPOSITORY]){totalCount}
        repositories(ownerAffiliations:OWNER, first:100, isFork:false){
          totalCount nodes{ nameWithOwner stargazerCount
            languages(first:20, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name color } } } } } } }""", token, login=login)["user"]
    repos = d["repositories"]["nodes"]
    stats = {
        "repos": d["repositories"]["totalCount"],
        "contributed": d["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": d["followers"]["totalCount"],
        "calendar": [[day["contributionCount"] for day in w["contributionDays"]]
                     for w in d["contributionsCollection"]["contributionCalendar"]["weeks"]],
    }

    # commits: one contributionsCollection per calendar year since the account opened
    start = int(d["createdAt"][:4])
    now = dt.datetime.now(dt.timezone.utc)
    commits = 0
    for year in range(start, now.year + 1):
        c = gql("""query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
            contributionsCollection(from:$from,to:$to){
              totalCommitContributions restrictedContributionsCount } } }""", token,
                login=login, **{"from": f"{year}-01-01T00:00:00Z",
                                "to": min(now, dt.datetime(year, 12, 31, 23, 59, 59,
                                                           tzinfo=dt.timezone.utc)).isoformat()})
        cc = c["user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
    stats["commits"] = commits

    # code by language: GitHub's linguist byte counts (skips vendored, generated and docs files)
    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            size, color = langs.get(n, (0, e["node"]["color"]))
            langs[n] = (size + e["size"], color or "#8b949e")
    total = sum(v[0] for v in langs.values()) or 1
    stats["languages"] = [[n, round(100 * v[0] / total, 1), v[1]]
                          for n, v in sorted(langs.items(), key=lambda kv: -kv[1][0])]
    stats["updated"] = now.strftime("%Y-%m-%d")
    return stats


# ---------------------------------------------------------------- rendering
def uptime(cfg):
    if not cfg.get("birthday"):
        return cfg.get("age_fallback", "")
    b = dt.date.fromisoformat(cfg["birthday"])
    t = dt.date.today()
    months = (t.year - b.year) * 12 + t.month - b.month - (t.day < b.day)
    y, m = divmod(months, 12)
    return f"{y} years, {m} month{'s' * (m != 1)}"


def fmt(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def span(cls, s):
    return f'<tspan class="{cls}">{escape(s)}</tspan>'


def kv(key, value, cls="value"):
    """'. Key: ......... value' padded to WIDTH."""
    left = f". {key}:"
    dots = WIDTH - len(left) - len(value) - 2
    if dots < 1:
        value = value[: WIDTH - len(left) - 4] + "…"
        dots = 1
    return [span("cc", ". "), span("key", key), ":", span("cc", " " + "." * dots + " "),
            span(cls, value)]


def header(title):
    rest = WIDTH - len(title) - 3
    return [span("cc", "- "), f'<tspan class="acc" font-weight="bold">{escape(title)}</tspan>', span("cc", " " + "-" * rest)]


def build_lines(cfg, s):
    lines = [[cfg["header"], span("cc", " " + "-" * (WIDTH - len(cfg["header"]) - 1))]]
    blocks = cfg["sections"]
    for i, blk in enumerate(blocks):
        if len(blk) == 1 and isinstance(blk[0], str):
            lines.append([])
            lines.append(header(blk[0]))
            continue
        if i and not (len(blocks[i - 1]) == 1 and isinstance(blocks[i - 1][0], str)):
            lines.append([span("cc", ".")])
        for k, v in blk:
            lines.append(kv(k, v.replace("{uptime}", uptime(cfg))))

    # stats block, two columns like the original
    lines.append([])
    lines.append(header("GitHub Stats"))

    def pair(k1, v1, k2, v2, extra=None):
        a = f". {k1}: "
        a_val = v1 + (f" {{{extra[0]}: {extra[1]}}}" if extra else "")
        left_w = 34
        dots = left_w - len(a) - len(a_val) - 1
        out = [span("cc", ". "), span("key", k1), ":", span("cc", " " + "." * dots + " "),
               span("value", v1)]
        if extra:
            out += [" {", span("key", extra[0]), ": ", span("value", extra[1]), "}"]
        b = f" | {k2}: "
        dots2 = WIDTH - left_w - len(b) - len(v2)
        out += [" | ", span("key", k2), ":", span("cc", " " + "." * max(dots2, 1) + " "),
                span("value", v2)]
        return out

    lines.append(pair("Repos", fmt(s.get("repos")), "Stars", fmt(s.get("stars")),
                      ("Contributed", fmt(s.get("contributed")))))
    lines.append(pair("Commits", fmt(s.get("commits")), "Followers", fmt(s.get("followers"))))
    # Code: Python 61% · JavaScript 22% · ...  (each name in its GitHub language colour)
    key = "Code"
    room = WIDTH - len(f". {key}: ") - 1
    shown, used = [], 0
    for name, pct, color in s.get("languages") or []:
        item = f"{name} {pct:.0f}%"
        add = len(item) + (3 if shown else 0)
        if pct < 1 or used + add > room:
            break
        shown.append((item, color))
        used += add
    if not shown:
        shown, used = [("-", None)], 1
    dots = WIDTH - len(f". {key}: ") - used
    parts = [span("cc", ". "), span("key", key), ":", span("cc", " " + "." * max(dots, 1) + " ")]
    for k, (item, color) in enumerate(shown):
        if k:
            parts.append(span("cc", " · "))
        parts.append(f'<tspan fill="{color}">{escape(item)}</tspan>' if color else span("value", item))
    lines.append(parts)
    return lines


def art_spans(art):
    """Colour the chip: pins, frame, neural mesh (pulsing nodes), label."""
    out = []
    for r, line in enumerate(art):
        parts, run, run_cls = [], "", None

        def flush():
            nonlocal run, run_cls
            if run:
                parts.append(f'<tspan class="{run_cls}">{escape(run)}</tspan>')
            run, run_cls = "", None

        for c, ch in enumerate(line):
            interior = 9 <= c <= 35
            if r in (0, len(art) - 1) or c < 5 or c > 37:
                cls = "pin"
            elif 3 <= r <= 11 and interior:
                cls = "mesh"
            elif 12 <= r <= 14 and interior and ch not in "|":
                cls = "label"
            else:
                cls = "frame"
            if ch == "o" and cls == "mesh":
                flush()
                delay = round((c / 5 + r / 4) * 0.18, 2)
                parts.append(f'<tspan class="node" style="animation-delay:{delay}s">o</tspan>')
                continue
            if cls != run_cls:
                flush()
                run_cls = cls
            run += ch
        flush()
        out.append("".join(parts))
    return out


BOOT_LOG = [
    ("[    0.000000]", " moore-edge kernel 6.x booting on npu0"),
    ("[  OK  ]", " Mounted /dev/npu0 (int8, <1W TDP)"),
    ("[  OK  ]", " Started homelab.service (Proxmox VE)"),
    ("[  OK  ]", " Started pentest.service (HTB)"),
    ("[  OK  ]", " Loaded service-record: US Army, 8 yrs"),
    ("[  OK  ]", " Loaded edge-ai.model (quantized)"),
    ("[  OK  ]", " Reached target: Edge AI Engineer"),
    ("", ""),
    ("moore-edge login:", " matthew"),
]


GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789Z:.=*+<>¦"
SCRAMBLE = "!<>-_/[]{}=+*^?#01ｱｸｾﾂﾅﾐ"


def matrix_rain(w, h, c, rng):
    """Digital rain behind the terminal: falling glyph columns, bright heads."""
    out = [f'<g class="rain" font-size="14px" aria-hidden="true">']
    col_w = 15
    for k in range(int(w / col_w) + 1):
        n = rng.randint(10, 26)
        dur = rng.uniform(5.5, 12.0)
        delay = -rng.uniform(0, dur)
        x = k * col_w + 2
        spans = []
        for j in range(n):
            g = escape(rng.choice(GLYPHS))
            if j == n - 1:
                spans.append(f'<tspan x="{x}" dy="17" fill="{c["rain_head"]}">{g}</tspan>')
            else:
                spans.append(f'<tspan x="{x}" dy="17" fill-opacity="{(j + 1) / n:.2f}">{g}</tspan>')
        out.append(f'<text class="drop" fill="{c["rain"]}" y="0" '
                   f'style="animation-duration:{dur:.2f}s;animation-delay:{delay:.2f}s">{"".join(spans)}</text>')
    out.append("</g>")
    return out


def scramble(text, x, y, t0, final_open, rng, frames=10, step=0.045):
    """Matrix-style decode: random glyphs resolve left to right into `text`."""
    out = []
    for f in range(frames):
        k = int(len(text) * f / frames)
        s = text[:k] + "".join(ch if ch == " " else rng.choice(SCRAMBLE) for ch in text[k:])
        a, b = t0 + f * step, t0 + (f + 1) * step
        out.append(f'<text class="sc acc" font-weight="bold" x="{x:.1f}" y="{y}" '
                   f'style="animation-delay:{a:.3f}s,{b:.3f}s">{escape(s)}</text>')
    t_end = t0 + frames * step
    out.append(f'<text class="pop" x="{x:.1f}" y="{y}" style="animation-delay:{t_end:.3f}s">'
               f'{final_open}{escape(text)}</tspan></text>')
    return out


def torus_frames(n=40, cols=46, rows=19):
    """donut.c-style spinning torus, pre-rendered as n ASCII frames."""
    lum = ".,-~:;=!*#$@"
    frames = []
    for f in range(n):
        A, B = 1.0 + f * 2 * math.pi / n, 0.5 + f * math.pi / n
        out = [[" "] * cols for _ in range(rows)]
        zb = [[0.0] * cols for _ in range(rows)]
        cA, sA, cB, sB = math.cos(A), math.sin(A), math.cos(B), math.sin(B)
        th = 0.0
        while th < 2 * math.pi:
            ct, st = math.cos(th), math.sin(th)
            ph = 0.0
            while ph < 2 * math.pi:
                cp, sp = math.cos(ph), math.sin(ph)
                cx, cy = 2 + ct, st
                x = cx * (cB * cp + sA * sB * sp) - cy * cA * sB
                y = cx * (sB * cp - sA * cB * sp) + cy * cA * cB
                z = 5 + cA * cx * sp + cy * sA
                ooz = 1 / z
                xp = int(cols / 2 + cols * 0.50 * ooz * x)
                yp = int(rows / 2 - rows * 0.86 * ooz * y)
                L = cp * ct * sB - cA * ct * sp - sA * st + cB * (cA * st - ct * sA * sp)
                if 0 <= xp < cols and 0 <= yp < rows and L > 0 and ooz > zb[yp][xp]:
                    zb[yp][xp] = ooz
                    out[yp][xp] = lum[min(len(lum) - 1, int(L * 8))]
                ph += 0.05
            th += 0.13
        frames.append(["".join(r).rstrip() for r in out])
    return frames


def render_portrait(p, c, x0, y0, col_w, boot, glow, PF, PCW, PLH):
    """ASCII portrait: glyph per pixel, coloured by brightness, scanned in, glitches now and then."""
    chars, levels = p["chars"], p["levels"]
    cols = max(len(r) for r in chars)
    x = x0 + (col_w - cols * PCW) / 2
    rows = len(chars)
    out = [f'<g class="art" font-size="{PF}px">', f'<g {glow}>']
    reveal = 1.4
    for r, (line, lv) in enumerate(zip(chars, levels)):
        parts, run, cur = [], "", None
        for ch, L in zip(line, lv):
            if L != cur and run:
                parts.append(f'<tspan fill="{c["portrait"][cur - 1]}">{escape(run)}</tspan>' if cur else escape(run))
                run = ""
            cur = L
            run += ch
        if run.strip():
            parts.append(f'<tspan fill="{c["portrait"][cur - 1]}">{escape(run)}</tspan>' if cur else "")
        d = round(boot + reveal * r / rows, 3)
        out.append(f'<text class="pop" style="animation-delay:{d}s" x="{x:.1f}" y="{y0 + r * PLH:.1f}">{"".join(parts)}</text>')
    out.append("</g>")
    # scan beam that "prints" the portrait
    out.append(f'<rect class="beam" x="{x - 6:.1f}" y="{y0 - 10}" width="{cols * PCW + 12:.1f}" height="2" '
               f'fill="{c["node_hot"]}" filter="url(#bloom)" style="animation-delay:{boot}s"/>')
    # glitch copies
    for g in ("g1", "g2"):
        body = "".join(f'<tspan x="{x:.1f}" y="{y0 + r * PLH:.1f}">{escape(l)}</tspan>' for r, l in enumerate(chars) if l.strip())
        out.append(f'<text class="{g}" font-weight="normal">{body}</text>')
    # caption
    cap_y = y0 + rows * PLH + 22
    cap = "M A T T H E W   M O O R E"
    cx = x0 + (col_w - len(cap) * 9.65) / 2
    out.append(f'<text class="label" font-size="16px" x="{cx:.1f}" y="{cap_y:.1f}" {glow}>{cap}</text>')
    for g in ("g1", "g2"):
        out.append(f'<text class="{g}" font-size="16px" x="{cx:.1f}" y="{cap_y:.1f}">{cap}</text>')
    out.append("</g>")
    return out


CHIP_TITLE = "[ MOORE :: EDGE  ·  NPU0  ·  int8  ·  <1W TDP ]"


def render_chip(c, x0, y0, body, W, boot, glow):
    """ASCII chip package around the info panel: pins, package, die border, live packets."""
    pins = list(range(7, W - 6, 4))
    L, R = 3, W - 4                                # package border columns
    DL, DR = 6, W - 7                              # die border columns

    def row(fill=" "):
        return [fill] * W

    rows = []
    r = row()
    for p in pins:
        r[p] = "|"
    rows.append(("pins", r))
    for corner in (".", "'"):
        r = row()
        r[L] = r[R] = corner
        for k in range(L + 1, R):
            r[k] = "-"
        for p in pins:
            r[p] = "+"
        rows.append(("pkg", r))
    pkg_top, pkg_bot = rows[1], rows[2][1]
    rows = [rows[0], pkg_top]

    def die_edge(corner, title=None):
        r = row()
        r[L] = r[R] = "|"
        r[DL] = r[DR] = corner
        for k in range(DL + 1, DR):
            r[k] = "-"
        for k in range(DL + 6, DR - 2, 9):
            r[k] = "o"
        if title:
            for k, ch in enumerate(title):
                r[DL + 3 + k] = ch
        return r

    rows.append(("die", die_edge(".", CHIP_TITLE)))
    for i in range(body):
        r = row()
        pin = i % 2 == 0
        r[:L + 1] = list("---+") if pin else list("   |")
        r[R:] = list("+---") if pin else list("|   ")
        r[DL] = r[DR] = "|"
        rows.append(("body", r))
    rows.append(("die", die_edge("'")))
    rows.append(("pkg", pkg_bot))
    rows.append(("pins", rows[0][1][:]))

    t_end = len(CHIP_TITLE) + DL + 3
    out = [f'<g class="art" style="animation-delay:{boot - 0.3:.2f}s">', f'<g {glow}>']
    for ri, (kind, r) in enumerate(rows):
        parts, run, rc = [], "", None

        def flush():
            nonlocal run, rc
            if run:
                parts.append(f'<tspan class="{rc}">{escape(run)}</tspan>')
            run, rc = "", None

        for k, ch in enumerate(r):
            if kind == "pins" or (kind == "body" and (k < L or k > R)):
                cls = "pin"
            elif k in (L, R) or kind == "pkg":
                cls = "frame"
            elif kind == "die" and DL + 3 <= k < t_end and ri == 2:
                cls = "label"
            else:
                cls = "mesh"
            if ch == "o" and kind == "die":
                flush()
                parts.append(f'<tspan class="node" style="animation-delay:{(k / 9) * 0.3 + ri * 0.05:.2f}s">o</tspan>')
                continue
            if cls != rc:
                flush()
                rc = cls
            run += ch
        flush()
        out.append(f'<text x="{x0:.1f}" y="{y0 + ri * LH:.1f}">{"".join(parts)}</text>')
    out.append("</g>")

    # glitch on the die title
    for g in ("g1", "g2"):
        out.append(f'<text class="{g}" x="{x0 + (DL + 3) * CW:.1f}" y="{y0 + 2 * LH:.1f}">{escape(CHIP_TITLE)}</text>')

    # data packets flowing into the package
    pk = []
    for ri, (kind, r) in enumerate(rows):
        if kind == "body" and r[0] == "-":
            yy = y0 + ri * LH - 5
            pk.append((x0, yy, "pkh"))
            pk.append((x0 + W * CW, yy, "pkhr"))
    for p in pins:
        xx = x0 + p * CW + CW / 2
        pk.append((xx, y0 - 14, "pkv"))
        pk.append((xx, y0 + (len(rows) - 1) * LH + 4, "pkvr"))
    out.append('<g filter="url(#bloom)">')
    for k, (px_, py_, cls) in enumerate(pk):
        out.append(f'<circle class="pk {cls}" style="animation-delay:{(k * 0.37) % 1.6:.2f}s" '
                   f'cx="{px_:.1f}" cy="{py_:.1f}" r="2.6"/>')
    out.append("</g></g>")
    return out


def heat_levels(cal):
    flat = sorted(v for w in cal for v in w if v)
    if not flat:
        return [0, 0, 0]
    q = lambda p: flat[min(len(flat) - 1, int(p * len(flat)))]
    return [q(.25), q(.5), q(.75)]


def render(theme, cfg, stats):
    c = THEMES[theme]
    art = (ROOT / "ascii.txt").read_text().rstrip("\n").splitlines()
    pfile = ROOT / "portrait.json"
    portrait = json.loads(pfile.read_text()) if cfg.get("art") == "portrait" and pfile.exists() else None
    info = build_lines(cfg, stats)
    art_w = max(len(a) for a in art) + 4
    PF, PCW, PLH = 10, 6.02, 9.6                   # portrait font, glyph width, line height

    pad, bar_h = 24, 34
    y0 = bar_h + pad + 14                          # prompt baseline
    # right side: the chip, with all the info printed on its die
    CHIP_W, HEAT_ROWS = WIDTH + 16, 5
    body_rows = len(info) + HEAT_ROWS
    chip_top = y0 + LH * 1.5                       # baseline of the top pin row
    info_top = chip_top + 3 * LH
    heat_top = info_top + len(info) * LH + 6       # contribution grid (on the die)
    cell, gap = 8, 2
    blocks_top = chip_top + (6 + body_rows) * LH + 8
    w = int((art_w + CHIP_W) * CW + 2 * pad)
    x_art = pad
    x_chip = pad + art_w * CW
    x_info = int(x_chip + 8 * CW)
    art_top = y0 + LH * 2.5                        # portrait
    if portrait:
        art_h = len(portrait["chars"]) * PLH + 34      # portrait + caption
    else:
        art_h = len(art) * LH + 4
    hud_top = art_top + art_h                      # npu monitor under the art
    hud_w = int((art_w - 4) * CW)
    TF, TLH, TCW = 11, 10, 6.6                     # torus font, line height, glyph width
    torus = torus_frames()
    torus_top = hud_top + LH * 4 + 14 + 26
    torus_bottom = torus_top + len(torus[0]) * TLH
    final_prompt = max(blocks_top + 2 * 18 + LH + 8, torus_bottom + LH + 10)
    h = int(final_prompt + LH + pad + 4)

    T0 = 0.12 * len(BOOT_LOG) + 0.5                # boot log, then clear screen
    TPER = 3.2                                     # torus rotation period (s)
    t_type = 0.06 * len(COMMAND)
    boot = T0 + 0.2 + t_type + 0.35                # neofetch output starts
    X = lambda col: x_art + col * CW
    Y = lambda row: art_top + row * LH

    # live command loop at the final prompt
    loop = cfg.get("terminal_loop", [])
    seg = 4.6
    P = max(len(loop), 1) * seg
    loop_css = ""
    if loop:
        f = 100 / len(loop)
        loop_css += (f"@keyframes cyc{{{{0%,{f - 0.01:.3f}%{{{{opacity:1}}}}{f:.3f}%,100%{{{{opacity:0}}}}}}}}\n"
                     f".cyc{{{{opacity:0;animation:cyc {P}s linear infinite}}}}\n")
        for i, (cmd, _) in enumerate(loop):
            L = len(cmd)
            pt = 0.065 * L / P * 100
            po = pt + 0.25 / P * 100
            loop_css += (f"@keyframes ty{i}{{{{0%{{{{transform:translateX(0);animation-timing-function:steps({L})}}}}"
                         f"{pt:.3f}%,100%{{{{transform:translateX({L * CW:.1f}px)}}}}}}}}\n"
                         f".ty{i}{{{{animation:ty{i} {P}s linear infinite}}}}\n"
                         f"@keyframes ou{i}{{{{0%,{po:.3f}%{{{{opacity:0}}}}{po + 0.01:.3f}%,100%{{{{opacity:1}}}}}}}}\n"
                         f".ou{i}{{{{opacity:0;animation:ou{i} {P}s linear infinite}}}}\n")
    loop_css = loop_css.replace("{{", "{").replace("}}", "}")

    css = f"""
text,tspan{{white-space:pre}}
.t{{fill:{c['text']}}} .key{{fill:{c['key']}}} .value{{fill:{c['value']}}} .cc{{fill:{c['dots']}}}
.addColor{{fill:{c['add']}}} .delColor{{fill:{c['dele']}}} .acc{{fill:{c['accent']}}} .pr{{fill:{c['prompt']}}}
.pin{{fill:{c['pin']}}} .frame{{fill:{c['frame']}}} .mesh{{fill:{c['mesh']}}} .label{{fill:{c['label']};font-weight:bold}}
.node{{fill:{c['node']};animation:pulse 2.4s ease-in-out infinite}}
@keyframes pulse{{0%,100%{{fill:{c['node']}}}45%,55%{{fill:{c['node_hot']}}}}}
.ln{{opacity:0;animation:in .25s ease-out forwards}}
@keyframes in{{from{{opacity:0;transform:translateX(-6px)}}to{{opacity:1;transform:none}}}}
.pop{{opacity:0;animation:pop .01s linear forwards}}
@keyframes pop{{to{{opacity:1}}}}
.bootlog{{animation:gone 0s {T0}s forwards}}
.after{{opacity:0;animation:pop .01s linear {T0}s forwards}}
.art{{opacity:0;animation:in .6s ease-out {boot}s forwards}}
.typer{{animation:type {t_type}s steps({len(COMMAND)}) {T0 + 0.2}s forwards, gone 0s {boot}s forwards}}
@keyframes type{{to{{transform:translateX({len(COMMAND) * CW:.1f}px)}}}}
.cur{{animation:blink 1s steps(1) infinite}} .cur1{{animation:blink .5s steps(1) infinite}}
@keyframes blink{{50%{{opacity:0}}}}
@keyframes gone{{to{{visibility:hidden}}}}
.scan{{animation:scan 7s linear {boot + 1}s infinite;opacity:0}}
@keyframes scan{{0%{{transform:translateY(0);opacity:0}}5%,95%{{opacity:.10}}100%{{transform:translateY({h}px);opacity:0}}}}
.pk{{fill:{c['node_hot']};opacity:0}}
.pkh{{animation:pkh 1.6s ease-in infinite}} .pkhr{{animation:pkhr 1.6s ease-in infinite}}
.pkv{{animation:pkv 1.6s ease-in infinite}} .pkvr{{animation:pkvr 1.6s ease-in infinite}}
@keyframes pkh{{0%{{opacity:0;transform:translateX(0)}}15%{{opacity:1}}85%{{opacity:1}}100%{{opacity:0;transform:translateX({4 * CW:.1f}px)}}}}
@keyframes pkhr{{0%{{opacity:0;transform:translateX(0)}}15%{{opacity:1}}85%{{opacity:1}}100%{{opacity:0;transform:translateX({-4 * CW:.1f}px)}}}}
@keyframes pkv{{0%{{opacity:0;transform:translateY(0)}}15%{{opacity:1}}85%{{opacity:1}}100%{{opacity:0;transform:translateY({LH * 1.2:.0f}px)}}}}
@keyframes pkvr{{0%{{opacity:0;transform:translateY(0)}}15%{{opacity:1}}85%{{opacity:1}}100%{{opacity:0;transform:translateY({-LH * 1.2:.0f}px)}}}}
.g1,.g2{{opacity:0;font-weight:bold}}
.g1{{fill:#00e5ff;animation:gl1 4.3s steps(1) infinite}} .g2{{fill:#ff2bd6;animation:gl2 4.3s steps(1) infinite}}
@keyframes gl1{{0%,88%,100%{{opacity:0;transform:none}}89%{{opacity:.9;transform:translate(-3px,1px)}}91%{{opacity:.9;transform:translate(2px,-1px)}}93%{{opacity:0}}96%{{opacity:.8;transform:translate(-2px,0)}}97%{{opacity:0}}}}
@keyframes gl2{{0%,88%,100%{{opacity:0;transform:none}}89%{{opacity:.9;transform:translate(3px,-1px)}}91%{{opacity:.9;transform:translate(-2px,1px)}}93%{{opacity:0}}96%{{opacity:.8;transform:translate(2px,1px)}}97%{{opacity:0}}}}
.wave{{animation:wave 3s linear infinite}}
@keyframes wave{{to{{transform:translateX(-120px)}}}}
.m1{{animation:m1 2.7s ease-in-out infinite alternate}} .m2{{animation:m2 3.9s ease-in-out infinite alternate}} .m3{{animation:m3 5.3s ease-in-out infinite alternate}}
@keyframes m1{{from{{transform:scaleX(.55)}}to{{transform:scaleX(.92)}}}}
@keyframes m2{{from{{transform:scaleX(.30)}}to{{transform:scaleX(.62)}}}}
@keyframes m3{{from{{transform:scaleX(.40)}}to{{transform:scaleX(.58)}}}}
.drop{{animation-name:fall;animation-timing-function:linear;animation-iteration-count:infinite}}
@keyframes fall{{from{{transform:translateY(-460px)}}to{{transform:translateY({h}px)}}}}
.rain{{opacity:{c['rain_op']};animation:rainfade 2.5s ease-out forwards}}
@keyframes rainfade{{0%{{opacity:{c['rain_boot']}}}60%{{opacity:{c['rain_boot']}}}100%{{opacity:{c['rain_op']}}}}}
.sc{{visibility:hidden;animation:show 0s forwards,gone 0s forwards}}
@keyframes show{{to{{visibility:visible}}}}
.tf{{opacity:0;animation:tf {TPER}s linear infinite}}
@keyframes tf{{0%,{100 / len(torus):.3f}%{{opacity:1}}{100 / len(torus) + 0.001:.3f}%,100%{{opacity:0}}}}
.flick{{animation:flick 6s steps(1) infinite}}
@keyframes flick{{0%,100%{{opacity:1}}31%{{opacity:.93}}32%{{opacity:1}}67%{{opacity:.96}}68%{{opacity:1}}84%{{opacity:.94}}85%{{opacity:1}}}}
{loop_css}
.beam{{opacity:0;animation:beam 1.5s linear forwards}}
@keyframes beam{{0%{{opacity:1;transform:translateY(0)}}93%{{opacity:1}}100%{{opacity:0;transform:translateY({(len(portrait["chars"]) * PLH + 10) if portrait else 0:.0f}px)}}}}
.hs{{animation:hsweep 4s linear {boot + 1.5}s infinite;opacity:0}}
@keyframes hsweep{{0%{{opacity:0;transform:translateX(0)}}10%,90%{{opacity:.35}}100%{{opacity:0;transform:translateX({53 * (cell + gap)}px)}}}}
"""
    glow = 'filter="url(#glow)"' if c["glow"] else ""
    o = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
         f'font-family="ConsolasFallback,Consolas,\'DejaVu Sans Mono\',Menlo,monospace" font-size="{FONT}px">',
         "<defs>",
         f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c["bg1"]}"/>'
         f'<stop offset="1" stop-color="{c["bg2"]}"/></linearGradient>',
         f'<linearGradient id="edge" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["border"]}"/>'
         f'<stop offset=".5" stop-color="{c["accent"]}"/><stop offset="1" stop-color="{c["key"]}"/></linearGradient>',
         # shimmering gradient for the name
         f'<linearGradient id="shine" x1="0" y1="0" x2="1" y2="0" gradientUnits="objectBoundingBox" spreadMethod="reflect">'
         f'<stop offset="0" stop-color="{c["accent"]}"/><stop offset=".5" stop-color="{c["key"]}"/>'
         f'<stop offset="1" stop-color="{c["accent"]}"/>'
         f'<animateTransform attributeName="gradientTransform" type="translate" from="-1 0" to="1 0" dur="3s" repeatCount="indefinite"/>'
         f'</linearGradient>',
         f'<linearGradient id="scanG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["scan"]}" stop-opacity="0"/>'
         f'<stop offset="1" stop-color="{c["scan"]}"/></linearGradient>',
         f'<linearGradient id="meter" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["key"]}"/>'
         f'<stop offset="1" stop-color="{c["accent"]}"/></linearGradient>',
         '<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/>'
         '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
         '<filter id="bloom" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.5" result="b"/>'
         '<feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
         f'<pattern id="lines" width="4" height="3" patternUnits="userSpaceOnUse"><rect width="4" height="1" '
         f'fill="#000" fill-opacity="{".22" if c["glow"] else ".035"}"/></pattern>',
         f'<radialGradient id="vig" cx=".5" cy=".5" r=".75"><stop offset=".6" stop-color="#000" stop-opacity="0"/>'
         f'<stop offset="1" stop-color="#000" stop-opacity="{".45" if c["glow"] else ".08"}"/></radialGradient>',
         f'<clipPath id="win"><rect width="{w}" height="{h}" rx="14"/></clipPath>',
         f'<clipPath id="hudclip"><rect x="{x_art + 70}" y="{hud_top}" width="{hud_w - 70}" height="30"/></clipPath>',
         "</defs>",
         f"<style>{css}</style>",
         '<g clip-path="url(#win)">',
         f'<rect width="{w}" height="{h}" fill="url(#bg)"/>',
         '<g class="flick">',
         *matrix_rain(w, h, c, random.Random(1337)),
         f'<rect width="{w}" height="{bar_h}" fill="{c["bar"]}"/>',
         f'<rect y="{bar_h - 1}" width="{w}" height="1.5" fill="url(#edge)"/>',
         '<circle cx="22" cy="17" r="6" fill="#ff5f57"/><circle cx="42" cy="17" r="6" fill="#febc2e"/>'
         '<circle cx="62" cy="17" r="6" fill="#28c840"/>',
         f'<text x="{w / 2}" y="22" text-anchor="middle" font-size="13px" style="fill:{c["pin"]}">'
         f'MattyIceMatrix — matthew@moore: ~ — zsh — {w // 10}×{h // 20}</text>',
         f'<rect class="scan" x="0" y="-60" width="{w}" height="60" fill="url(#scanG)"/>']

    # ---- 1. boot log (then the screen clears)
    o.append('<g class="bootlog">')
    for i, (tag, msg) in enumerate(BOOT_LOG):
        if not tag:
            continue
        d = round(0.12 * i + 0.15, 2)
        tcls = "pr" if "OK" in tag else ("cc" if tag.startswith("[ ") else "t")
        o.append(f'<text class="pop" style="animation-delay:{d}s" x="{pad}" y="{y0 + i * LH}">'
                 f'<tspan class="{tcls}" font-weight="bold">{escape(tag)}</tspan><tspan class="t">{escape(msg)}</tspan></text>')
    o.append('</g>')

    # ---- 2. prompt + typed command
    pw = len("matthew@moore") * CW
    cx = pad + pw + 4 * CW
    o.append(f'<g class="after"><text x="{pad}" y="{y0}"><tspan class="pr" font-weight="bold">matthew@moore</tspan>'
             f'<tspan class="t">:</tspan><tspan class="key">~</tspan><tspan class="t">$ </tspan>'
             f'<tspan class="t">{COMMAND}</tspan></text>'
             f'<g class="typer"><rect x="{cx}" y="{y0 - 15}" width="{len(COMMAND) * CW + 2}" height="20" '
             f'fill="{c["bg1"]}"/><rect class="cur1" x="{cx}" y="{y0 - 14}" width="{CW:.1f}" height="18" '
             f'fill="{c["key"]}"/></g></g>')

    if portrait:
        o.extend(render_portrait(portrait, c, x_art, art_top, art_w * CW - 4 * CW, boot, glow, PF, PCW, PLH))
    else:
        # ---- 3. chip art + data packets + glitch label
        o.append(f'<g class="art">')
        o.append(f'<g {glow}>')
        for i, row in enumerate(art_spans(art)):
            o.append(f'<text x="{x_art}" y="{Y(i)}">{row}</text>')
        o.append("</g>")
        pk = []
        for r, line in enumerate(art):
            if line.startswith("  ---+"):
                pk.append((X(2), Y(r) - 5, "pkh"))
            if line.rstrip().endswith("+---"):
                pk.append((X(len(line.rstrip())), Y(r) - 5, "pkhr"))
        for col, ch in enumerate(art[0]):
            if ch == "|":
                pk.append((X(col) + CW / 2, Y(0) - 14, "pkv"))
                pk.append((X(col) + CW / 2, Y(len(art) - 1) + 4, "pkvr"))
        o.append(f'<g filter="url(#bloom)">')
        for k, (px_, py_, cls) in enumerate(pk):
            o.append(f'<circle class="pk {cls}" style="animation-delay:{(k * 0.37) % 1.6:.2f}s" cx="{px_:.1f}" cy="{py_:.1f}" r="2.6"/>')
        o.append("</g>")
        for r, line in enumerate(art):                  # glitch copies of the label rows
            if "M O O R E" in line or "NPU" in line:
                start = line.index("M O O R E") if "M O O R E" in line else line.index("[ NPU")
                txt = line[start:].split("|")[0].rstrip()
                for g in ("g1", "g2"):
                    o.append(f'<text class="{g}" x="{X(start):.1f}" y="{Y(r)}">{escape(txt)}</text>')
        o.append("</g>")


    # ---- 4. NPU monitor under the chip
    hd = round(boot + 0.4, 2)
    o.append(f'<g class="ln" style="animation-delay:{hd}s">')
    o.append(f'<rect x="{x_art}" y="{hud_top - 2}" width="{hud_w}" height="{LH * 4 + 14}" rx="6" fill="none" '
             f'stroke="{c["frame"]}" stroke-opacity=".45" stroke-dasharray="3 3"/>')
    o.append(f'<text x="{x_art + 8}" y="{hud_top + 19}" font-size="12px"><tspan class="acc" font-weight="bold">npu0</tspan>'
             f'<tspan class="cc"> sig</tspan></text>')
    wave_pts = " ".join(f"{x},{hud_top + 15 + 9 * math.sin(x / 120 * 2 * 3.14159) * (0.6 + 0.4 * math.sin(x / 40)):.1f}"
                        for x in range(0, hud_w + 240, 4))
    o.append(f'<g clip-path="url(#hudclip)"><g transform="translate({x_art + 70},0)"><polyline class="wave" points="{wave_pts}" '
             f'fill="none" stroke="{c["key"]}" stroke-width="1.6" {glow}/></g></g>')
    for k, (lab, cls) in enumerate((("util", "m1"), ("mem ", "m2"), ("temp", "m3"))):
        yy = hud_top + 34 + k * 17
        bx, bwid = x_art + 70, hud_w - 82
        o.append(f'<text x="{x_art + 8}" y="{yy + 9}" font-size="12px" class="cc" style="fill:{c["pin"]}">{lab}</text>')
        o.append(f'<rect x="{bx}" y="{yy}" width="{bwid}" height="9" rx="2" fill="{c["dots"]}" fill-opacity=".5"/>')
        o.append(f'<g transform="translate({bx},{yy})"><rect class="{cls}" width="{bwid}" height="9" rx="2" '
                 f'fill="url(#meter)" style="transform-origin:0 0"/></g>')
    o.append("</g>")

    # ---- 4b. the chip on the right: package, pins, die, packets
    o.extend(render_chip(c, x_chip, chip_top, body_rows, CHIP_W, boot, glow))

    # ---- 5. info lines boot in one by one; name + section headers decode Matrix-style
    rng = random.Random(42)
    for i, parts in enumerate(info):
        if not parts:
            continue
        d = round(boot + 0.25 + i * 0.055, 3)
        y = info_top + i * LH
        if i == 0:
            title, xoff = cfg["header"], 0
            final_open = '<tspan fill="url(#shine)" font-weight="bold">'
            parts = [f'<tspan fill-opacity="0">{escape(title)}</tspan>'] + parts[1:]
        elif len(parts) == 3 and 'class="acc"' in parts[1]:
            title = parts[1].split(">", 1)[1].rsplit("<", 1)[0]
            xoff = 2
            final_open = '<tspan class="acc" font-weight="bold">'
            parts = [parts[0], f'<tspan fill-opacity="0">{title}</tspan>', parts[2]]
        else:
            title = None
        o.append(f'<text class="ln t" style="animation-delay:{d}s" x="{x_info}" y="{y}">{"".join(parts)}</text>')
        if title:
            o.extend(scramble(title.replace("&amp;", "&"), x_info + xoff * CW, y, d, final_open, rng))

    # ---- 6. contribution heatmap (real data from the daily Action)
    d = round(boot + 0.35 + len(info) * 0.055, 3)
    cal = stats.get("calendar") or []
    lv = heat_levels(cal)
    ramp = [c["dots"], c["mesh"], c["key"], c["accent"], c["node_hot"]]
    o.append(f'<g class="ln" style="animation-delay:{d}s">')
    weeks = cal[-53:] if cal else [[None] * 7] * 53
    for wi, wk in enumerate(weeks):
        for di, v in enumerate(wk):
            if v is None or v == 0:
                col, op = ramp[0], ".55"
            else:
                col, op = ramp[1 + sum(v > t for t in lv)], "1"
            o.append(f'<rect x="{x_info + wi * (cell + gap)}" y="{heat_top + di * (cell + gap)}" width="{cell}" '
                     f'height="{cell}" rx="1.5" fill="{col}" fill-opacity="{op}"/>')
    o.append(f'<rect class="hs" x="{x_info - 4}" y="{heat_top - 2}" width="6" height="{7 * (cell + gap) + 2}" '
             f'fill="{c["key"]}" filter="url(#bloom)"/>')
    total = sum(sum(wk) for wk in cal) if cal else None
    note = f"{total:,} contributions in the last year" if total is not None else "contribution grid syncs on first run"
    o.append(f'<text x="{x_info}" y="{heat_top + 7 * (cell + gap) + 14}" font-size="12px" class="cc" '
             f'style="fill:{c["pin"]}">{note}</text>')
    o.append("</g>")

    # ---- 7. neofetch colour blocks
    d2 = round(d + 0.2, 3)
    o.append(f'<g class="ln" style="animation-delay:{d2}s">')
    bw = CW * 3
    for k, col in enumerate(PALETTE):
        o.append(f'<rect x="{x_info + (k % 8) * bw:.1f}" y="{blocks_top + (k // 8) * 18}" '
                 f'width="{bw:.1f}" height="18" fill="{col}"/>')
    o.append("</g>")

    # ---- 8. spinning torus: the "live model" on npu0
    tw = max(len(r) for fr in torus for r in fr) * TCW
    tx = x_art + (hud_w - tw) / 2
    o.append(f'<g class="ln" style="animation-delay:{hd + 0.2:.2f}s">')
    o.append(f'<text x="{x_art + 8}" y="{torus_top - 10}" font-size="12px"><tspan class="acc" font-weight="bold">'
             f'model.run</tspan><tspan style="fill:{c["pin"]}"> · npu0 · live</tspan></text>')
    o.append(f'<g font-size="{TF}px" fill="url(#meter)" {glow}>')
    for k, fr in enumerate(torus):
        rows_ = "".join(f'<tspan x="{tx:.1f}" y="{torus_top + 10 + r * TLH}">{escape(line)}</tspan>'
                        for r, line in enumerate(fr) if line)
        o.append(f'<text class="tf" style="animation-delay:{k * TPER / len(torus):.3f}s">{rows_}</text>')
    o.append("</g></g>")

    # ---- 9. final prompt that never stops working
    d3 = d2 + 0.3
    prompt = (f'<tspan class="pr" font-weight="bold">matthew@moore</tspan><tspan class="t">:</tspan>'
              f'<tspan class="key">~</tspan><tspan class="t">$ </tspan>')
    o.append(f'<g class="ln" style="animation-delay:{d3}s"><text x="{pad}" y="{final_prompt}">{prompt}</text></g>')
    if not loop:
        o.append(f'<rect class="cur" x="{cx:.1f}" y="{final_prompt - 14}" width="{CW:.1f}" height="18" fill="{c["key"]}"/>')
    for i, (cmd, out) in enumerate(loop):
        start = round(d3 + 0.4 + i * seg, 2)
        L = len(cmd)
        o.append(f'<clipPath id="tc{theme}{i}"><rect class="ty{i}" style="animation-delay:{start}s" '
                 f'x="{cx - L * CW:.1f}" y="{final_prompt - 16}" width="{L * CW:.1f}" height="22"/></clipPath>')
        o.append(f'<g class="cyc" style="animation-delay:{start}s">')
        o.append(f'<text x="{cx:.1f}" y="{final_prompt}" class="t" clip-path="url(#tc{theme}{i})">{escape(cmd)}</text>')
        o.append(f'<g class="ty{i}" style="animation-delay:{start}s"><rect class="cur" x="{cx:.1f}" '
                 f'y="{final_prompt - 14}" width="{CW:.1f}" height="18" fill="{c["key"]}"/></g>')
        o.append(f'<text class="ou{i}" style="animation-delay:{start}s" x="{pad}" y="{final_prompt + LH}">'
                 f'<tspan class="acc">&gt; </tspan><tspan class="value">{escape(out)}</tspan></text>')
        o.append("</g>")

    o.append("</g>")   # end flicker group
    # CRT finish
    o.append(f'<rect width="{w}" height="{h}" fill="url(#lines)" pointer-events="none"/>')
    o.append(f'<rect width="{w}" height="{h}" fill="url(#vig)" pointer-events="none"/>')
    o.append(f'<rect width="{w}" height="{h}" rx="14" fill="none" stroke="url(#edge)" stroke-width="2"/>')
    o.append("</g></svg>")
    (ROOT / f"{theme}_mode.svg").write_text("\n".join(o) + "\n")


def main():
    cfg = json.loads((ROOT / "profile.json").read_text())
    cache = ROOT / "stats.json"
    stats = json.loads(cache.read_text()) if cache.exists() else {}
    token = os.environ.get("GH_TOKEN")
    if token:
        try:
            stats = fetch_stats(cfg["login"], token)
            cache.write_text(json.dumps(stats, indent=2) + "\n")
            print("stats:", stats)
        except Exception as e:  # keep last good card, but fail loud
            print(f"ERROR fetching stats: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("GH_TOKEN not set - rendering from cached stats.json")
    for t in THEMES:
        render(t, cfg, stats)
    print("wrote dark_mode.svg, light_mode.svg")


if __name__ == "__main__":
    main()

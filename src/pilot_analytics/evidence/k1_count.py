"""Daily K1 evidence count (card C-03, task T-CP-16, requirement CP-ACCESS-003).

K1 is the gate criterion "reachable EVSEs on the Istanbul-Bodrum corridor across all channels":
at least 120 EVSEs, at least 45 of them DC (150 kW or more preferred). K1-H is the part reached
through Hubject (ZES). Both come from `07-go-no-go.md`.

Inputs
  --index     corridor index written by EV_PNC_telemetry `corridor-index` (card C-01)
  --channels  CSV of channel evidence: evse_uid, channel, status, hub, evidence_ref, evidence_date

Rules
  * An EVSE counts toward K1 only if the index says `k1_evidence` (user-listed stations never do)
    and at least one channel row for it has status `confirmed`.
  * An EVSE reachable over several channels counts once in the K1 total and once in each channel.
  * Channel rows with status `offered` or `claimed` are reported as potential, never as evidence.
  * Everything that does not count is listed with the reason, so a low number can be explained.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

CHANNELS = ("HUB", "BILATERAL_OCPI", "GUEST")  # same values as the ocpi-model Channel enum
HUBS = ("HUBJECT", "GIREVE", "E_CLEARING")
STATUSES = ("confirmed", "offered", "claimed")
FAMILIES = ("M", "A1", "A2", "A3", "A4")
POWER_CLASSES = ("AC", "DC<150", "DC>=150", "unknown")

# Gate values, from roaming-hubs/deliverables/07-go-no-go.md (K1, K1-H).
K1_MIN_EVSE = 120
K1_MIN_DC = 45
K1H_PROPOSED_SHARE = 0.20  # a proposal; the threshold is open (card G-01)
DC_FAST_KW = 150.0


class InputError(ValueError):
    """Bad input data; the message says which file, row and field."""


@dataclass(frozen=True)
class ChannelRow:
    evse_uid: str
    channel: str
    status: str
    hub: str
    evidence_ref: str
    evidence_date: str


@dataclass
class Report:
    as_of: str
    geometry_version: str
    geometry_quality: str
    totals: dict = field(default_factory=dict)
    by_channel: dict = field(default_factory=dict)
    by_family: dict = field(default_factory=dict)
    by_power_class: dict = field(default_factory=dict)
    k1h: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)
    potential: dict = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "geometry": {"version": self.geometry_version, "quality": self.geometry_quality},
            "totals": self.totals,
            "by_channel": self.by_channel,
            "by_family": self.by_family,
            "by_power_class": self.by_power_class,
            "k1h": self.k1h,
            "gates": self.gates,
            "potential": self.potential,
            "excluded": self.excluded,
            "warnings": self.warnings,
        }


def power_class(entry: dict) -> str:
    kw = entry.get("max_power_kw") or 0
    ptype = (entry.get("power_type") or "").upper()
    if ptype == "AC":
        return "AC"
    if ptype == "DC" and kw >= DC_FAST_KW:
        return "DC>=150"
    if ptype == "DC" and kw > 0:
        return "DC<150"
    return "unknown"


def read_channels(path: Path) -> list[ChannelRow]:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = {"evse_uid", "channel", "status"} - set(reader.fieldnames or [])
        if missing:
            raise InputError(f"{path}: missing columns {sorted(missing)}")
        for n, raw in enumerate(reader, start=2):
            channel = (raw.get("channel") or "").strip().upper()
            status = (raw.get("status") or "").strip().lower()
            hub = (raw.get("hub") or "").strip().upper()
            uid = (raw.get("evse_uid") or "").strip()
            if not uid:
                raise InputError(f"{path}:{n}: empty evse_uid")
            if channel not in CHANNELS:
                raise InputError(f"{path}:{n}: channel {channel!r} is not one of {CHANNELS}")
            if status not in STATUSES:
                raise InputError(f"{path}:{n}: status {status!r} is not one of {STATUSES}")
            if channel == "HUB" and hub not in HUBS:
                raise InputError(f"{path}:{n}: a HUB row needs hub in {HUBS}, got {hub!r}")
            if channel != "HUB" and hub:
                raise InputError(f"{path}:{n}: hub is only for HUB rows")
            if status == "confirmed" and not (raw.get("evidence_ref") or "").strip():
                raise InputError(f"{path}:{n}: a confirmed row needs evidence_ref (offer, contract or feed id)")
            rows.append(
                ChannelRow(uid, channel, status, hub, (raw.get("evidence_ref") or "").strip(), (raw.get("evidence_date") or "").strip())
            )
    return rows


def build_report(index: dict, rows: list[ChannelRow], as_of: dt.date, k1h_min_share: float | None = None) -> Report:
    entries = {e["evse_uid"]: e for e in index["entries"]}
    rep = Report(as_of.isoformat(), index.get("geometry_version", "?"), index.get("geometry_quality", "?"))
    if rep.geometry_quality != "routed":
        rep.warnings.append(
            f"Corridor geometry {rep.geometry_version} is '{rep.geometry_quality}': which EVSEs are 'on the corridor' is not reliable. "
            "Do not use this count for the gate until a routed geometry is published."
        )

    confirmed: dict[str, set[tuple[str, str]]] = defaultdict(set)  # uid -> {(channel, hub)}
    potential_rows: list[ChannelRow] = []
    orphans = sorted({r.evse_uid for r in rows if r.evse_uid not in entries})
    blocked_user_listed = set()
    for r in rows:
        e = entries.get(r.evse_uid)
        if e is None:
            continue
        if r.status != "confirmed":
            potential_rows.append(r)
            continue
        if not e.get("k1_evidence", False):
            blocked_user_listed.add(r.evse_uid)
            continue
        confirmed[r.evse_uid].add((r.channel, r.hub))

    counted = sorted(confirmed)
    classes = {u: power_class(entries[u]) for u in counted}
    dc = [u for u in counted if classes[u].startswith("DC")]
    dc_fast = [u for u in counted if classes[u] == "DC>=150"]

    rep.totals = {
        "k1_evse": len(counted),
        "k1_dc_evse": len(dc),
        "k1_dc_150_plus_evse": len(dc_fast),
        "index_entries": len(entries),
        "index_entries_with_k1_evidence": sum(1 for e in entries.values() if e.get("k1_evidence")),
    }

    by_channel = {c: {"evse": 0, "dc_evse": 0, "dc_150_plus_evse": 0} for c in CHANNELS}
    hub_detail = {h: {"evse": 0, "dc_evse": 0, "dc_150_plus_evse": 0} for h in HUBS}
    for u in counted:
        seen_channels, seen_hubs = set(), set()
        for channel, hub in confirmed[u]:
            seen_channels.add(channel)
            if hub:
                seen_hubs.add(hub)
        for bucket, keys in ((by_channel, seen_channels), (hub_detail, seen_hubs)):
            for k in keys:
                bucket[k]["evse"] += 1
                bucket[k]["dc_evse"] += classes[u].startswith("DC")
                bucket[k]["dc_150_plus_evse"] += classes[u] == "DC>=150"
    rep.by_channel = {**by_channel, "HUB_detail": hub_detail}

    fam = {f: {"evse": 0, "dc_evse": 0, "dc_150_plus_evse": 0} for f in FAMILIES}
    for u in counted:
        for f in entries[u].get("families", []):
            fam[f]["evse"] += 1
            fam[f]["dc_evse"] += classes[u].startswith("DC")
            fam[f]["dc_150_plus_evse"] += classes[u] == "DC>=150"
    rep.by_family = fam
    by_class = Counter(classes.values())
    rep.by_power_class = {c: by_class[c] for c in POWER_CLASSES}

    hubject = hub_detail["HUBJECT"]["evse"]
    share = (hubject / len(counted)) if counted else None
    rep.k1h = {
        "hubject_evse": hubject,
        "share_of_k1": None if share is None else round(share, 4),
        "threshold_share": k1h_min_share,
        "threshold_status": "set" if k1h_min_share is not None else "open (card G-01); proposal is 20% of K1",
        "proposed_share": K1H_PROPOSED_SHARE,
        "meets_proposal": None if share is None else share >= K1H_PROPOSED_SHARE,
        "meets_threshold": None if (share is None or k1h_min_share is None) else share >= k1h_min_share,
    }

    rep.gates = {
        "K1": {
            "criterion": f">= {K1_MIN_EVSE} EVSE and >= {K1_MIN_DC} DC (>= 150 kW preferred)",
            "evse": len(counted),
            "dc_evse": len(dc),
            "status": "PASS" if len(counted) >= K1_MIN_EVSE and len(dc) >= K1_MIN_DC else "FAIL",
        },
        "K1-H": {
            "criterion": "Hubject-reached share of K1 at or above the threshold",
            "status": "OPEN" if k1h_min_share is None else ("PASS" if rep.k1h["meets_threshold"] else "FAIL"),
        },
    }

    pot = defaultdict(set)
    for r in potential_rows:
        pot[(r.channel, r.status)].add(r.evse_uid)
    rep.potential = {f"{c}/{s}": len(v) for (c, s), v in sorted(pot.items())}

    in_index_no_channel = sorted(u for u, e in entries.items() if u not in confirmed and e.get("k1_evidence"))
    rep.excluded = {
        "user_listed_with_confirmed_channel": sorted(blocked_user_listed),
        "channel_rows_for_unknown_evse": orphans,
        "index_evse_without_confirmed_channel": len(in_index_no_channel),
    }
    if orphans:
        rep.warnings.append(f"{len(orphans)} channel row(s) refer to EVSEs missing from the corridor index (outside the corridor, or an uid mismatch).")
    return rep


def render_markdown(rep: Report) -> str:
    d = rep.to_dict()
    g = d["gates"]
    out = [f"# K1 evidence count, {d['as_of']}", ""]
    out.append(
        f"**K1 {g['K1']['status']}**: {g['K1']['evse']} confirmed EVSE, {g['K1']['dc_evse']} of them DC "
        f"(gate: {g['K1']['criterion']}). **K1-H {g['K1-H']['status']}**: "
        f"{d['k1h']['hubject_evse']} via Hubject, share {fmt_share(d['k1h']['share_of_k1'])} "
        f"(threshold {d['k1h']['threshold_status']})."
    )
    out.append("")
    for w in d["warnings"]:
        out.append(f"> **Warning.** {w}")
        out.append("")
    out += ["## By channel (confirmed only)", "", "| Channel | EVSE | DC | DC >= 150 kW |", "|---|---:|---:|---:|"]
    for c in CHANNELS:
        b = d["by_channel"][c]
        out.append(f"| {c} | {b['evse']} | {b['dc_evse']} | {b['dc_150_plus_evse']} |")
    for h, b in d["by_channel"]["HUB_detail"].items():
        out.append(f"| HUB / {h} | {b['evse']} | {b['dc_evse']} | {b['dc_150_plus_evse']} |")
    out += ["", "An EVSE reachable over two channels appears in both rows and once in the K1 total.", ""]
    out += ["## By family", "", "| Family | EVSE | DC | DC >= 150 kW |", "|---|---:|---:|---:|"]
    for f in FAMILIES:
        b = d["by_family"][f]
        out.append(f"| {f} | {b['evse']} | {b['dc_evse']} | {b['dc_150_plus_evse']} |")
    out += ["", "A station near two families is counted in both rows.", ""]
    out += ["## By power class", "", "| Class | EVSE |", "|---|---:|"]
    out += [f"| {c} | {n} |" for c, n in d["by_power_class"].items()]
    out += ["", "## Not evidence", ""]
    if d["potential"]:
        out += [f"- Potential only, not counted: " + ", ".join(f"{k}: {v}" for k, v in d["potential"].items())]
    else:
        out.append("- No offered or claimed channels recorded.")
    ex = d["excluded"]
    out.append(f"- Corridor EVSEs with no confirmed channel: {ex['index_evse_without_confirmed_channel']}")
    if ex["user_listed_with_confirmed_channel"]:
        out.append(f"- User-listed (K) stations with a confirmed channel, withheld: {', '.join(ex['user_listed_with_confirmed_channel'])}")
    if ex["channel_rows_for_unknown_evse"]:
        out.append(f"- Channel rows for EVSEs not in the index: {', '.join(ex['channel_rows_for_unknown_evse'])}")
    out += ["", f"Geometry {d['geometry']['version']} ({d['geometry']['quality']}).", ""]
    return "\n".join(out)


def fmt_share(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--channels", type=Path, required=True)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=None, help="report date, default today (UTC)")
    ap.add_argument("--k1h-min-share", type=float, default=None, help="K1-H threshold as a fraction; omit while it is open")
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--md-out", type=Path)
    args = ap.parse_args(argv)
    try:
        index = json.loads(args.index.read_text(encoding="utf-8"))
        rows = read_channels(args.channels)
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"k1-count: {exc}", file=sys.stderr)
        return 2
    as_of = args.as_of or dt.datetime.now(dt.UTC).date()
    rep = build_report(index, rows, as_of, args.k1h_min_share)
    md = render_markdown(rep)
    if args.json_out:
        args.json_out.write_text(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.md_out:
        args.md_out.write_text(md, encoding="utf-8")
    if not args.json_out and not args.md_out:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

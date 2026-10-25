import datetime as dt
import json

import pytest

from pilot_analytics.evidence import k1_count as k1

AS_OF = dt.date(2026, 11, 3)


def entry(uid, kw=180, ptype="DC", families=("M",), k1_ok=True):
    return {"evse_uid": uid, "max_power_kw": kw, "power_type": ptype, "families": list(families), "k1_evidence": k1_ok, "source": "ocpi_feed"}


def index(*entries, quality="routed"):
    return {"geometry_version": "t", "geometry_quality": quality, "entries": list(entries)}


def row(uid, channel="BILATERAL_OCPI", status="confirmed", hub=""):
    return k1.ChannelRow(uid, channel, status, hub, "ref", "2026-11-01")


def test_counts_each_evse_once_in_total_and_once_per_channel():
    rep = k1.build_report(
        index(entry("A"), entry("B", kw=120)),
        [row("A", "HUB", hub="HUBJECT"), row("A"), row("A", "GUEST"), row("B", "GUEST")],
        AS_OF,
    )
    assert rep.totals["k1_evse"] == 2
    assert rep.by_channel["HUB"]["evse"] == 1 and rep.by_channel["BILATERAL_OCPI"]["evse"] == 1
    assert rep.by_channel["GUEST"]["evse"] == 2
    assert rep.by_channel["HUB_detail"]["HUBJECT"]["evse"] == 1


def test_dc_and_fast_dc_are_split():
    rep = k1.build_report(
        index(entry("A", 180), entry("B", 120), entry("C", 22, "AC"), entry("D", 0, "")),
        [row(u) for u in "ABCD"],
        AS_OF,
    )
    assert (rep.totals["k1_dc_evse"], rep.totals["k1_dc_150_plus_evse"]) == (2, 1)
    assert rep.by_power_class == {"AC": 1, "DC<150": 1, "DC>=150": 1, "unknown": 1}


def test_offered_and_claimed_are_potential_not_evidence():
    rep = k1.build_report(index(entry("A"), entry("B")), [row("A", status="offered"), row("B", status="claimed")], AS_OF)
    assert rep.totals["k1_evse"] == 0
    assert rep.potential == {"BILATERAL_OCPI/claimed": 1, "BILATERAL_OCPI/offered": 1}


def test_user_listed_station_never_counts_even_with_a_confirmed_row():
    rep = k1.build_report(index(entry("U", k1_ok=False)), [row("U")], AS_OF)
    assert rep.totals["k1_evse"] == 0
    assert rep.excluded["user_listed_with_confirmed_channel"] == ["U"]


def test_rows_for_unknown_evses_are_reported():
    rep = k1.build_report(index(entry("A")), [row("A"), row("ZZ")], AS_OF)
    assert rep.excluded["channel_rows_for_unknown_evse"] == ["ZZ"]
    assert any("missing from the corridor index" in w for w in rep.warnings)


def test_k1_gate_needs_120_evse_and_45_dc():
    def run(n_dc, n_ac):
        ents = [entry(f"D{i}") for i in range(n_dc)] + [entry(f"A{i}", 22, "AC") for i in range(n_ac)]
        return k1.build_report(index(*ents), [row(e["evse_uid"]) for e in ents], AS_OF).gates["K1"]["status"]

    assert run(45, 75) == "PASS"
    assert run(44, 76) == "FAIL"  # enough EVSE, one DC short
    assert run(45, 74) == "FAIL"  # 119 in total


def test_k1h_share_and_open_threshold():
    rep = k1.build_report(
        index(*[entry(f"E{i}") for i in range(5)]),
        [row("E0", "HUB", hub="HUBJECT")] + [row(f"E{i}") for i in range(1, 5)],
        AS_OF,
    )
    assert rep.k1h["share_of_k1"] == 0.2 and rep.k1h["meets_proposal"] is True
    assert rep.k1h["meets_threshold"] is None and rep.gates["K1-H"]["status"] == "OPEN"
    set_ = k1.build_report(index(entry("E0")), [row("E0", "HUB", hub="HUBJECT")], AS_OF, k1h_min_share=0.5)
    assert set_.gates["K1-H"]["status"] == "PASS"
    low = k1.build_report(index(entry("E0"), entry("E1")), [row("E0", "HUB", hub="HUBJECT"), row("E1")], AS_OF, k1h_min_share=0.6)
    assert low.gates["K1-H"]["status"] == "FAIL"


def test_hub_other_than_hubject_does_not_feed_k1h():
    rep = k1.build_report(index(entry("A")), [row("A", "HUB", hub="GIREVE")], AS_OF)
    assert rep.k1h["hubject_evse"] == 0 and rep.by_channel["HUB"]["evse"] == 1


def test_empty_inputs_do_not_divide_by_zero():
    rep = k1.build_report(index(), [], AS_OF)
    assert rep.k1h["share_of_k1"] is None and rep.gates["K1"]["status"] == "FAIL"


def test_draft_geometry_warns():
    rep = k1.build_report(index(entry("A"), quality="draft-waypoints"), [row("A")], AS_OF)
    assert any("not reliable" in w for w in rep.warnings)
    assert not k1.build_report(index(entry("A")), [row("A")], AS_OF).warnings


def test_a_station_near_two_families_counts_in_both():
    rep = k1.build_report(index(entry("A", families=("M", "A2"))), [row("A")], AS_OF)
    assert rep.by_family["M"]["evse"] == rep.by_family["A2"]["evse"] == 1 and rep.totals["k1_evse"] == 1


@pytest.mark.parametrize(
    "line,msg",
    [
        ("A,SMOKE,confirmed,,r,d", "channel"),
        ("A,GUEST,maybe,,r,d", "status"),
        ("A,HUB,confirmed,,r,d", "needs hub"),
        ("A,GUEST,confirmed,HUBJECT,r,d", "only for HUB"),
        ("A,GUEST,confirmed,,,d", "evidence_ref"),
        (",GUEST,confirmed,,r,d", "empty evse_uid"),
    ],
)
def test_bad_channel_rows_are_rejected(tmp_path, line, msg):
    p = tmp_path / "c.csv"
    p.write_text("evse_uid,channel,status,hub,evidence_ref,evidence_date\n" + line + "\n")
    with pytest.raises(k1.InputError, match=msg):
        k1.read_channels(p)


def test_missing_columns_are_rejected(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("evse_uid,channel\nA,GUEST\n")
    with pytest.raises(k1.InputError, match="missing columns"):
        k1.read_channels(p)


def test_cli_end_to_end_on_the_sample_files(tmp_path, capsys):
    j, m = tmp_path / "r.json", tmp_path / "r.md"
    rc = k1.main(["--index", "evidence/samples/index-sample.json", "--channels", "evidence/samples/channels-sample.csv",
                  "--as-of", "2026-11-03", "--json-out", str(j), "--md-out", str(m)])
    assert rc == 0
    d = json.loads(j.read_text())
    assert d["totals"]["k1_evse"] == 2 and d["totals"]["k1_dc_evse"] == 2 and d["totals"]["k1_dc_150_plus_evse"] == 1
    assert d["excluded"]["user_listed_with_confirmed_channel"] == ["SAMPLE-4"]
    assert d["excluded"]["channel_rows_for_unknown_evse"] == ["SAMPLE-9"]
    assert d["potential"] == {"BILATERAL_OCPI/offered": 1}
    text = m.read_text()
    assert text.startswith("# K1 evidence count, 2026-11-03") and "K1 FAIL" in text.splitlines()[2]


def test_cli_reports_bad_input_with_exit_code_2(tmp_path, capsys):
    bad = tmp_path / "c.csv"
    bad.write_text("evse_uid,channel,status\nA,NOPE,confirmed\n")
    assert k1.main(["--index", "evidence/samples/index-sample.json", "--channels", str(bad)]) == 2
    assert "channel" in capsys.readouterr().err

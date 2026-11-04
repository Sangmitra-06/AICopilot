"""The criteria menu and form walkthrough read only from definitions/venue_criteria.json."""
import asyncio
import json
import logging

import pytest

from app import criteria, main, onboarding as ob, venue
from test_onboarding import Session


def write_venue(tmp_path, monkeypatch, criteria_list, status="official guidelines", venue_name="Test Venue",
                cycle="2031-Q1"):
    f = tmp_path / "venue_criteria.json"
    f.write_text(json.dumps({"source": {"venue": venue_name, "cycle": cycle, "status": status},
                             "criteria": criteria_list}), encoding="utf-8")
    monkeypatch.setattr(venue, "PATH", str(f))
    return f


CUSTOM = [
    {"id": "alpha", "label": "Alpha", "description": "Alpha, in the venue's words."},
    {"id": "beta", "label": "Beta", "description": "Beta, in the venue's words."},
    {"id": "gamma", "label": "Gamma", "description": "Gamma, in the venue's words.", "menu": True},
    {"id": "delta", "label": "Delta", "description": "Delta, in the venue's words.", "menu": False},
]


# ------------------------------------------------------------------ built purely from the file

def test_menu_is_built_purely_from_the_file(tmp_path, monkeypatch):
    write_venue(tmp_path, monkeypatch, CUSTOM)
    # prove independence from the other criteria config: it is not consulted at all
    monkeypatch.setattr(criteria, "items", lambda: pytest.fail("menu read criteria.json"))
    monkeypatch.setattr(criteria, "load", lambda: pytest.fail("menu read criteria.json"))
    menu = ob.menu_for("rev", "strength_criteria")
    assert {m["id"] for m in menu[:-1]} == {"alpha", "beta", "gamma"}  # delta is menu:false
    by_id = {m["id"]: m for m in menu}
    for c in CUSTOM[:3]:
        assert by_id[c["id"]]["label"] == c["label"] and by_id[c["id"]]["description"] == c["description"]
    assert "Soundness" not in json.dumps(menu)


def test_walkthrough_is_built_purely_from_the_file(tmp_path, monkeypatch):
    write_venue(tmp_path, monkeypatch, CUSTOM)
    monkeypatch.setattr(criteria, "items", lambda: pytest.fail("walkthrough read criteria.json"))
    monkeypatch.setattr(criteria, "load", lambda: pytest.fail("walkthrough read criteria.json"))
    w = ob.walkthrough()
    assert [p["id"] for p in w["parts"]] == ["alpha", "beta", "gamma", "delta"]  # menu:false parts still shown
    assert w["parts"][0] == {"id": "alpha", "label": "Alpha", "description": "Alpha, in the venue's words."}
    assert w["text"].startswith("The Test Venue review form has 4 parts, in this order: Alpha; Beta; Gamma; Delta.")
    assert "Soundness" not in json.dumps(w)


def test_swapping_the_file_changes_the_menu_with_no_code_change(tmp_path, monkeypatch):
    f = write_venue(tmp_path, monkeypatch, CUSTOM[:2])
    assert {m["id"] for m in ob.menu_items()} == {"alpha", "beta"}
    f.write_text(json.dumps({"source": {"venue": "V", "cycle": "c", "status": "official"},
                             "criteria": [{"id": "zeta", "label": "Zeta", "description": "Z."}]}), encoding="utf-8")
    import os
    os.utime(f, (os.path.getmtime(f) + 5, os.path.getmtime(f) + 5))  # make the change visible to the mtime cache
    assert [m["id"] for m in ob.menu_items()] == ["zeta"]


def test_menu_descriptions_are_the_venues_wording_exactly(tmp_path, monkeypatch):
    write_venue(tmp_path, monkeypatch, CUSTOM)
    s = Session("r9")
    s.step(); s.say("0"); s.say("never worked on it")
    for a in ("abstract", "alone", "after", "pdf"):
        r = s.say(a)
    shown = {m["id"]: m.get("description") for m in r["menu"]}
    assert shown.pop("other") is None  # "Other" has no description to show
    assert shown == {c["id"]: c["description"] for c in CUSTOM[:3]}


# ------------------------------------------------------------------ order and "Other"

def test_order_is_stable_for_one_reviewer_and_differs_across_reviewers():
    first = [m["id"] for m in ob.menu_for("alice", "strength_criteria")]
    for _ in range(5):
        assert [m["id"] for m in ob.menu_for("alice", "strength_criteria")] == first
    orders = {tuple(m["id"] for m in ob.menu_for(f"reviewer-{i}", "strength_criteria")) for i in range(40)}
    assert len(orders) >= 3  # four entries have 24 orders; 40 reviewers must not all see the same one


@pytest.mark.parametrize("rid", [f"r{i}" for i in range(30)])
def test_other_in_my_words_is_always_last(rid):
    menu = ob.menu_for(rid, "weakness_criteria")
    assert menu[-1] == {"id": "other", "label": "Other, in my words"}
    assert [m["id"] for m in menu[:-1]].count("other") == 0


def test_the_menu_is_stable_when_the_question_is_asked_again():
    s = Session("same")
    s.step(); s.say("0"); s.say("never worked on it")
    for a in ("abstract", "alone", "after", "pdf"):
        r = s.say(a)
    assert r["menu"] == s.step()["menu"]


# ------------------------------------------------------------------ the seed file

def test_seed_file_is_marked_placeholder_with_venue_and_cycle():
    s = venue.source()
    assert s["status"] == "placeholder, replace with official guidelines"
    assert s["venue"] == "ACL Rolling Review" and "cycle" in s
    assert venue.is_placeholder()


def test_seed_file_has_id_label_description_for_every_form_part():
    raw = json.load(open(venue.PATH, encoding="utf-8"))
    for c in raw["criteria"]:
        assert c["id"].strip() and c["label"].strip() and c["description"].strip(), c
        assert "Stand-in wording" not in c["description"]  # the note is carried by `source`, not repeated
    assert [c["id"] for c in raw["criteria"]] == [c["id"] for c in criteria.items()]  # same parts as the form


def test_seed_menu_keeps_the_four_entries_it_had_before():
    assert [m["label"] for m in sorted(venue.menu_items(), key=lambda m: m["label"])] == [
        "Ethical concerns", "Excitement", "Reproducibility", "Soundness"]


def test_descriptions_carry_no_assistant_commentary():
    raw = {c["id"]: c["description"] for c in json.load(open(venue.PATH, encoding="utf-8"))["criteria"]}
    for cid, text in raw.items():
        stand_in = open(f"{criteria.DEFS}/{cid}.txt", encoding="utf-8-sig").read()
        assert text in " ".join(stand_in.split()), cid  # a verbatim line of the venue's stand-in definition


# ------------------------------------------------------------------ validation

@pytest.mark.parametrize("bad,needle", [
    ([], "non-empty list"),
    ([{"id": "a", "label": "A"}], "description"),
    ([{"id": "a", "label": "", "description": "d"}], "label"),
    ([{"id": "a", "label": "A", "description": "d"}, {"id": "a", "label": "B", "description": "e"}], "duplicate"),
    ([{"id": "a", "label": "A", "description": "d", "menu": "yes"}], "menu"),
])
def test_a_malformed_file_is_reported_with_its_path(tmp_path, monkeypatch, bad, needle):
    f = write_venue(tmp_path, monkeypatch, bad)
    with pytest.raises(ValueError) as e:
        venue.load()
    assert needle in str(e.value) and str(f) in str(e.value)


def test_unparseable_json_is_reported(tmp_path, monkeypatch):
    f = tmp_path / "v.json"
    f.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(venue, "PATH", str(f))
    with pytest.raises(ValueError, match="v.json"):
        venue.load()


# ------------------------------------------------------------------ startup warning

def test_warning_is_logged_while_the_source_is_a_placeholder(caplog):
    with caplog.at_level(logging.WARNING, logger="copilot.venue"):
        assert venue.warn_if_placeholder() is True
    msg = caplog.records[-1].getMessage()
    assert "placeholder, replace with official guidelines" in msg and "ACL Rolling Review" in msg


def test_no_warning_once_the_source_is_official(tmp_path, monkeypatch, caplog):
    write_venue(tmp_path, monkeypatch, CUSTOM, status="official guidelines, cycle published 2031-01-05")
    with caplog.at_level(logging.WARNING, logger="copilot.venue"):
        assert venue.warn_if_placeholder() is False
    assert not caplog.records


def test_the_app_warns_at_startup(caplog):
    async def boot():
        async with main.lifespan(main.app):
            pass
    with caplog.at_level(logging.WARNING, logger="copilot.venue"):
        asyncio.run(boot())
    assert any("placeholder" in r.getMessage() for r in caplog.records)


def test_the_app_refuses_to_start_with_a_broken_file(tmp_path, monkeypatch):
    f = tmp_path / "v.json"
    f.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(venue, "PATH", str(f))

    async def boot():
        async with main.lifespan(main.app):
            pass
    with pytest.raises(Exception):
        asyncio.run(boot())

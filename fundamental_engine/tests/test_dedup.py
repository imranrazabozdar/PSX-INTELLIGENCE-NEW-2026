import pytest

from extract import dedup
from extract.dedup import cluster_plan, fingerprint, group_items, normalize_title, similarity


def same(a, b):
    return fingerprint(a) == fingerprint(b) and fingerprint(a) is not None


@pytest.mark.parametrize("a,b", [
    ("Gold rises over 1% as softer oil prices ease inflation worries", "GOLD RISES OVER 1% AS SOFTER OIL PRICES EASE INFLATION WORRIES"),   # case
    ("Gold rises over 1% as softer oil prices ease inflation worries", "Gold  rises over 1%   as softer oil prices ease inflation worries "),  # whitespace
    ("PSX sheds nearly 1,500 points", "PSX sheds nearly 1500 points"),                                                                  # thousands separator
    ("Petrol price cut by Rs6.59, HSD’s by Rs4.25", "Petrol price cut by Rs 6.59, HSD's by Rs. 4.25"),                                   # quotes, currency spacing
    ("Short-term inflation surges to 12.31pc", "Short-term inflation surges to 12.31 percent"),                                          # percent spellings
    ("Short-term inflation surges to 12.31pc", "Short-term inflation surges to 12.31%"),
    ("SECP seeks records from banks in IPO probe", "SECP seeks records from banks in IPO probe - Business Recorder"),                   # publisher suffix
    ("SECP seeks records from banks in IPO probe", "SECP seeks records from banks in IPO probe | Dawn.com"),
    ("SECP seeks records from banks in IPO probe", "Dawn: SECP seeks records from banks in IPO probe"),                                  # publisher prefix
    ("SECP seeks records from banks in IPO probe", "UPDATE 2 - SECP seeks records from banks in IPO probe"),                            # wire prefix
    ("The 50-point gap behind tariff debate", "50-point gap behind tariff debate"),                                                      # leading article
    ("Rupee records gain against US dollar", "Rupee records gain against US dollar!!!"),                                                 # trailing punctuation
    ("China’s factory-gate inflation at fastest in nearly 4-1/2 years", "China's factory-gate inflation at fastest in nearly 4-1/2 years"),
])
def test_same_story_variants_have_same_fingerprint(a, b):
    assert same(a, b), (normalize_title(a), normalize_title(b))


@pytest.mark.parametrize("a,b", [
    ("Petrol price slashed by Rs9.41 per litre", "Petrol price slashed by Rs6.59 per litre"),            # different figure = different fact
    ("Pakistan's forex reserves climb to $26bn", "Pakistan's forex reserves climb to $27bn"),             # UPDATED story with a new figure
    ("SBP keeps policy rate unchanged", "SBP cuts policy rate"),                                         # similar words, opposite facts
    ("OGDC announces final cash dividend", "PPL announces final cash dividend"),                          # different company
    ("Weekly SPI inflation up 0.29pc", "Weekly SPI inflation down 0.29pc"),
    ("Petrol price cut by Rs6.59, HSD's by Rs4.25", "Petrol price down by Rs6.59 per litre, high-speed diesel by Rs4.25 in fifth straight cut"),  # reworded
    ("", "something"), (None, "x"),
])
def test_distinct_or_empty_headlines_never_collide(a, b):
    assert not same(a, b)


def test_numbers_are_preserved_in_normalisation():
    assert "rs6.59" in normalize_title("Petrol price cut by Rs 6.59").split() and "12.31pc" in normalize_title("up 12.31 per cent").split()
    assert "1500" in normalize_title("1,500 points").split() and "4-1/2" in normalize_title("nearly 4-1/2 years").split()


def test_near_duplicates_reported_not_equated():
    a = "Government announces new tax relief package for exporters this week"
    b = "Government announces new tax relief package for exporters this week, officials say"
    s = similarity(a, b)
    assert not same(a, b) and s["near_duplicate"] is True and s["same_numbers"]
    assert similarity("Petrol price cut by Rs6.59 per litre", "Petrol price cut by Rs9.41 per litre")["near_duplicate"] is False   # numbers differ
    assert similarity("Rupee gains", "Rupee falls")["near_duplicate"] is False                                                      # too short / different


def item(i, src, title):
    return {"source_item_id": i, "source_id": src, "title": title}


def test_group_items_cross_feed_keeps_first_and_never_mutates_inputs():
    items = [item(1, "brecorder", "Gold rises over 1% as oil eases"), item(2, "dawn", "Unrelated local story about a flood"),
             item(3, "brecorder_markets", "Gold rises over 1% as oil eases | Business Recorder"), item(4, "dawn", "GOLD RISES OVER 1% AS OIL EASES"),
             item(5, "tribune", "Government announces new tax relief package for exporters this week"),
             item(6, "dawn", "Government announces new tax relief package for exporters this week, officials say")]
    snapshot = [dict(x) for x in items]
    g = group_items(items)
    assert g["duplicate_of"] == {3: 1, 4: 1} and g["exact"] == [[1, 3, 4]]
    assert [(a, b) for a, b, _ in g["near"]] == [(5, 6)]                       # reported only
    assert items == snapshot                                                   # originals untouched
    assert 6 not in g["duplicate_of"]                                          # near-duplicates are NOT skipped


def test_cluster_plan_uses_existing_tables_and_min_id_key():
    plan = cluster_plan({"exact": [[7, 3, 9]]}, "2026-11-09T00:00:00Z")
    assert plan[0][1][0] == "dedup@v1:3" and len(plan) == 4 and all("story_cluster" in s for s, _ in plan)


def test_cluster_plan_executes_on_real_schema_idempotently(db):
    db.execute("INSERT INTO sources(source_id,name,source_type,created_at_utc,updated_at_utc) VALUES('s','s','news_media','t','t')")
    ids = [db.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256) VALUES('s',?,?, 't',?)",
                      (f"e{i}", "x", "a" * 64)).lastrowid for i in range(3)]
    for _ in range(2):
        db.batch(cluster_plan({"exact": [ids]}, "2026-11-09T00:00:00Z"))
    assert db.execute("select count(*) n from story_clusters").one()["n"] == 1
    assert db.execute("select count(*) n from story_cluster_members").one()["n"] == 3

from interest_signals.output.grounding import ungrounded

ALLOWED = [22895.0, 6.1, 50.0, 59.0, 41.0, 0.5333, 324.0, 24.0]  # 24: period months


def test_locale_formats_are_grounded():
    texts = ["22 895 переглядів, 6,1 на 1 млн, тренд −50 % (−59 % … −41 %)", "22,895 and 22.895 views",
             "about 23 thousand", "22.9K", "score 0.53", "324"]
    assert ungrounded(texts, ALLOWED) == []


def test_small_counts_and_years_are_free():
    assert ungrounded(["3 languages over 24 months, 2024-09 to 2026-08"], ALLOWED) == []


def test_invented_numbers_are_reported():
    assert ungrounded(["about 300 views, 3.5 times more, +18%"], ALLOWED) == ["300", "3.5", "18"]

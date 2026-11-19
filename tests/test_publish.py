from tf.probe import marketplace_size
from tf.publish import week_label


def test_week_label_covers_previous_seven_days():
    # Monday Nov 30 run -> window Nov 23..29 (ISO week 48)
    assert week_label("2026-11-30") == ("2026-W48", "Nov 23", "Nov 29")


def test_marketplace_size():
    assert marketplace_size('{"plugins": [{}, {}, {}]}') == 3
    assert marketplace_size('{"plugins": {}}') == 0
    assert marketplace_size("not json") == 0
    assert marketplace_size(None) == 0

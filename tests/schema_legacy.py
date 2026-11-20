"""Remove only empty later entities when constructing historical test saves."""


def remove_crisis_v2_tables(connection):
    for name in ("crisis_v2_battles", "crisis_v2_maps", "crisis_v2_seasons", "crisis_v2_accounts"):
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
            assert connection.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] == 0
            connection.execute('DROP TABLE "' + name + '"')

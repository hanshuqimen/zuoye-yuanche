"""Shared authored score metadata, never a product fallback for missing data."""


def add_base_score(tables):
    table = tables["roguelike_topic_table"]
    detail = table["details"]["rogue_1"]
    for key, value in {"milestoneTokenRatio": 1, "outerBuffTokenRatio": 10}.items():
        table["constant"].setdefault(key, value)
    detail.setdefault("difficulties", [{"modeDifficulty": "NORMAL", "grade": 0, "scoreFactor": 1, "bpValue": 0}])
    for row in detail["difficulties"]:
        if row.get("modeDifficulty") == "NORMAL" and row.get("grade") == 0:
            row.setdefault("scoreFactor", 1)
            row.setdefault("bpValue", 0)
    for key, value in {"historicalRecordsMode": "NONE", "historicalRecordsCount": 0, "outerBuffTokenSum": 100}.items():
        detail["detailConst"].setdefault(key, value)
    detail.setdefault("milestoneUpdates", [{"updateTime": 0, "endTime": -1, "maxBpCount": 200}])
    detail["gameConst"].setdefault("gpScoreRatio", 0)


def add_empty_closure_ledger(connection):
    """Keep unrelated latest-schema requirements present in corruption cases."""
    from sqlalchemy.dialects.sqlite import dialect
    from sqlalchemy.schema import CreateTable

    from terralocal.server.persistence.models import RogueRunClosure

    connection.execute(str(CreateTable(RogueRunClosure.__table__).compile(dialect=dialect())))

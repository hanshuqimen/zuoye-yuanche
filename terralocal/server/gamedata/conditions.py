"""Translate static-data clear requirements into the domain's star count."""


def required_stars(value: str | int) -> int:
    if value == "PASS":
        return 1
    if value == "COMPLETE":
        return 3
    # Older normalized imports and the miniature data use explicit star counts.
    if type(value) is int and value in (1, 2, 3):
        return value
    raise ValueError(f"不支持的关卡通关条件: {value!r}")

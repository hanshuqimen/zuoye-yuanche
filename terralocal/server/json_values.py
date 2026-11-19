"""Compare JSON values without losing their serialized types."""


def same_json_value(before, after) -> bool:
    if before is after:
        return True
    # Python considers True == 1 and 1 == 1.0 despite the different JSON values.
    if type(before) is not type(after):
        return False
    if isinstance(after, list):
        return len(before) == len(after) and all(
            same_json_value(left, right) for left, right in zip(before, after)
        )
    if isinstance(after, dict):
        return before.keys() == after.keys() and all(
            same_json_value(before[key], value) for key, value in after.items()
        )
    return before == after

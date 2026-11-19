"""Structural deltas: dictionaries merge, lists replace, deleted dictionaries remove keys."""

from copy import deepcopy

from terralocal.server.json_values import same_json_value


def diff(before: dict, after: dict) -> dict:
    modified, deleted = {}, {}
    for key in before.keys() - after.keys():
        deleted[key] = 1
    for key, value in after.items():
        if key not in before:
            modified[key] = value
        elif isinstance(value, dict) and isinstance(before[key], dict):
            nested = diff(before[key], value)
            if nested["modified"]:
                modified[key] = nested["modified"]
            if nested["deleted"]:
                deleted[key] = nested["deleted"]
        elif not same_json_value(before[key], value):
            modified[key] = value
    return {"modified": modified, "deleted": deleted}


def apply(state: dict, delta: dict) -> dict:
    result = deepcopy(state)

    def merge(target, changes):
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    def remove(target, changes):
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                remove(target[key], value)
            else:
                target.pop(key, None)

    merge(result, delta["modified"])
    remove(result, delta["deleted"])
    return result

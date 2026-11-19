"""Initial home display from the selected immutable client catalog.

Only the catalog's default background and theme are owned initially. This does
not grant event backgrounds, paid themes, or fabricate completed review groups.
"""


def initial_display(ctx) -> dict:
    if "display_meta_table" not in ctx.data.manifest["tables"]:
        return {}
    catalog = ctx.data.table("display_meta_table")["homeBackgroundData"]
    background, theme = catalog["defaultBackgroundId"], catalog["defaultThemeId"]
    from terralocal.server.domain.home_rotation import snapshot

    rotation = snapshot(ctx)
    selected = rotation.get("charRotation", {})
    selected = selected.get("preset", {}).get(selected.get("current"), {})
    return {
        "background": {"selected": selected.get("background", background),
                       "bgs": {background: {"unlock": ctx.profile.registered_at}}},
        "homeTheme": {"selected": selected.get("homeTheme", theme),
                      "themes": {theme: {"unlock": ctx.profile.registered_at}}},
        **rotation,
    }

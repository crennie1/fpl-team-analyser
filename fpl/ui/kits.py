"""Club shirt colours for the SVG kits (drawn by the app; no club images are used)."""


def _k(body, sleeves, text, pattern="plain", colours=None):
    kit = {"body": body, "sleeves": sleeves, "text": text, "pattern": pattern}
    if colours:
        kit["pattern_colors"] = colours
    return kit


KITS = {
    "ARS": _k("#EF0107", "#ffffff", "#ffffff"),
    "AVL": _k("#670E36", "#95BFE5", "#ffffff"),
    "BOU": _k("#DA291C", "#000000", "#ffffff", "stripes", ["#DA291C", "#111111"]),
    "BRE": _k("#e30613", "#ffffff", "#ffffff", "stripes", ["#e30613", "#ffffff"]),
    "BHA": _k("#0057B8", "#0057B8", "#0057B8", "stripes", ["#0057B8", "#ffffff"]),
    "CHE": _k("#034694", "#034694", "#ffffff"),
    "COV": _k("#59c3eb", "#ffffff", "#0b1f4b"),
    "CRY": _k("#1B458F", "#C4122E", "#ffffff", "stripes", ["#1B458F", "#C4122E"]),
    "EVE": _k("#003399", "#003399", "#ffffff"),
    "FUL": _k("#ffffff", "#000000", "#000000"),
    "HUL": _k("#F5A200", "#111111", "#111111", "stripes", ["#F5A200", "#111111"]),
    "IPS": _k("#0044aa", "#ffffff", "#ffffff"),
    "LEE": _k("#ffffff", "#1D428A", "#1D428A"),
    "LIV": _k("#C8102E", "#C8102E", "#ffffff"),
    "MCI": _k("#6CABDD", "#ffffff", "#1c2c5b"),
    "MUN": _k("#DA291C", "#ffffff", "#ffffff"),
    "NEW": _k("#ffffff", "#ffffff", "#ffffff", "stripes", ["#111111", "#ffffff"]),
    "NFO": _k("#DD0000", "#ffffff", "#ffffff"),
    "TOT": _k("#ffffff", "#132257", "#132257"),
    "SUN": _k("#EB172B", "#ffffff", "#ffffff", "stripes", ["#EB172B", "#ffffff"]),
}

DEFAULT_KIT = _k("#6b7280", "#4b5563", "#ffffff")

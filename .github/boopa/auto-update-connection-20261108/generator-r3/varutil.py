"""Shared variation-series thinning for the BoothDB payload builders.

A variation entry becomes {"p": points, "d": obs_days, "sd": sale_days,
"average_source": {"sum": price_sum, "count": observation_count}}.
The average metadata is computed before thinning, excluding marked outliers
when ordinary observations exist; an all-marked input retains the legacy
fallback to all observations.
where points are run-length thinned [date, price, is_sale] rows: the first
row of each constant (price, is_sale) segment plus the final row, which
preserves the exact step shape and sale-period boundaries at a fraction
of the size of the daily series.
"""


import math

def find_outlier_indexes(rows):
    """Boopa's findSeparatedHighPoints: sorted positive prices, first split
    (from max(5, 80%)) where price jumps >=20x and the ordinary side covers
    >=5 distinct dates; points from the split on are outliers."""
    pos = sorted((i for i, r in enumerate(rows) if r[1] > 0), key=lambda i: rows[i][1])
    n = len(pos)
    out = set()
    for split in range(5, n):
        if rows[pos[split]][1] / rows[pos[split - 1]][1] >= 20:
            if len({rows[i][0] for i in pos[:split]}) >= 5:
                out = set(pos[split:])
                break
    if any(r[1] == 0 or 0 < r[1] < 1000000 for r in rows):
        out |= {i for i, r in enumerate(rows) if r[1] >= 1000000}
    return out


def tag_outliers(rows):
    oi = find_outlier_indexes(rows)
    return [[*r, 1] if i in oi else r for i, r in enumerate(rows)]


def thin_points(rows):
    """rows: [[date, price, sale], ...] sorted by date -> thinned rows."""
    if len(rows) <= 2:
        return rows
    out = [rows[0]]
    for i in range(1, len(rows) - 1):
        if (rows[i][1], rows[i][2]) != (rows[i - 1][1], rows[i - 1][2]):
            out.append(rows[i])
    out.append(rows[-1])
    return out


def average_source(rows):
    """Full observations, not graph samples. Preserve all-marked fallback.

    Each recorded observation has equal weight (not elapsed calendar days).
    Constant-space accumulator; never retain another copy of the history.
    """
    total = ordinary_total = 0
    count = ordinary_count = 0
    for row in rows:
        total += row[1]
        count += 1
        if len(row) < 4 or not row[3]:
            ordinary_total += row[1]
            ordinary_count += 1
    result = {"sum": ordinary_total if ordinary_count else total,
              "count": ordinary_count if ordinary_count else count}
    if not math.isfinite(result["sum"]) or not 0 <= result["sum"] <= 9007199254740991 or not 0 <= result["count"] <= 9007199254740991:
        raise ValueError("Average statistics exceed safe numeric range")
    return result


def thin_vars_from_item(d):
    """Tracker item dict -> ordered {name: {p, d, sd}} with the
    representative (longest) variation first; None when fewer than two
    variations have at least two points."""
    vars_ = d.get("variations") or {}
    entries = {}
    for k, series in vars_.items():
        if not isinstance(series, list) or len(series) < 2:
            continue
        s = sorted(series, key=lambda p: p["date"])
        rows = tag_outliers([[p["date"], p["price"], 1 if p.get("is_sale") else 0] for p in s])
        entries[k] = {
            "p": thin_points(rows),
            "d": len(rows),
            "sd": sum(r[2] for r in rows),
            "average_source": average_source(rows),
        }
    if len(entries) < 2:
        return None
    rep = max(entries, key=lambda k: entries[k]["d"])
    ordered = {rep: entries[rep]}
    for k in entries:
        if k != rep:
            ordered[k] = entries[k]
    return ordered


def convert_raw_variations(vars_):
    """payload.json charts format {name: [[date, price, sale], ...]} ->
    the thinned object format, representative first."""
    entries = {}
    for k, rows in (vars_ or {}).items():
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        rows = tag_outliers([list(r) for r in rows])
        entries[k] = {
            "p": thin_points(rows),
            "d": len(rows),
            "sd": sum(r[2] for r in rows),
            "average_source": average_source(rows),
        }
    if not entries:
        return vars_
    rep = max(entries, key=lambda k: entries[k]["d"])
    ordered = {rep: entries[rep]}
    for k in entries:
        if k != rep:
            ordered[k] = entries[k]
    return ordered

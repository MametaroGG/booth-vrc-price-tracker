#!/usr/bin/env python3
"""Build the full (uncapped) list data + search index for BoothDB.

Outputs (into prod/):
  search_index.json  [[id, name], ...] for every tracked product
  lists_full.json    {on_sale, free, drops, active, newest} with ALL
                     qualifying products (time windows instead of
                     count caps), image/shop merged from meta.json
                     where available.
"""
import json, os, re, sys, hashlib, math
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from visibility_policy import VisibilityPolicy



_PX = re.compile(r"^https://booth\.pximg\.net/c/620x620/([0-9a-f-]{36}/i/\d+/[0-9a-f-]{36})_base_resized\.jpg$")


def px_compact(url):
    """Store pximg URLs in the search index without their fixed frame:
    'shop/i/img/file' (the client re-expands it). Non-matching URLs are
    stored whole; the client passes anything containing '://' through."""
    if not url:
        return ""
    m = _PX.match(url)
    return m.group(1) if m else url


def load_tracker_meta(META, visibility=None):
    """Load public metadata from the same exact reads as visibility evidence."""
    visibility = visibility or VisibilityPolicy(META)
    out = {}
    for ident, r in visibility.iter_metadata():
        if ident in visibility.excluded_ids() or not r.get("name"):
            continue
        shop = r.get("shop") or {}
        out[ident] = {
            "name": r["name"],
            "shop": shop.get("name") or "",
            "shop_sub": shop.get("subdomain") or "",
            "shop_url": shop.get("url") or "",
            "image": r.get("image_resized") or r.get("image") or None,
            "likes": r.get("likes"),
            "refs": r.get("refs") or [],
            "base_refs": r.get("base_refs") if isinstance(r.get("base_refs"), list) else None,
            "category": r.get("category"),
            "likes_history": r.get("likes_history") or [],
            "tags": r.get("tags") or [],
        }
    return out


def rep_variation(d):
    vars_ = d.get("variations") or {}
    best_key, best = None, None
    for k, series in vars_.items():
        if isinstance(series, list) and series and (best is None or len(series) > len(best)):
            best_key, best = k, series
    return best_key, best


def all_at_lowest(d):
    """Badge rule (user, 2026-10-25): True only when EVERY variation's
    latest price equals that variation's all-time minimum. One variation
    above its lowest and the item gets no badge."""
    series_list = [s for s in (d.get("variations") or {}).values()
                   if isinstance(s, list) and s]
    if not series_list:
        return False
    for series in series_list:
        ps = [p["price"] for p in sorted(series, key=lambda p: p["date"])]
        if ps[-1] > min(ps):
            return False
    return True


def per_day10(tm):
    """Likes gained per day over the last ~7 days of history, x10 int (0 = no data)."""
    hist = sorted((h for h in (tm.get("likes_history") or []) if h.get("date") and isinstance(h.get("count"), (int, float))), key=lambda h: h["date"])
    if len(hist) >= 2:
        last = hist[-1]
        target = (date.fromisoformat(last["date"]) - timedelta(days=7)).isoformat()
        base = hist[0]
        for h in hist:
            if h["date"] <= target:
                base = h
            else:
                break
        span = (date.fromisoformat(last["date"]) - date.fromisoformat(base["date"])).days
        if span >= 2:
            return round((last["count"] - base["count"]) / span * 10)
    return 0

DAILY_RECORDS_HASH_ALGORITHM = 'sha256-sorted-record-leaves-v1'


def daily_record_digest(record):
    """One bounded 32-byte leaf; canonical JSON is hashed incrementally."""
    wrapper = {'record':record, 'variation_order':list(record['variations']) if isinstance(record.get('variations'),dict) else None}
    digest = hashlib.sha256(b'boopadb-daily-record-v1\0')
    encoder = json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False)
    for chunk in encoder.iterencode(wrapper): digest.update(chunk.encode('utf-8'))
    return digest.digest()


def daily_leaf_root(leaves):
    digest = hashlib.sha256(b'boopadb-daily-sorted-leaves-v1\0')
    for leaf in sorted(leaves): digest.update(leaf)
    return digest.hexdigest()


def daily_records_sha256(records):
    """Order-independent snapshot binding; retains only 32-byte record hashes."""
    return daily_leaf_root([daily_record_digest(record) for record in records])


class DailyPriceAccumulator:
    """Streaming: retains only ID set, 32-byte hashes, counters and reasons.

    Input receipt schema1 additionally declares records_hash_algorithm exactly
    DAILY_RECORDS_HASH_ALGORITHM. Never synthesize coverage from snapshot dates.
    """
    def __init__(self,target_date=None,coverage=None,now=None):
        self.now=now or datetime.now(timezone.utc)
        if self.now.tzinfo is None: raise ValueError('Aware generation timestamp required')
        self.jst=timezone(timedelta(hours=9))
        self.day=target_date or self.now.astimezone(self.jst).date().isoformat()
        if date.fromisoformat(self.day).isoformat()!=self.day: raise ValueError('Canonical target date required')
        self.coverage=coverage;self.ids=set();self.leaves=[];self.changed=0;self.observed=False
        self.reason=None;self.id_error=False;self.history_error=None
        if self.day>self.now.astimezone(self.jst).date().isoformat():self.reason='future-target-date'
        elif not isinstance(coverage,dict):self.reason='missing-coverage'
        elif type(coverage.get('schema')) is not int or coverage['schema']!=1 or coverage.get('timezone')!='Asia/Tokyo' or coverage.get('complete') is not True:self.reason='incomplete-coverage'
        elif coverage.get('date')!=self.day:self.reason='stale-coverage'
        elif coverage.get('records_hash_algorithm')!=DAILY_RECORDS_HASH_ALGORITHM:self.reason='unsupported-records-hash-algorithm'

    def add(self,record,visible=True):
        if self.reason:return
        ident=record.get('id')
        if not isinstance(ident,str) or not re.fullmatch('[1-9][0-9]*',ident) or ident in self.ids:
            self.id_error=True
        else:self.ids.add(ident)
        try:self.leaves.append(daily_record_digest(record))
        except (TypeError,ValueError):self.history_error=self.history_error or 'invalid-price-history';return
        try:
            changed,observed,reason=self._observe(record)
            self.changed+=int(changed and visible);self.observed|=observed
            self.history_error=self.history_error or reason
        except (TypeError,ValueError,AttributeError,OverflowError):self.history_error=self.history_error or 'invalid-price-history'

    def _observe(self,record):
        _,series=rep_variation(record)
        if not series:return False,False,'missing-price-history'
        observations={};observed=False
        for observation in series:
            value=observation.get('price')
            if type(value) not in (int,float) or not math.isfinite(value):return False,False,'invalid-price'
            stamp=observation.get('date')
            if not isinstance(stamp,str):return False,False,'invalid-observation-date'
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',stamp):
                if self.coverage.get('history_timezone')!='Asia/Tokyo':return False,False,'unverified-history-timezone'
                instant=datetime.combine(date.fromisoformat(stamp),datetime.min.time(),self.jst)
            else:
                instant=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if instant.tzinfo is None:return False,False,'unverified-history-timezone'
                instant=instant.astimezone(self.jst)
            if instant>self.now.astimezone(self.jst):return False,False,'future-observation'
            if instant.date().isoformat()==self.day:observed=True
            if instant in observations and observations[instant]!=value:return False,False,'conflicting-observation'
            observations[instant]=value
        ordered=sorted(observations.items())
        changed=any(previous!=current and current_time.date().isoformat()==self.day for (_,previous),(current_time,current) in zip(ordered,ordered[1:]))
        return changed,observed,None

    def finish(self,cumulative):
        reason=self.reason
        if not reason:
            covered=self.coverage.get('product_ids')
            if self.id_error:reason='duplicate-or-invalid-product-id'
            elif not isinstance(covered,list) or any(type(i) is not str for i in covered) or len(covered)!=len(set(covered)) or set(covered)!=self.ids:reason='incomplete-product-coverage'
            elif self.coverage.get('records_sha256')!=daily_leaf_root(self.leaves):reason='unbound-coverage'
            elif self.history_error:reason=self.history_error
            elif not self.observed:reason='missing-observation-day'
            elif type(cumulative) is not int or cumulative<self.changed:reason='inconsistent-cumulative-count'
        basis='representative-variation-history'
        return dict(schema=1,cumulative=dict(unique_products=cumulative,basis=basis),daily=dict(date=self.day,timezone='Asia/Tokyo',basis=basis,unique_products=None if reason else self.changed,status='unavailable' if reason else 'complete',reason=reason,updated_at=self.now.isoformat()))


def price_change_stats(records,cumulative,target_date=None,coverage=None,now=None):
    accumulator=DailyPriceAccumulator(target_date,coverage,now)
    for record in records:accumulator.add(record)
    return accumulator.finish(cumulative)


def read_daily_coverage(path, private_dir):
    """Read receipt once, retain exact bytes privately; never infer attestations."""
    if path is None: return None, None
    private_dir = Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    try:
        data = Path(path).read_bytes()
    except OSError:
        return {}, None
    digest = hashlib.sha256(data).hexdigest()
    (private_dir / 'daily-coverage-receipt.json').write_bytes(data)
    (private_dir / 'daily-coverage-provenance.json').write_text(json.dumps({'schema':1,'sha256':digest,'bytes':len(data)}))
    try:
        receipt = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        receipt = {}
    return receipt if isinstance(receipt,dict) else {}, digest


def build(DATA, META, OUT, metadata_file=None, daily_coverage=None, daily_target_date=None, generation_time=None, current_price_projection=None, tracker_meta_hashes=None, visibility_private_dir=None, verified_source=None, retained_exclusions=None, quarantine=None, latest_negative_overlay=None):
    DATA, META, OUT = Path(DATA), Path(META), Path(OUT)
    if not DATA.is_dir() or not META.is_dir():
        raise ValueError("Explicit existing data and tracker-meta directories required")
    if any(OUT.resolve() == source.resolve() or source.resolve() in OUT.resolve().parents
           for source in (DATA, META)):
        raise ValueError("Public output must not be inside retained source data")
    OUT.mkdir(parents=True, exist_ok=True)
    meta = (verified_source.read_json(metadata_file) if verified_source else json.loads(Path(metadata_file).read_text(encoding="utf-8"))) if metadata_file else {}
    if not isinstance(meta, dict):
        raise ValueError("Metadata mapping must be an object")
    visibility = VisibilityPolicy(META, tracker_meta_hashes, generation_time, verified_source=verified_source, retained_exclusions=retained_exclusions, quarantine=quarantine, latest_negative_overlay=latest_negative_overlay)
    tmeta = load_tracker_meta(META, visibility)
    print(f"tracker meta: {len(tmeta)}", file=sys.stderr)
    files = []
    if verified_source:
        files = list(verified_source.paths('data', products_only=True))
    else:
        for shard in os.scandir(DATA):
            if shard.is_dir():
                for f in os.scandir(shard.path):
                    if f.name.endswith(".json"):
                        files.append(f.path)
    print(f"files: {len(files)}", file=sys.stderr)

    index = []
    daily_accumulator = DailyPriceAccumulator(daily_target_date, daily_coverage, generation_time)
    parsed = 0
    raw = []  # per-item aggregates, windowed after max_date is known
    max_date = ""
    source_min_date = None
    for path in files:
        try:
            raw_price = verified_source.read_bytes(path) if verified_source else Path(path).read_bytes()
            from visibility_policy import strict_json
            d = strict_json(raw_price)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid price record {path}: {exc}") from exc
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"].isascii() or not d["id"].isdecimal() or d["id"].startswith("0"):
            raise ValueError(f"Noncanonical item ID in {path}")
        if Path(path).stem != d["id"]:
            raise ValueError(f"Price record ID/path mismatch in {path}")
        visible = visibility.observe_product(d, raw_price)
        daily_accumulator.add(d, visible=visible)
        # Freshness is a property of the retained source snapshot, including
        # unavailable records. Public counts and rows are the visible subset.
        _, source_series = rep_variation(d)
        if source_series:
            source_first = min(p["date"] for p in source_series)
            source_last = max(p["date"] for p in source_series)
            source_min_date = source_first if source_min_date is None else min(source_min_date, source_first)
            max_date = max(max_date, source_last)
        if not visible:
            continue
        parsed += 1
        tm = tmeta.get(str(d["id"]), {})
        name = tm.get("name") or d.get("name", "")
        _cat = tm.get("category") or {}
        cat = ((_cat.get("name") or "") + " " + (_cat.get("parent") or "")).strip()
        likes = tm.get("likes") or 0
        shop_name = tm.get("shop") or (meta.get(str(d["id"]), {}) or {}).get("shop") or ""
        tags_list = tm.get("tags") or (meta.get(str(d["id"]), {}) or {}).get("tags") or []
        tags_str = " ".join(str(t) for t in tags_list if t)
        key, series = rep_variation(d)
        if not series:
            if name:
                index.append([d["id"], name, None, None, None, 0, 0, cat, likes, px_compact(tm.get("image")), 0, per_day10(tm), shop_name, tags_str])
            continue
        series = sorted(series, key=lambda p: p["date"])
        prices = [p["price"] for p in series]
        cur, base, lowest = prices[-1], max(prices), min(prices)
        cur_sale = bool(series[-1].get("is_sale"))
        projected = current_price_projection.for_item(d) if current_price_projection is not None else None
        if projected is not None:
            cur, base, lowest, cur_sale = projected['cur'], projected['base'], projected['lowest'], projected['on_sale']
        at_low_all = all_at_lowest(d)
        if name:
            index.append([d["id"], name, cur, base, lowest, 1 if cur_sale else 0, 1 if at_low_all else 0, cat, likes, px_compact(tm.get("image")), int(series[0]["date"].replace("-", "")), per_day10(tm), shop_name, tags_str])
        last_date = series[-1]["date"]
        if last_date > max_date:
            max_date = last_date
        changes = [i for i in range(1, len(series)) if prices[i] != prices[i - 1]]
        drop = None
        for i in range(len(series) - 1, 0, -1):
            if prices[i] != prices[i - 1]:
                if prices[i] < prices[i - 1]:
                    drop = {"from": prices[i - 1], "to": prices[i], "date": series[i]["date"],
                            "sale_event": bool(series[i].get("is_sale"))}
                break
        # First-observed date of every variation: a variation whose first
        # date falls inside the recent window while the product itself is
        # older is a public "update" (the creator added a variation).
        var_firsts = []
        for vn, vs in (d.get("variations") or {}).items():
            if vs:
                var_firsts.append([min(p["date"] for p in vs), vn])
        var_firsts.sort()
        m = meta.get(str(d["id"]), {})
        raw.append({
            "id": d["id"], "name": name, "cur": cur, "base": base, "lowest": lowest,
            "on_sale": cur_sale, "at_lowest": at_low_all,
            "current_projection": projected,
            "var_firsts": var_firsts,
            "first_date": series[0]["date"], "last_date": last_date,
            "last_change": series[changes[-1]]["date"] if changes else series[0]["date"],
            "changes_total": len(changes),
            "change_dates": [series[i]["date"] for i in changes],
            "drop": drop,
            "image": tm.get("image") or m.get("image"), "shop": tm.get("shop") or m.get("shop"),
            "shop_sub": tm.get("shop_sub") or "",
            "likes": tm.get("likes"),
            "likes_hist": tm.get("likes_history"),
        })

    if not max_date:
        raise ValueError("No usable dated price histories; refusing empty snapshot")
    md = date.fromisoformat(max_date)
    win21 = (md - timedelta(days=21)).isoformat()
    win30 = (md - timedelta(days=30)).isoformat()
    # Search-index per_day fallback, mirroring the rising list: items first
    # seen inside the 30-day window with no usable likes history yet get
    # likes / days-alive, so the rising sort matches the rising page.
    win30_int = int(win30.replace("-", ""))
    for e in index:
        if e[11] == 0 and e[10] and e[10] >= win30_int and e[8]:
            fd_d = date.fromisoformat(f"{str(e[10])[:4]}-{str(e[10])[4:6]}-{str(e[10])[6:8]}")
            days = max(1, (md - fd_d).days + 1)
            e[11] = round(e[8] / days * 10)
    print(f"max_date {max_date} win21 {win21} win30 {win30}", file=sys.stderr)

    def pub(r, extra):
        out = {"id": r["id"], "name": r["name"], "image": r["image"], "shop": r["shop"]}
        if r.get("likes") is not None:
            out["likes"] = r["likes"]
        out.update(extra)
        if r.get('current_projection') is not None and 'cur' in out:
            projection = r['current_projection']
            out.update({k:projection[k] for k in ('selected_variant_id','selected_variant_key','selection_observed_at')})
            out['spark'] = projection['observed_display_spark']
        return out

    on_sale, free, drops, active, newest = [], [], [], [], []
    for r in raw:
        if r["on_sale"] and r["cur"] < r["base"] and r["base"] >= 500:
            on_sale.append(pub(r, {"cur": r["cur"], "base": r["base"], "lowest": r["lowest"],
                                   "pct": round((r["base"] - r["cur"]) / r["base"] * 100),
                                   "at_lowest": r["at_lowest"], "date": r["last_date"]}))
        if r["cur"] == 0 and r["base"] >= 100:
            free.append(pub(r, {"cur": 0, "base": r["base"], "lowest": r["lowest"], "pct": 100,
                                "at_lowest": True, "on_sale": r["on_sale"], "date": r["last_date"]}))
        if r["drop"] and r["drop"]["date"] >= win21:
            drops.append(pub(r, {"from": r["drop"]["from"], "to": r["drop"]["to"], "date": r["drop"]["date"],
                                 "lowest": r["lowest"], "at_lowest": r["drop"]["to"] <= r["lowest"],
                                 "on_sale": r["on_sale"], "sale_event": r["drop"]["sale_event"]}))
        recent = sum(1 for cd in r["change_dates"] if cd >= win21)
        if recent >= 1:
            active.append(pub(r, {"cur": r["cur"], "base": r["base"], "lowest": r["lowest"],
                                  "at_lowest": r["at_lowest"], "on_sale": r["on_sale"],
                                  "changes_recent": recent, "changes_total": r["changes_total"],
                                  "first_date": r["first_date"], "last_change": r["last_change"]}))
        if r["first_date"] >= win30:
            newest.append(pub(r, {"cur": r["cur"], "base": r["base"], "lowest": r["lowest"],
                                  "at_lowest": r["at_lowest"], "on_sale": r["on_sale"],
                                  "first_date": r["first_date"]}))

    # Recent updates: products that already existed before the 30-day
    # window but gained at least one variation inside it (public signal:
    # variation additions). Newest addition first.
    updates = []
    for r in raw:
        if r["base"] and r["base"] > 100000:
            continue  # curated surface: gag base prices stay out, like popular
        vf = r.get("var_firsts") or []
        if not vf or vf[0][0] >= win30:
            continue
        adds = [[dt, nm] for dt, nm in vf if dt >= win30]
        if not adds:
            continue
        adds.sort(reverse=True)
        updates.append(pub(r, {"cur": r["cur"], "base": r["base"], "lowest": r["lowest"],
                                "at_lowest": r["at_lowest"], "on_sale": r["on_sale"],
                                "added": [{"name": nm, "date": dt} for dt, nm in adds[:3]],
                                "added_n": len(adds), "date": adds[0][0],
                                "first_date": vf[0][0]}))
    updates.sort(key=lambda s: (s["date"], s.get("likes") or 0), reverse=True)
    # Drop duplicate detections: the same shop adding the same variation
    # name on the same day across sibling products (avatar-specific
    # editions of one series) is one update, not several — keep the
    # most-liked entry.
    seen_upd = set()
    deduped = []
    for s in updates:
        key = (s.get("shop"), (s["added"][0]["name"] if s["added"] else ""), s["date"])
        if key in seen_upd:
            continue
        seen_upd.add(key)
        deduped.append(s)
    updates = deduped[:120]
    print("updates deduped", len(deduped), file=sys.stderr)
    print("updates", len(updates), file=sys.stderr)

    on_sale.sort(key=lambda s: (-s["pct"], -(s["base"] - s["cur"])))
    free.sort(key=lambda s: -s["base"])
    drops.sort(key=lambda s: (s["date"], s["from"] - s["to"]), reverse=True)
    active.sort(key=lambda s: (-s["changes_recent"], -s["changes_total"]))
    newest.sort(key=lambda s: s["first_date"], reverse=True)

    def gain_stats(r):
        likes = r.get("likes") or 0
        hist = sorted((h for h in (r.get("likes_hist") or []) if h.get("date") and isinstance(h.get("count"), (int, float))), key=lambda h: h["date"])
        if len(hist) >= 2:
            last = hist[-1]
            target = (date.fromisoformat(last["date"]) - timedelta(days=7)).isoformat()
            base = hist[0]
            for h in hist:
                if h["date"] <= target:
                    base = h
                else:
                    break
            span = (date.fromisoformat(last["date"]) - date.fromisoformat(base["date"])).days
            if span >= 2:
                return last["count"] - base["count"], (last["count"] - base["count"]) / span
        days = max(1, (md - date.fromisoformat(r["first_date"])).days + 1)
        return likes, likes / days

    rising = []
    for r in raw:
        if r["first_date"] >= win30 and (r.get("likes") or 0) > 0:
            gain, per_day = gain_stats(r)
            if per_day > 0:
                rising.append(pub(r, {"cur": r["cur"], "base": r["base"], "lowest": r["lowest"],
                                      "at_lowest": r["at_lowest"], "on_sale": r["on_sale"],
                                      "first_date": r["first_date"], "gain": gain,
                                      "per_day": round(per_day, 1)}))
    rising.sort(key=lambda s: (-s["per_day"], -(s.get("likes") or 0)))
    print("rising", len(rising), file=sys.stderr)

    # Popularity ranking source: top 300 by likes, gag base prices excluded
    # (rankings are a curated surface, like the featured mosaics).
    popular = [pub(r, {"cur": r["cur"], "base": r["base"], "lowest": r["lowest"],
                       "at_lowest": r["at_lowest"], "on_sale": r["on_sale"],
                       "first_date": r["first_date"]})
               for r in raw if (r.get("likes") or 0) > 0 and r["base"] and r["base"] <= 100000]
    popular.sort(key=lambda s: -(s.get("likes") or 0))
    popular = popular[:300]
    print("popular", len(popular), file=sys.stderr)

    lists = {"on_sale": on_sale, "free": free, "drops": drops, "active": active, "newest": newest,
             "rising": rising, "popular": popular, "updates": updates, "max_date": max_date,
             "visibility": visibility.public_payload()}
    # Home stats bar + page subtitles read these, so every data refresh
    # (this script) moves the numbers; definitions match build_prototype's
    # original payload stats (representative-variation series).
    stats = {"total": parsed, "sale_now": sum(1 for r in raw if r["on_sale"]),
             "free_now": len(free), "changed": sum(1 for r in raw if r["changes_total"] > 0),
             "min_date": source_min_date, "max_date": max_date}
    stats["price_changes"] = daily_accumulator.finish(stats["changed"])
    lists["stats"] = stats
    print("stats", stats, file=sys.stderr)
    if visibility_private_dir is None:
        import tempfile
        visibility_private_dir = Path(tempfile.mkdtemp(prefix='.' + OUT.name + '-visibility-', dir=OUT.parent))
    private_path = Path(visibility_private_dir).resolve()
    if private_path == OUT.resolve() or OUT.resolve() in private_path.parents:
        raise ValueError('Visibility evidence must stay outside the public output')
    if any(private_path == source.resolve() or source.resolve() in private_path.parents
           for source in (DATA, META)):
        raise ValueError('Visibility evidence must not modify retained source data')
    visibility_evidence = visibility.write_evidence(private_path, source_min_date, max_date)
    (OUT / "lists_full.json").write_text(json.dumps(lists, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if current_price_projection is not None:
        if set(current_price_projection.records) != set(current_price_projection.applied):
            raise ValueError('Unapplied projection proof')
        (OUT / 'current-price-projection.json').write_text(json.dumps({'schema':1,'entries':current_price_projection.applied}, ensure_ascii=False, separators=(',', ':')))
    # Shop digest for the home "shops you know" section, keyed by BOOTH
    # subdomain: [shop name, item count, top item, newest item]. Top item
    # array: [id, name, compact image, cur, base, on_sale]; newest:
    # [id, name, first_date] or null when it is the top item itself.
    # Shops with a single catalog item are omitted — the card for those
    # falls back to the visitor's own bookmarked/recommended item.
    by_shop = {}
    for r in raw:
        if r.get("shop_sub"):
            by_shop.setdefault(r["shop_sub"], []).append(r)
    digest = {}
    for sub, items in by_shop.items():
        if len(items) < 2:
            continue
        top = max(items, key=lambda r: r.get("likes") or 0)
        new = max(items, key=lambda r: r["first_date"])
        digest[sub] = [
            top["shop"] or "", len(items),
            [top["id"], top["name"], px_compact(top.get("image")), top["cur"], top["base"], 1 if top["on_sale"] else 0],
            None if new["id"] == top["id"] else [new["id"], new["name"], new["first_date"]],
        ]
    (OUT / "shop_digest.json").write_text(json.dumps(digest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("shop digest", len(digest), (OUT / "shop_digest.json").stat().st_size // 1024, "KB", file=sys.stderr)
    # Per-shop item lists for the product page's same-shop rail, sharded by
    # subdomain hash (djb2-xor, mirrored in the client) so a product page
    # fetches one small file: {subdomain: [[id, name, compact img, cur,
    # base, on_sale, at_lowest, likes], ...]} likes desc, cap 60 per shop.
    def _shop_shard(sub):
        h = 5381
        for ch in sub:
            h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
        return h % 24
    shop_shards = [dict() for _ in range(24)]
    for sub, items in by_shop.items():
        if len(items) < 2:
            continue
        rows = sorted(items, key=lambda r: -(r.get("likes") or 0))[:60]
        shop_shards[_shop_shard(sub)][sub] = [
            [r["id"], r["name"], px_compact(r.get("image")), r["cur"], r["base"],
             1 if r["on_sale"] else 0, 1 if r["at_lowest"] else 0, r.get("likes") or 0]
            for r in rows]
    for i, shard in enumerate(shop_shards):
        (OUT / f"shop_items_{i}.json").write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("shop item shards", sum(len(s) for s in shop_shards), "shops", file=sys.stderr)
    nshards = 24
    ssize = (len(index) + nshards - 1) // nshards
    for i in range(nshards):
        (OUT / f"search_index_{i}.json").write_text(json.dumps(index[i * ssize:(i + 1) * ssize], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # Category rail (home bottom): top-24 categories by item count, each
    # with its top-9 most-liked imaged items (compact pximg paths).
    _cc_counts = {}
    _cc_items = {}
    for _r in index:
        if not _r[7]:
            continue
        _cc_counts[_r[7]] = _cc_counts.get(_r[7], 0) + 1
        if _r[9]:
            _cc_items.setdefault(_r[7], []).append((_r[8] or 0, _r[9], _r[0]))
    _cc = {}
    for _cat, _n in sorted(_cc_counts.items(), key=lambda kv: -kv[1])[:24]:
        _top = sorted(_cc_items.get(_cat, []), key=lambda t: -t[0])[:9]
        if _top:
            _cc[_cat] = [{"id": _ident, "i": _img} for _l, _img, _ident in _top]
    (OUT / "cat_cards.json").write_text(json.dumps(_cc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("cat_cards", len(_cc), file=sys.stderr)
    for k in ("on_sale", "free", "drops", "active", "newest"):
        print(k, len(lists[k]), file=sys.stderr)
    # Relations (children side; parents resolve live from each item's own
    # meta record): use the context-judged base_refs when the scraper could
    # identify them; otherwise fall back to all description refs, except
    # links to tools/software, which are dependencies rather than parents.
    # Value: parent id -> [total children, [child ids by likes desc,
    # capped]], sharded by parent id for on-demand fetch.
    children = {}
    likes_of = {i: (t.get("likes") or 0) for i, t in tmeta.items()}
    dependency_cats = {"3Dツール・システム", "ソフトウェア"}
    # WITHDRAWN 2026-10-25 (user decision): neither the refs fallback nor
    # the scraper's heuristic base_refs is a proven judgment. Emit empty
    # relation shards until AI-judged base_refs land, then remove the gate.
    RELATIONS_WITHDRAWN = True
    for cid, t in tmeta.items():
        if RELATIONS_WITHDRAWN:
            break
        strict = isinstance(t.get("base_refs"), list)
        parent_ids = t["base_refs"] if strict else t["refs"]
        for pid in parent_ids:
            if pid == cid:
                continue
            if not strict:
                pcat = ((tmeta.get(pid) or {}).get("category") or {}).get("name")
                if pcat in dependency_cats:
                    continue
            children.setdefault(pid, []).append(cid)
    NSH = 8
    shards = [dict() for _ in range(NSH)]
    for pid, kids in children.items():
        kids.sort(key=lambda c: (-likes_of.get(c, 0), c))
        try:
            shards[int(pid) % NSH][pid] = [len(kids), kids[:2000]]
        except ValueError:
            continue
    for i, sh in enumerate(shards):
        (OUT / f"relations_children_{i}.json").write_text(
            json.dumps(sh, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("relations: parents with children", len(children), file=sys.stderr)
    print("index", len(index), file=sys.stderr)
    print("sizes: lists_full", (OUT / "lists_full.json").stat().st_size // 1024, "KB / search_index",
          (OUT / "search_index_0.json").stat().st_size // 1024, "KB", file=sys.stderr)
    return visibility_evidence


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--tracker-meta-dir", type=Path, required=True)
    p.add_argument("--metadata-file", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--daily-coverage-file", type=Path)
    p.add_argument("--daily-target-date")
    a = p.parse_args()
    coverage = None
    if a.daily_coverage_file:
        import tempfile
        a.output_dir.parent.mkdir(parents=True, exist_ok=True)
        private = Path(tempfile.mkdtemp(prefix='.' + a.output_dir.name + '-daily-input-', dir=a.output_dir.parent))
        coverage, _ = read_daily_coverage(a.daily_coverage_file, private)
    build(a.data_dir, a.tracker_meta_dir, a.output_dir, a.metadata_file,
          daily_coverage=coverage, daily_target_date=a.daily_target_date)


if __name__ == "__main__":
    main()

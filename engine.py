"""Duplicate-call clustering and priority triage engine (stdlib only).

Pipeline per call:  geocode -> classify incident type -> priority score -> cluster.
Every decision carries human-readable reasons so dispatchers can verify and undo it.
"""
import math
import re

# ---------------------------------------------------------------- config
DUP_THRESHOLD = 0.60          # pair score needed to join an existing incident
TIME_WINDOW_MIN = 40          # time-proximity decay window
GEO_SLACK_M = 300             # distance beyond summed accuracy radii before geo score hits 0
SAME_CALLER_WINDOW_MIN = 45   # same caller within this window = update to same incident
LEVELS = {"P1": 5, "P2": 3, "P3": 1}   # min points; below -> P4
CLUSTER_SIZE_BUMPS = [(10, 2), (5, 1)]  # (distinct callers, levels to escalate)

# Spoken landmarks the caller may mention (stand-in for a real geocoder).
GAZETTEER = {
    "5th and oak": (40.7128, -74.0060),
    "lincoln high": (40.7326, -73.9815),
    "highway 9 overpass": (40.7200, -74.0390),
    "riverside apartments": (40.6903, -73.9942),
    "mill creek bridge": (40.6858, -74.0280),
}

STOP = set("a an the is are was were be to of in on at and or but my our i im ive its it this that there "
           "with for from by as we you he she they them his her please hurry help can cant just really "
           "very some now me can't".split())
SYN = {"collision": "crash", "collided": "crash", "wreck": "crash", "accident": "crash", "blaze": "fire",
       "flames": "fire", "burning": "fire", "vehicles": "car", "cars": "car", "vehicle": "car",
       "truck": "car", "gunshots": "shots", "shooting": "shots", "shot": "shots", "gunman": "shooter",
       "kids": "child", "kid": "child", "children": "child", "baby": "child", "infant": "child",
       "flooded": "flood", "submerged": "water", "river": "water", "creek": "water", "bridge": "bridge"}

# incident type vocabulary; order = precedence on ties
TYPE_WORDS = {
    "violence": {"gun", "shots", "shooter", "weapon", "knife", "fight", "stabbed", "armed", "gunfire", "gunshots", "hostage"},
    "fire": {"fire", "smoke", "flames", "burning", "blaze"},
    "crash": {"crash", "collision", "collided", "accident", "wreck", "rollover", "fender"},
    "water": {"flood", "water", "drowning", "submerged", "creek"},
    "hazmat": {"gas", "chemical", "fumes"},
    "medical": {"breathing", "unconscious", "heart", "chest", "collapsed", "seizure", "choking", "bleeding",
                "pulse", "dizzy", "dying", "die"},
}

# ---- priority vocabulary: phrase/word -> (points, label). Phrases are matched first and are never negated.
PHRASES = {
    "not breathing": (6, "not breathing"), "isnt breathing": (6, "not breathing"),
    "stopped breathing": (6, "not breathing"), "no pulse": (6, "no pulse"),
    "not responding": (4, "unresponsive"), "not moving": (3, "not moving"),
    "cant breathe": (5, "cant breathe"), "cant get out": (3, "trapped (can't get out)"),
    "cannot get out": (3, "trapped (can't get out)"), "gun shots": (5, "gunfire"),
    "people inside": (3, "people inside"), "someone inside": (3, "people inside"),
    "gas leak": (3, "gas leak"), "chest pain": (4, "chest pain"), "shots fired": (6, "shots fired"),
    "heavily bleeding": (4, "heavy bleeding"), "bleeding badly": (4, "heavy bleeding"),
    "dont know what to do": (2, "distress: doesn't know what to do"), "going to die": (5, "distress: going to die"),
    "gonna die": (5, "distress: going to die"), "oh my god": (1, "distress: panic"),
    "please help": (2, "distress: pleading for help"), "need help": (2, "distress: needs help"),
    "cant think": (1, "distress: panic"), "i am scared": (1, "distress: fear"), "im scared": (1, "distress: fear"),
}
WORDS = {
    "weapon": (5, "weapon"), "gun": (5, "gun"), "knife": (5, "knife"), "shots": (5, "gunfire"), "gunshots": (5, "gunfire"), "gunfire": (5, "gunfire"),
    "dying": (5, "dying"), "die": (3, "fear of dying"), "panic": (2, "distress: panic"),
    "panicking": (2, "distress: panic"), "scared": (1, "distress: fear"), "terrified": (2, "distress: terror"),
    "help": (1, "distress: calling for help"), "wreck": (2, "wreck"), "rollover": (2, "rollover"),
    "shooter": (6, "shooter"), "hostage": (6, "hostage"), "armed": (5, "armed person"),
    "stabbed": (5, "stabbing"), "explosion": (5, "explosion"), "drowning": (5, "drowning"),
    "choking": (5, "choking"), "trapped": (4, "trapped"), "unconscious": (4, "unconscious"),
    "seizure": (3, "seizure"), "bleeding": (3, "bleeding"), "fire": (2, "fire"), "flames": (2, "flames"),
    "smoke": (1, "smoke"), "crash": (2, "crash"), "collision": (2, "collision"), "flood": (2, "flooding"),
    "fight": (1, "fight"), "collapsed": (3, "collapse"), "overdose": (5, "overdose"),
}
VULNERABLE = {"child", "baby", "infant", "toddler", "elderly", "pregnant", "wheelchair", "kids", "children", "kid"}
CRITICAL_PLACES = ("school", "hospital", "nursing home", "stadium", "daycare", "kindergarten", "lincoln high")
HAZARD_TERMS = {"weapon", "gun", "knife", "shots", "shooter", "explosion", "fire", "flames", "smoke", "crash",
                "collision", "flood", "drowning", "trapped", "fight", "armed", "stabbed", "hostage"}
NEGATORS = {"no", "not", "without", "never", "nobody", "isnt", "wasnt", "dont", "doesnt", "neither", "nor"}
BENIGN = {"movie", "tv", "film", "game", "prank", "barbecue", "bbq", "laughing", "fireworks", "video"}
ACCIDENTAL = ("pocket", "butt dial", "butt-dial", "wrong number", "dialed by accident", "sorry my phone")
AUDIO_PTS = {"whisper": (2, "whispering caller"), "screaming": (2, "caller screaming"),
             "silent": (1, "open line, no speech (callback needed)"),
             "gunfire_bg": (4, "gunfire audible in background")}


# ---------------------------------------------------------------- helpers
def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def clean(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("'", "").replace("’", ""))


def tokens(text):
    return clean(text).split()


def canon_tokens(text):
    return {SYN.get(t, t) for t in tokens(text) if t not in STOP and len(t) > 1}


def dice(a, b):
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


# ---------------------------------------------------------------- enrichment
def geocode(call):
    """Prefer a spoken landmark over the phone's location when the phone is clearly elsewhere or imprecise."""
    text = clean(call["transcript"])
    lat, lon, acc, src = call["lat"], call["lon"], call["accuracy_m"], "phone"
    for name, (glat, glon) in GAZETTEER.items():
        if name in text:
            if acc > 300 or haversine_m(lat, lon, glat, glon) > 500:
                return glat, glon, 60, "spoken address: " + name
            break
    return lat, lon, acc, src


def classify_type(text):
    """Return (primary type, set of all types mentioned)."""
    toks = set(tokens(text))
    best, best_n, seen = "other", 0, set()
    for t, words in TYPE_WORDS.items():
        n = len(toks & words)
        if n:
            seen.add(t)
        if n > best_n:
            best, best_n = t, n
    return best, seen or {"other"}


def score_priority(call):
    text = clean(call["transcript"])
    toks = text.split()
    points, reasons, hits = 0, [], set()

    for phrase, (pts, label) in PHRASES.items():          # phrases first, consumed so words can't double count
        if phrase in text:
            points += pts
            reasons.append(f"{label} (+{pts})")
            text = text.replace(phrase, " ")
    toks = text.split()
    for i, t in enumerate(toks):
        if t in WORDS:
            pts, label = WORDS[t]
            if NEGATORS & set(toks[max(0, i - 6):i]):
                reasons.append(f"'{t}' negated - ignored")
                continue
            points += pts
            hits.add(t)
            reasons.append(f"{label} (+{pts})")

    vulnerable = VULNERABLE & set(toks)
    if vulnerable:
        points += 2
        reasons.append(f"vulnerable person: {sorted(vulnerable)[0]} (+2)")
        if hits & HAZARD_TERMS:
            points += 1
            reasons.append("hazard + vulnerable person (+1)")
    place = [p for p in CRITICAL_PLACES if p in clean(call["transcript"])]
    if place:
        points += 2
        reasons.append(f"critical location: {place[0]} (+2)")
    audio = call.get("audio")
    if audio in AUDIO_PTS:
        pts, label = AUDIO_PTS[audio]
        points += pts
        reasons.append(f"{label} (+{pts})")
    if BENIGN & set(toks):
        points = min(points, 0)
        reasons.append("benign context (movie/bbq/etc.) - suppressed")
    return points, reasons


def level_for(points):
    for name, floor in LEVELS.items():
        if points >= floor:
            return name
    return "P4"


def enrich(call):
    c = dict(call)
    c["lat_used"], c["lon_used"], c["acc_used"], c["loc_source"] = geocode(call)
    c["type"], c["types"] = classify_type(call["transcript"])
    c["toks"] = canon_tokens(call["transcript"])
    c["points"], c["reasons"] = score_priority(call)
    c["accidental"] = any(k in call["transcript"].lower() for k in ACCIDENTAL)
    c["level"] = level_for(c["points"])
    return c


# ---------------------------------------------------------------- duplicate scoring
def pair_score(a, b, cluster_types=None):
    d = haversine_m(a["lat_used"], a["lon_used"], b["lat_used"], b["lon_used"])
    slack = max(0.0, d - (a["acc_used"] + b["acc_used"]))
    geo = max(0.0, 1 - slack / GEO_SLACK_M)
    if max(a["acc_used"], b["acc_used"]) > 300:           # cell-tower fix: location is weak evidence
        geo *= 0.4
    dt = abs(a["t"] - b["t"])
    time = max(0.0, 1 - dt / TIME_WINDOW_MIN)
    # compatibility is judged against the whole incident's type profile, so a vague "other" call can't bridge
    # two unrelated emergencies
    known = cluster_types or b["types"]
    if a["types"] == {"other"} or known == {"other"}:
        compat, type_s = True, 0.7
    else:
        compat = bool(a["types"] & known)
        type_s = 1.0 if compat else 0.0
    text = min(1.0, dice(a["toks"], b["toks"]) / 0.35)
    score = 0.40 * geo + 0.15 * time + 0.20 * type_s + 0.25 * text
    if not compat:
        score *= 0.3                                       # different kind of emergency: never auto-merge
    same_caller = a["caller"] == b["caller"] and dt <= SAME_CALLER_WINDOW_MIN
    if same_caller:
        score = max(score, 0.5) + 0.25
    return score, {"dist_m": round(d), "geo": round(geo, 2), "time": round(time, 2),
                   "type": type_s, "text": round(text, 2), "same_caller": same_caller}


def cl_types(cl):
    t = set().union(*(m["types"] for m in cl["members"])) - {"other"}
    return t or {"other"}


def process(raw_calls):
    calls = sorted((enrich(c) for c in raw_calls), key=lambda c: c["t"])
    clusters = []
    for c in calls:
        c["cluster"], c["match"] = None, None
        if c["accidental"]:
            continue
        best, best_cl, best_member = 0.0, None, None
        for cl in clusters:
            for m in cl["members"]:
                s, detail = pair_score(c, m, cl_types(cl))
                if s > best:
                    best, best_cl, best_member, best_detail = s, cl, m, detail
        if best >= DUP_THRESHOLD:
            best_cl["members"].append(c)
            c["cluster"] = best_cl["id"]
            c["match"] = {"with": best_member["id"], "score": round(min(best, 1.0), 2), **best_detail}
        else:
            cl = {"id": len(clusters) + 1, "members": [c]}
            clusters.append(cl)
            c["cluster"] = cl["id"]
    return calls, clusters


def label_place(lat, lon):
    best, best_d = "Unlabeled area", 600
    for name, (glat, glon) in GAZETTEER.items():
        d = haversine_m(lat, lon, glat, glon)
        if d < best_d:
            best, best_d = name.title().replace("5Th", "5th"), d
    return best


def export(calls, clusters):
    """Plain-JSON payload for the dashboard (clients aggregate per time slice)."""
    out_calls = []
    for c in calls:
        out_calls.append({k: c[k] for k in ("id", "t", "caller", "transcript", "audio", "type", "points", "level",
                                            "reasons", "accidental", "cluster", "match", "loc_source")}
                         | {"lat": c["lat_used"], "lon": c["lon_used"], "acc": c["acc_used"]})
    out_clusters = []
    for cl in clusters:
        m = cl["members"]
        lat = sum(x["lat_used"] for x in m) / len(m)
        lon = sum(x["lon_used"] for x in m) / len(m)
        out_clusters.append({"id": cl["id"], "place": label_place(lat, lon)})
    return {"calls": out_calls, "clusters": out_clusters,
            "config": {"levels": LEVELS, "size_bumps": CLUSTER_SIZE_BUMPS, "threshold": DUP_THRESHOLD,
                       "vocab": vocab()}}


def vocab():
    """Shared vocabulary so the browser (live voice intake) scores calls exactly like the Python engine."""
    return {"phrases": PHRASES, "words": WORDS, "vulnerable": sorted(VULNERABLE), "critical": list(CRITICAL_PLACES),
            "hazard": sorted(HAZARD_TERMS), "negators": sorted(NEGATORS), "benign": sorted(BENIGN),
            "accidental": list(ACCIDENTAL), "stop": sorted(STOP), "syn": SYN,
            "type_words": {k: sorted(v) for k, v in TYPE_WORDS.items()}, "gazetteer": GAZETTEER}

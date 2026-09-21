# -*- coding: utf-8 -*-
"""Engine: turns an ODM console into progress with a remaining time.

Three sources, in order of reliability:

1. Stage markers (`Running X stage` / `Finished X stage`). These always say
   exactly where the task is and which stages are done. They never fail.

2. Step lines inside OpenSfM: one per image with features, one per matched pair,
   one per image added to the reconstruction, one per undistorted image. This is
   where the fine percentage and the rate come from.

3. Files on disk, for stages that log no progress at all. OpenMVS writes one
   .dmap per image and says nothing in the console; counting those files is the
   only fine signal there is. Local node only — the task's working directory is
   extracted from the console itself.

The per-stage weights drive the overall percentage. They start at typical values
and are replaced by measured durations as stages complete, so the estimate
corrects itself as the task goes on.
"""
import os
import re
import datetime

# ODM 3.x pipeline order, with each stage's typical share of the total time.
# The weights are a starting point: finished stages switch to their measured
# duration.
STAGES = [
    ("dataset", 3.0),
    ("split", 0.2),
    ("merge", 0.2),
    ("opensfm", 40.0),
    ("openmvs", 30.0),
    ("odm_filterpoints", 2.0),
    ("odm_meshing", 8.0),
    ("mvs_texturing", 10.0),
    ("odm_georeferencing", 2.0),
    ("odm_dem", 2.0),
    ("odm_orthophoto", 2.0),
    ("odm_report", 0.2),
    ("odm_postprocess", 0.2),
]
ORDER = [n for n, _ in STAGES]
WEIGHTS = dict(STAGES)

# Countable steps inside OpenSfM, with each one's weight within the stage.
SFM_STEPS = [
    ("features",       15.0, None,                          r"Extracting ROOT_HAHOG"),
    ("matching",       55.0, r"Matching (\d+) image pairs", r"Matcher: (?:WORDS|FLANN|BRUTEFORCE)"),
    ("reconstruction", 20.0, None,                          r"Adding .+ to the reconstruction"),
    ("undistort",      10.0, None,                          r"Undistorting image"),
]
SFM_COMPILED = [(n, w, re.compile(t) if t else None, re.compile(s))
                for n, w, t, s in SFM_STEPS]
# Steps whose total is the image count rather than something the console states
PER_IMAGE = ("features", "reconstruction", "undistort")

RE_START = re.compile(r"Running ([a-z0-9_]+) stage")
RE_END = re.compile(r"Finished ([a-z0-9_]+) stage")
RE_IMAGES = re.compile(r"Loading (\d+) images")
# ODM echoes every command with the task folder's absolute path; that is how we
# find where to look for OpenMVS files.
RE_WORKDIR = re.compile(r'"((?:[A-Za-z]:\\|/)[^"]*?[\\/]data[\\/][0-9a-fA-F-]{36})[\\/]')
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})")
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S,%f"


def new_state():
    return {
        "cursor": 0, "images": None, "workdir": None,
        "stage": None, "done": [], "started": {}, "ended": {},
        "counts": {}, "totals": {}, "first": {}, "last": {},
        "source": None, "heals": 0,
    }


def consume(state, lines):
    """Fold new console lines into the state."""
    for line in lines:
        m = RE_START.search(line)
        if m:
            state["stage"] = m.group(1)
            s = STAMP.match(line)
            if s:
                state["started"].setdefault(m.group(1), s.group(1))
            continue
        m = RE_END.search(line)
        if m:
            if m.group(1) not in state["done"]:
                state["done"].append(m.group(1))
            s = STAMP.match(line)
            if s:
                state["ended"][m.group(1)] = s.group(1)
            continue
        m = RE_IMAGES.search(line)
        if m:
            state["images"] = int(m.group(1))
        if state["workdir"] is None:
            m = RE_WORKDIR.search(line)
            if m:
                state["workdir"] = m.group(1)

        for name, _weight, re_total, re_step in SFM_COMPILED:
            if re_total is not None:
                mt = re_total.search(line)
                if mt:
                    state["totals"][name] = max(state["totals"].get(name, 0),
                                                int(mt.group(1)))
            if re_step.search(line):
                state["counts"][name] = state["counts"].get(name, 0) + 1
                s = STAMP.match(line)
                if s:
                    state["first"].setdefault(name, s.group(1))
                    state["last"][name] = s.group(1)


def _seconds(a, b):
    try:
        return (datetime.datetime.strptime(b, STAMP_FORMAT) -
                datetime.datetime.strptime(a, STAMP_FORMAT)).total_seconds()
    except (ValueError, TypeError):
        return None


def _depthmaps(state):
    """Dense stage progress: one .dmap per image, counted on disk.

    OpenMVS logs nothing during this stage, which is usually the longest one
    after matching. Local node only.
    """
    if not state["workdir"] or not state["images"]:
        return None
    folder = os.path.join(state["workdir"], "opensfm", "undistorted",
                          "openmvs", "depthmaps")
    if not os.path.isdir(folder):
        return None
    try:
        n = sum(1 for f in os.listdir(folder) if f.endswith(".dmap"))
    except OSError:
        return None
    return n, state["images"]


def _step(state, name, fallback_total=None):
    done = state["counts"].get(name, 0)
    total = state["totals"].get(name) or fallback_total
    d = {"key": name, "done": done, "total": total,
         "pct": None, "rate": None, "remaining_s": None}
    if done and total:
        d["pct"] = round(100.0 * min(done, total) / total, 1)
    if done > 20 and name in state["first"]:
        s = _seconds(state["first"][name], state["last"][name])
        if s and s > 1:
            rate = done / s
            d["rate"] = round(rate, 2)
            if total and total > done:
                d["remaining_s"] = int((total - done) / rate)
    return d


def summarize(state, now=None):
    """Current stage, steps, overall percentage and remaining time."""
    now = now or datetime.datetime.now()

    # Weights: measured duration where known, typical value elsewhere. This is
    # what makes the overall estimate correct itself during the task.
    weights = dict(WEIGHTS)
    measured = {}
    for name in state["done"]:
        s = _seconds(state["started"].get(name), state["ended"].get(name))
        if s is not None and s > 0:
            measured[name] = s
    if measured:
        # rescale the measurements onto the same scale as the typical weights
        typical = sum(WEIGHTS[n] for n in measured if n in WEIGHTS) or 1.0
        actual = sum(measured.values())
        if actual > 0:
            for n, s in measured.items():
                weights[n] = s / actual * typical

    stage = state["stage"]
    steps = []
    within = 0.0        # fraction of the current stage already done

    if stage == "opensfm":
        acc = 0.0
        for name, weight, _rt, _rs in SFM_STEPS:
            step = _step(state, name,
                         fallback_total=state["images"] if name in PER_IMAGE else None)
            step["weight"] = weight
            steps.append(step)
            acc += weight * (step["pct"] or 0.0) / 100.0
        within = acc / sum(w for _, w, _, _ in SFM_STEPS)
    elif stage == "openmvs":
        d = _depthmaps(state)
        if d:
            done, total = d
            steps.append({"key": "openmvs", "done": done, "total": total,
                          "pct": round(100.0 * min(done, total) / total, 1),
                          "rate": None, "remaining_s": None, "weight": 100.0})
            within = min(done / total, 1.0)

    done_weight = sum(weights.get(n, 0.0) for n in state["done"])
    if stage and stage not in state["done"]:
        done_weight += weights.get(stage, 0.0) * within
    total_weight = sum(weights.get(n, 0.0) for n in ORDER) or 1.0
    pct = round(100.0 * done_weight / total_weight, 1)

    # Remaining: the current step's estimate when there is one, otherwise
    # extrapolated from the task's overall rate so far.
    remaining = next((s["remaining_s"] for s in steps
                      if s.get("remaining_s") is not None and (s["pct"] or 0) < 100),
                     None)
    if remaining is None and pct > 1 and state["started"]:
        first = min(state["started"].values())
        elapsed = _seconds(first, now.strftime(STAMP_FORMAT)[:-3])
        if elapsed and elapsed > 60:
            remaining = int(elapsed * (100.0 - pct) / pct)

    eta = None
    if remaining:
        eta = (now + datetime.timedelta(seconds=remaining)).strftime("%H:%M")

    return {
        "stage": stage,
        "done": list(state["done"]),
        "order": ORDER,
        "steps": steps,
        "pct": pct,
        "remaining_s": remaining,
        "eta": eta,
        "images": state["images"],
        "source": state["source"],
        "heals": state["heals"],
    }

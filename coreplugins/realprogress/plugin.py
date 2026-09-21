# -*- coding: utf-8 -*-
"""Real Progress — true percentage and remaining time for WebODM tasks.

WebODM shows `running_progress`, which ODM only updates at stage boundaries: a
task sits at 4% for two hours and then jumps. The fine-grained progress does
exist, but only in the console — one line per matched pair, per processed image,
per image added to the reconstruction.

This module handles the WebODM side: fetching the console, keeping per-task
state and serving the endpoint. The analysis lives in progress.py and the
strings in translations.py.

Two decisions worth explaining:

1. The console comes from the NODE, not from the local file. WebODM keeps a copy
   in data/.../console_output.txt, but that copy can freeze (see _heal_console)
   while the work carries on. Asking the node is always the truth; the local file
   is the fallback for when the node cannot be reached.

2. Reading is INCREMENTAL, with a line cursor per task. A large task's console
   goes past 20 MB and re-reading it every 5 seconds would be absurd.
"""
import os
import json
import time

from urllib.request import urlopen
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils.translation import get_language

from app.plugins import PluginBase, MountPoint

from .progress import new_state, consume, summarize
from .translations import strings

POLL_INTERVAL = 4.0     # seconds between node queries
STALL_SECONDS = 180.0   # WebODM console not growing while the node produces

_state = {}


def _lines_from_node(task, since):
    node = task.processing_node
    if not node or not task.uuid:
        return None
    url = "http://{}:{}/task/{}/output?token={}&line={}".format(
        node.hostname, node.port, task.uuid, quote(node.token or ""), since)
    with urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if isinstance(data, str):
        data = data.splitlines()
    return [l for l in data if l]


def _lines_from_file(task, since):
    path = task.data_path("console_output.txt")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return [l.rstrip("\n") for i, l in enumerate(f) if i >= since]


def _heal_console(task):
    """Unstick WebODM's console sync.

    WebODM decides where to resume by counting the lines it already stored
    (app/models/task.py). If a task is re-run on the node, the node's line
    numbering goes back to zero and WebODM keeps asking for a line that no longer
    exists; the node returns an empty list with no error, the file never grows,
    the offset never changes — and the console is frozen forever while the task
    keeps processing. Reported as github.com/WebODM/WebODM/issues/2027.

    Detected by the only reliable signature: the node is producing new lines
    while WebODM's file has not been touched for minutes. Truncating the file
    puts the offset back to zero and sync resumes on the next cycle.
    """
    try:
        path = task.data_path("console_output.txt")
        if not os.path.isfile(path):
            return False
        if time.time() - os.path.getmtime(path) < STALL_SECONDS:
            return False
        task.console.reset()
        return True
    except Exception:
        return False


def _update(task):
    key = str(task.id)
    state = _state.get(key)
    if state is None:
        state = _state[key] = new_state()

    now = time.time()
    if now - state.get("polled_at", 0) < POLL_INTERVAL:
        return state
    state["polled_at"] = now

    lines, source = None, None
    try:
        lines = _lines_from_node(task, state["cursor"])
        source = "node"
        # If the task was re-run on the node, its line numbering restarted and
        # our cursor now points past the end: ask for everything and compare.
        # The full read is only paid for in this case.
        if not lines and state["cursor"] > 0:
            everything = _lines_from_node(task, 0)
            if everything is not None and len(everything) < state["cursor"]:
                heals = state["heals"]
                _state[key] = state = new_state()
                state["heals"] = heals
                state["polled_at"] = now
                lines = everything
    except Exception:
        lines = None

    if lines is None:
        try:
            lines = _lines_from_file(task, state["cursor"])
            source = "file"
        except Exception:
            lines = None

    if lines:
        consume(state, lines)
        state["cursor"] += len(lines)
        state["source"] = source
        if source == "node" and _heal_console(task):
            state["heals"] += 1
    elif source:
        state["source"] = source
    return state


def _translate(summary, s):
    """Swap internal keys for the active language's strings."""
    out = dict(summary)
    out["stage_label"] = s.get(summary["stage"], summary["stage"]) if summary["stage"] else None
    out["steps"] = [dict(step, label=s.get(step["key"], step["key"]))
                    for step in summary["steps"]]
    out["stages"] = [{"key": n, "label": s.get(n, n),
                      "done": n in summary["done"], "current": n == summary["stage"]}
                     for n in summary["order"]]
    out["words"] = {k: s[k] for k in ("remaining", "eta", "of")}
    return out


class Plugin(PluginBase):
    def include_js_files(self):
        return ["main.js"]

    def include_css_files(self):
        return ["style.css"]

    def api_mount_points(self):
        from app.models import Task

        @login_required
        def status(request):
            s = strings(get_language())
            out = {}
            for task in Task.objects.filter(status=20):      # 20 = RUNNING
                try:
                    out[str(task.id)] = dict(
                        _translate(summarize(_update(task)), s),
                        name=task.name or ("Task #%s" % task.id))
                except Exception as exc:
                    out[str(task.id)] = {"error": str(exc)}
            return JsonResponse({"tasks": out, "language": get_language()})

        return [MountPoint("status", status)]

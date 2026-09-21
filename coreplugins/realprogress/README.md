# Real Progress — true progress and ETA for WebODM

WebODM shows `running_progress`, which ODM only updates at stage boundaries. A
task sits at 4% for two hours and then jumps. There is no way to tell whether it
is halfway through matching or nearly done, and no way to know when it will
finish.

The fine-grained progress does exist — but only in the console, one line per
matched pair, per processed image, per image added to the reconstruction. This
plugin reads that console, counts the steps of each stage, measures the rate,
and puts the real percentage and the remaining time on the task list.

Before:

```
Running
```

After:

```
6.3% · Camera positions · 11,298 of 84,666 · remaining 2h13
```

Hovering the label lists all 13 ODM stages with their state, the counts and
rates of each sub-step, and the estimated finish time.

## Install

**From the interface** — Administration → Plugins → *Load Plugin (.zip)*, pick
`realprogress.zip`.

**By hand** — copy the `realprogress` folder into WebODM's `coreplugins`
directory (or, on a desktop install, into `data/media/plugins`), then restart
WebODM. If it does not show up under Administration → Plugins, create its
database record:

```python
from app.models import Plugin
p, _ = Plugin.objects.get_or_create(name='realprogress')
p.enabled = True
p.save()
```

No configuration. It applies to every running task.

## How it works

Three sources, in order of reliability:

1. **Stage markers** (`Running X stage` / `Finished X stage`). These always say
   exactly where the task is and which stages are done. They never fail.

2. **Step lines inside OpenSfM** — one per image with features, one per matched
   pair, one per image added to the reconstruction, one per undistorted image.
   This is where the fine percentage and the rate come from.

3. **Files on disk**, for stages that log no progress at all. OpenMVS writes one
   `.dmap` per image and says nothing in the console; counting those files is the
   only fine signal there is. Local node only — the task's working directory is
   extracted from the console itself.

The stage weights behind the overall percentage start at typical values and are
replaced by measured durations as stages complete, so the estimate corrects
itself as the task goes on.

Reading is incremental: a line cursor per task, only new lines requested. A large
task's console goes past 20 MB and re-reading it every 5 seconds would be absurd.

## It also works around a WebODM bug

`Task.process()` asks the node for console output starting at an offset derived
from the console it already stored. If the node's output ever becomes *shorter*
than that offset — which happens when a task is re-run on the node — NodeODM
returns an empty list with no error, the stored console never grows, the offset
never changes, and console sync is stuck permanently while the task keeps
processing. Reported as
[WebODM#2027](https://github.com/WebODM/WebODM/issues/2027).

This plugin reads the console from the node rather than from WebODM's copy, so it
is unaffected. It also detects the stall — the node is producing new lines while
WebODM's file has not been touched for minutes — and resets the stored console so
normal sync resumes.

## Languages

Strings are translated server side, following WebODM's active language:

`en` `pt` `pt-br` `es` `fr` `de` `it` `nl` `pl` `ru` `uk` `tr` `cs` `sv` `el`
`zh-hans` `zh-hant` `ja` `ko`

Anything else falls back to English. Adding a language means copying one block in
`translations.py` and translating thirteen short strings — no `.po` files, no
compilation step.

## Files

| | |
|---|---|
| `plugin.py` | WebODM integration: fetching the console, per-task state, the endpoint |
| `progress.py` | the engine: parsing, counting, rates, weights, ETA |
| `translations.py` | the strings, one block per language |
| `public/main.js` | repaints the status label; the React list re-renders, so it repaints every cycle and on DOM changes |
| `public/style.css` | the label needs more width now |

## Limitations

- The dense point cloud stage only gets a fine percentage when the node runs on
  the same machine, because it is counted from files on disk.
- Rows are matched to tasks by name: while a task is running, the name is the
  only identifier present in the DOM.
- Stage markers were verified against ODM 3.x. Other versions may log
  differently; unknown stages degrade to the stage name alone, never to an error.

## License

AGPL-3.0, same as WebODM.

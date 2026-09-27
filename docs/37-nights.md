# The failures your agent will never log

*37 nights of a scheduled Claude Code agent, measured from outside the process.*

My night agent has never reported a failure. Not once, across 65 daily journals.

It delivered a report on 22 of the last 37 nights.

Both statements are true, and the gap between them is the subject of this
document. It is not a bug in the agent. It is a property of where the failure
reporting lives.

## The system, briefly

A Windows scheduled task fires at 00:30 and runs a wrapper around `claude -p`.
The agent reads a 36-hour window of a Markdown vault, consolidates it, and must
finish by printing a proof line. The wrapper enforces that window, a lock, a
timeout and one retry, appends a health block to the day's journal, and updates
a `state.json`. The task itself is set to wake the machine and to catch up after
a missed start — that turns out to matter, and not enough. Four other jobs run
on a schedule around it: two capture runs, a backup, a profile rebuild.

You do not need my vault to read the rest. The shape is what matters: a
scheduled process on a personal machine, driving an LLM CLI, writing files, and
reporting on itself.

## What was already right: the proof line

Before the failures, the one design decision that held up.

A zero exit code does not mean an agent did its job. An LLM can be handed a
prompt, decide there is nothing to do, say so politely, and exit clean. The
process succeeded. The work did not happen. If your scheduler treats exit 0 as
"done", you cannot tell those apart — and the quiet one looks exactly like the
good one.

So the run does not count as done unless the agent emits, as its last line:

```
NIGHTSHIFT_OK <journal> notes=N links=N proposals=N
```

The wrapper greps for it. No line, no success, whatever the exit code says.
The counters are not decoration either: `notes=0 links=0 proposals=0` is a
night that ran and achieved nothing, which is a different problem from a night
that crashed, and you want to be able to see the difference in the morning.

This is the part I would keep in any rewrite. Make the worker assert what it
did, in a form the parent can check, and refuse to infer success from the
absence of an error.

It also turned out to be insufficient, in a way I did not anticipate: it proves
a run finished, and it cannot say anything at all about a run that stopped
existing. More on that below.

## Failure 1: the exit code lied, in both directions, two days apart

The agent's run ends by publishing a small status asset to a repository. Same
script, same `git push`, two nights apart:

| | 2026-09-24 | 2026-09-26 |
|---|---|---|
| `git push` reported | success | failure |
| GitHub had the commit | **no** | **yes** |
| The system recorded | published | failed |

The first is the boring one: a push that reports success and does not land. The
scheduled task printed "published", and the commit sat in the local repository
for a day.

The second is more instructive. `git push` writes its progress to stderr — not
because anything is wrong, that is just where git puts it. Under PowerShell
with `$ErrorActionPreference = "Stop"`, redirecting that into the pipeline turns
ordinary output into a `NativeCommandError`. The script concluded the push had
failed and wrote a warning into the day's journal. The push had worked. The
warning was false, and I only caught it because I went and looked at the
repository by hand.

So within 48 hours, the same three lines of script produced a false success and
a false failure. The fix is not better error handling around the command. It is
to stop asking the command:

```
git ls-remote origin refs/heads/main      # ask the remote what it actually has
```

and compare that SHA to the local one. Commit `e745971` — *only claim the night
is published once GitHub has it.*

**Generalised:** verify the effect, not the return value. A process reporting on
its own side effects is a witness with an interest in the outcome. Anything that
crosses a boundary — a network, a disk, another machine — should be confirmed on
the far side of that boundary.

## Failure 2: the log that stops mid-sentence

Here is `run_2026-09-16_0030.log`, in full:

```
=== Nightly run 2026-09-16_0030 (PID 60200) ===
00:30:27 journal=2026-09-15 since=2026-09-14T12:30:26 model=claude-sonnet-5
00:30:27 tentative 1 : /nightly-agent --since 2026-09-14T12:30:26 --journal 2026-09-15 --run-id 2026-09-16_0030_1
```

Three lines. That is the entire file — no error, no status line, no retry, no
`=== fin ===`. The run from later that same day is one line: the header, and
nothing after it.

This is worth being precise about, because it is easy to file under "it
crashed". It did not crash. A crash runs code: it unwinds, it writes to stderr,
it sets an exit code, and every one of those is something you can catch and
log. This process stopped between two writes to a file it had open.

Which means:

- The `try/catch` never ran.
- The retry never ran — it did not fail, it was never reached.
- The timeout never fired — the thing that was supposed to be timed had no
  process left to time.
- The proof line was never going to appear, and the absence of the proof line
  was never going to be noticed, because the code that checks for it is in the
  same process.

The only evidence that this night went wrong is that the file ends where it
does. **The failure signal is the absence of a line** — and absence is the one
signal a program cannot emit about itself.

Four of thirty runs, across two nights, look like this.

## Failure 3: the nights that never started

Ten of the 37 nights have no log file at all:

```
2026-08-23  2026-08-25  2026-08-27  2026-08-28  2026-09-03
2026-09-05  2026-09-06  2026-09-12  2026-09-19  2026-09-20
```

No log file is a strong claim here, because the runner opens its log on line 34,
before every guard it has — before the maintenance lock, before the window
calculation, before anything that could make it exit early. A run that started
and immediately decided to do nothing still leaves a file. So an absent file
means the process never started.

**The obvious objection is already handled, and it was not enough.** The
scheduled task is configured the way you would configure it:

```
WakeToRun          : True     # wake the machine for this
StartWhenAvailable : True     # run it late if the start was missed
DisallowStartIfOnBatteries : False
Triggers           : daily 00:30  +  at logon
```

That catch-up is not theoretical. Eleven of the thirty runs fired outside the
00:00–01:30 window — at 09:18, 10:05, 11:45, 16:19, 04:11. Those are the
scheduler recovering missed starts, and they worked.

It still lost ten nights, because `WakeToRun` wakes a sleeping machine and a
shut-down one has nothing listening, and because catch-up can only run once the
machine comes back — which, across a four-day gap, is too late to be the same
night.

**How much was actually lost is smaller than ten.** The runner consolidates a
36-hour window, not a calendar day, so a single missed night is usually absorbed
by the next run. Checking each dark night against the `since=` value of the next
successful run:

| | Nights |
|---|---|
| Absorbed by the next run's 36h window | 3 |
| Outside the window — genuinely lost | 3 |
| Indeterminate (pre-rewrite logs record no `since`) | 4 |

The three genuine losses are consecutive: 2026-09-03, 09-05 and 09-06, closed by
a run on 09-07 whose window only reached back to 09-06 04:19. One dark night is
an inconvenience. Four in five days is a hole.

So: 27% of nights produced no report, and at least 8% lost data outright. The
first number is what the system was blind to. The second is what it cost.

## The blind spot, named

I want to be clear that I had built the right mechanism. It is in the README,
under the design decisions: *"If that line is missing, the runner writes a
failure line into your journal, so in the morning 'nothing to do' is never
confused with 'didn't run'."* It is tested. It works.

It has written that line zero times — not once since the 2026-09-07 rewrite
that introduced it, and not anywhere in the 65 journals in the archive.

Go back to the truncated run from 2026-09-16. Its second line records the file
it was working toward: `journal=2026-09-15`.

That file does not exist.

This is the part worth sitting with, because the safety net is written to handle
exactly that. It creates the journal from a template if it is missing, *then*
appends the failure line — the whole point being that a missing journal must
never be indistinguishable from a quiet night:

```powershell
if (-not (Test-Path $journalFile)) { …write the template… }
…AppendAllText($journalFile, "- ❌ Non exécuté : $reason…")
```

So the file's absence is not the net failing to write. It is proof the net was
never reached. That code sits in section 3 of the runner; the process stopped in
section 2, at `tentative 1`. Every line after the point of death is, from the
failure's point of view, code that does not exist.

That is the shape of the whole problem. You cannot place a handler *after* the
failure when the failure is the process ending. There is no after.

Which makes this mechanism structurally incapable of reporting the two failure
classes above — 15 of 37 nights, 41% of the sample, invisible to it by
construction. Not missed. Unreachable.

> A system that reports on itself can only report the failures it survives.

The corollary is the actionable part. If you want to know whether a scheduled
job ran, the check has to live outside the process. If you want to know whether
the *machine* was there to run it, the check has to live outside the machine.
Every layer of self-reporting you add inside the process improves the quality of
the failures you can already see, and does nothing for the ones you cannot.

## The numbers, and how they were counted

Window: 2026-08-21 (first log) to 2026-09-26. 37 nights, 30 runs.

Nights, which is what I actually care about:

| | Nights | % |
|---|---|---|
| Delivered a report | 22 | 59% |
| Attempted, delivered nothing | 5 | 14% |
| Never started | 10 | 27% |

Of the 15 nights with no report, 3 were absorbed by a later run's 36-hour
window, 3 lost data outright, and 9 are indeterminate — 4 because the
pre-rewrite logs do not record their window, 5 because a run that produced no
report also left no record of what it would have covered.

Runs, which is where the failure modes are visible:

| | Runs |
|---|---|
| Succeeded | 23 |
| Failed with a non-zero exit code | 3 |
| Log truncated, no exit code, no status | 4 |

Method, so you can run it against your own logs: one file per run, named
`run_<date>_<time>.log`. Classify each by its final line — `STATUT FINAL : ok`,
an explicit exit code, or nothing. Roll up to nights, because two runs on one
night is one night. Then diff the set of dates against the calendar, because the
nights that matter most are the ones with no file to classify.

**Where this data is weaker:** the status line only exists in the runner as
rewritten on 2026-09-07. Runs before that are classified by exit code alone,
which is the very signal this document argues you should not trust. I am
counting 6 pre-rewrite nights as delivered on the strength of `Exit code: 0`. If
one of those was a silent no-op, 59% is generous.

## What fixes what

| Failure class | Fixable where you already are? | By what |
|---|---|---|
| Lying return value | Yes, in the code | Confirm the effect at the source of truth |
| Failure during the run | Yes, in the code | Lock, timeout, retry, proof line |
| Process killed mid-run | **No** | Nothing in-process survives it |
| Night never started | **Partly**, one layer down | Wake-to-run, catch-up, a wide enough window |

That last row is the one worth being precise about, because it is where the
easy answer lives and the easy answer is already in place. Wake-to-run, catch-up
and a 36-hour window are real mitigations: they fired on 11 of 30 runs and
absorbed 3 of the 10 missed nights. They are worth having, and if you take one
practical thing from this document, make it *check those three settings on your
own scheduled job.*

They also have a ceiling. Waking works from sleep, not from off. Catch-up runs
whenever the machine returns, which may be nowhere near the night it owed you.
A window sized for one missed night does not span four. Each of those is a
property of the machine's power state, not of the schedule — which is why the
mitigation is one layer down from the code, and still not far enough down.

## The part that is not a software problem

41% is not a reliability figure. Reliability is a property of a program:
given that it runs, does it do the right thing. Mine does, as far as I can
measure — 23 of 30 runs succeeded, and the 3 that failed failed legibly.

What I was actually measuring is **availability**, and availability is a
property of the host. Retry logic cannot move it, because retry logic needs a
running process and the failure is that there is no process. The scheduler can
move it a little, and does. But every lever at that layer is still asking a
machine that is switched off to do something, and the answer to that is always
going to be the same.

The conclusion I draw from my own data is not "write better error handling". It
is that the always-on parts of this system are running on a machine that is not
always on, and they should not be. The capture runs and the maintenance jobs
want a box that stays powered: they are batch work, they hold no secrets, and
they already ship as a container with a scheduler inside it — because a box with
no cron still needs one, and `restart: unless-stopped` is not a schedule.

The night agent is the exception, and it stays where it is. It drives an
authenticated CLI, and those credentials do not belong in a container that
restarts unattended. A job that needs a human's login belongs on a machine that
human logs into. Its 00:30 run will keep missing nights, and that is now a
known, measured, bounded cost rather than a surprise.

There is one job in this system that has never missed: the profile rebuild,
because it runs on GitHub's infrastructure rather than mine. It is 4 for 4 since
I moved it. I am deliberately not presenting that as evidence — four nights is
not a sample, and quoting it as a success rate would be exactly the kind of
unverified number this document is about. The argument is structural, not
statistical: that job cannot miss a night for the reason the others do, because
the reason the others miss is my laptop.

## Limits

One machine, one operating system, one user, 37 nights. The method is
reproducible; the sample is not a study. The pre-2026-09-07 classification is
weaker than the rest, as noted above, and the same gap makes 4 of the 10 dark
nights impossible to test for window recovery.

I cannot say which of the dark nights were shutdown rather than hibernation, and
I have not tested whether `WakeToRun` behaves the same under Windows' modern
standby as under classic S3 sleep — both would change how much of the 27% is
addressable at the scheduler layer. Nothing was running to record any of it,
which is the document's own point turned back on its author.

What I have not done is the obvious next experiment: move the capture jobs to a
host that stays on and measure the same 37 nights again. Until that number
exists, the case for the move rests on the mechanism, not on a comparison.

---

*The runner, the proof line and the container are in
[this repository](https://github.com/martinbouvet2000-tech/nightshift). The logs
and journals behind these numbers are from a private vault and are not
published; the counting method above is the part that transfers.*

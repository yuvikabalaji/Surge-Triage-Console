# Surge Triage Console

> After an incident, call volumes spike. This prototype **identifies duplicate reports** of the same event and **flags high-priority cases for immediate response**, then ranks them so dispatchers know what to send help to first.

Built as a hackathon demo (Round 3). It runs on synthetic data, uses only the Python standard library on the back end, and ships as a single self-contained HTML dashboard.

---

## Table of contents
1. [The problem](#the-problem)
2. [What it does](#what-it-does)
3. [Quick start](#quick-start)
4. [Using the dashboard](#using-the-dashboard)
5. [How it works](#how-it-works)
   - [Pipeline](#pipeline)
   - [Duplicate detection](#duplicate-detection)
   - [Priority triage](#priority-triage)
   - [Ranked response queue](#ranked-response-queue)
   - [Live voice intake and vocal stress](#live-voice-intake-and-vocal-stress)
6. [Demo scenarios](#demo-scenarios)
7. [Project structure](#project-structure)
8. [Configuration and tuning](#configuration-and-tuning)
9. [Design principles](#design-principles)
10. [Limitations](#limitations)
11. [Roadmap](#roadmap)

---

## The problem
In the minutes after a major incident (a fire, a crash, a shooting), emergency lines are flooded:

- Dozens of callers report the **same event** in different words, from slightly different places.
- The calls that matter most (someone not breathing, a weapon, children trapped) are buried in the volume.
- Dispatchers can't tell "ten calls about one fire" from "ten separate emergencies", and don't have time to read every transcript.

## What it does
| Capability | Summary |
|---|---|
| **Duplicate detection** | Merges calls about the same event into one incident using location, time, incident type and wording, with an explanation for every link. |
| **Priority flagging** | Scores each call for urgency from keywords (negation-aware), vulnerable people, critical places, panic language and vocal stress, then rolls it up to the incident. |
| **Surge escalation** | An incident gets more urgent as more independent callers report it, and when later calls reveal worse details. |
| **Ranked response queue** | Orders P1/P2 incidents with a transparent response score and shows who to dispatch now given the number of free units. |
| **Live voice intake** | Transcribes a caller with the Web Speech API and scores the call *while they are still speaking*. |
| **Map** | A live street map of incidents and individual calls, in the style of the Citizen app. |

## Quick start
Requirements: Python 3 (standard library only) and Chrome or Edge for voice features. Internet access is needed for the map tiles and speech recognition.

```bash
git clone https://github.com/yuvikabalaji/Surge-Triage-Console.git
cd Surge-Triage-Console

python build.py                  # runs the engine on the synthetic calls and regenerates dashboard.html
python -m http.server 8000       # serve over localhost (needed for microphone access)
```

Open **http://localhost:8000/dashboard.html** in Chrome or Edge.

`dashboard.html` also opens by double-click for everything except the microphone: Chrome restricts speech features on `file://` pages.

After editing any Python or JavaScript file, run `python build.py` again.

## Using the dashboard
**Header stats:** calls received, incidents, duplicates collapsed, P1 incidents, and calls filtered out as accidental.

**Timeline and Replay:** drag the slider to see the surge at any minute, or press **Replay** to watch incidents appear and escalate. Units are re-ranked at each step.

**Units free slider:** how many response units are available. The top-ranked P1/P2 incidents show **DISPATCH NOW**; the rest show **QUEUED**, with a reminder to send automated callback and self-help guidance (for example CPR or shelter instructions).

**Incident cards:** each card shows the rank, response score, priority, call count, distinct callers, an *Escalated since first report* marker, the factor bars behind the score, and the keywords that triggered the priority. Click a card to expand every call, including *why* it was linked to the incident (distance, time, wording scores) and why it got its priority. Clicking also zooms the map to the incident.

**Map:** pins are colored by priority, sized by caller count and labelled with the response rank for P1/P2 incidents. P1 pins pulse. Small dots are individual calls, with a faint circle for GPS accuracy. Clicking a pin opens its card.

**Live call intake (voice):**
1. Choose where the caller's phone is (a landmark, "elsewhere", or your own GPS).
2. Press the microphone and speak. The transcript appears as you talk, with live keyword chips and a priority badge.
3. The call is placed on the map and ranked in the queue about once a second while you speak.
4. Press **Stop & submit call** to finish. The system waits briefly for the last words, then finalizes the call.
5. If voice is unsupported, type or paste a transcript and press **Analyze & submit as call**.

Try: *"There's a fire at 5th and Oak, kids are trapped inside"*, *"Someone's dying, please help, I don't know what to do"*, *"I don't think anyone has a weapon"* (the last one is negated and does not trigger the weapon flag).

## How it works

### Pipeline
```
call (transcript, caller ID, phone location, time, audio cue)
   │
   ├─ geocode      spoken landmark overrides a far-away or imprecise phone fix
   ├─ classify     incident type: violence / fire / crash / water / hazmat / medical / other
   ├─ score        priority points from keywords, vulnerability, place, distress, stress
   └─ cluster      join the best-matching open incident, or open a new one
                         │
                         └─ aggregate per incident: max call priority, surge bump,
                            escalation flag, response score, rank
```
The same vocabulary and scoring rules run in Python (`engine.py`, for the dataset) and JavaScript (`voice.js`, for live calls). Python exports its vocabulary into the page so both stay in sync.

### Duplicate detection
Every new call is compared with the members of each open incident. The best pairwise score decides.

```
score = 0.40·geo + 0.15·time + 0.20·type + 0.25·text
```

| Signal | How it is measured |
|---|---|
| **geo** | Distance between the two calls minus the sum of their location-accuracy radii. Full score when the circles overlap, fading to zero over 300 m. Cell-tower fixes (accuracy above 300 m) count at 40%. |
| **time** | Fades to zero over a 40-minute window. |
| **type** | 1.0 if the incident types are compatible, 0.7 against a vague "other" call, 0 if different. |
| **text** | Dice similarity of normalized words, with synonyms merged (collision, crash, wreck, accident → crash; blaze, flames → fire). |

Rules on top of the score:
- A call joins an incident at **0.60 or above**; otherwise it opens a new incident.
- **Different kinds of emergency are never auto-merged.** Types are judged against the whole incident's profile, so a vague call cannot bridge two unrelated emergencies. A chest-pain call 60 m from a warehouse fire stays separate.
- **Same caller within 45 minutes** counts as an update to the same incident.
- A **spoken landmark** overrides the phone's location when the phone is more than 500 m away or its accuracy is poor, which handles people reporting for a relative or a friend.
- **Accidental calls** (pocket dials, wrong numbers) are excluded from incident counts but kept for audit. A **silent open line** is *not* treated as accidental, because the caller may be unable to speak safely.

### Priority triage
Each call earns points; the call's level comes from its total.

| Level | Points |
|---|---|
| **P1** | 5 or more |
| **P2** | 3 to 4 |
| **P3** | 1 to 2 |
| **P4** | 0 |

Scoring sources:
- **Danger and medical keywords**, for example weapon, gun, shots fired, shooter, hostage (5 to 6); not breathing, no pulse (6); unconscious, trapped, collapsed (3 to 4); drowning, explosion, choking, overdose (5); fire, crash, flood (2); smoke (1).
- **Panic and distress language**: *dying* (+5), *going to die* (+5), *I don't know what to do* (+2), *please help / need help* (+2), *help*, *scared*, *panic*, *terrified*, *oh my god* (+1 to +2). Reasons are tagged `distress:`.
- **Negation handling:** a hazard word with a negator in the six words before it is ignored ("no weapon", "nobody is trapped"). Fixed phrases such as "not breathing" are matched first and are never negated.
- **Vulnerable people** (child, baby, elderly, pregnant, wheelchair): +2, and +1 more when combined with a hazard.
- **Critical locations** (school, hospital, nursing home, stadium, daycare): +2.
- **Audio cues:** whispering +2, screaming +2, gunfire in the background +4, silent open line +1, and measured vocal stress (see below).
- **Benign context** (movie, TV, barbecue, prank): priority suppressed to P4.

**From calls to incidents:**
- An incident takes the **highest** priority among its calls, so one late "shots fired" raises a whole incident that began as "a fight".
- **Surge bump:** 5 or more distinct callers raise the level by one; 10 or more raise it by two.
- An incident is marked **Escalated** when its level is higher than its first call's.

### Ranked response queue
P1/P2 labels say an incident is urgent. When 10 or more are open at once, the **response score** orders them:

```
score = 40·time-critical + 25·lives-at-risk + 15·growth + 10·vulnerability + 10·confidence
        + waiting bonus (up to 10) + tier offset (P1 +30, P2 +10, P3 0, P4 -10)
```

| Factor | Meaning |
|---|---|
| Time-critical | How fast harm grows (from the highest call points). |
| Lives at risk | Grows with the number of distinct callers. |
| Growth | Calls in the last 10 minutes, plus a bonus if the incident escalated. |
| Vulnerability | Children, the elderly or a critical location involved. |
| Confidence | Number of independent callers confirming it. |
| Waiting bonus | +0.25 per minute since the first report, capped at 10, so nothing waits forever. |

The tier offset keeps P1 above P2 unless a P2 has waited long enough to catch up. The dashboard shows each factor as a bar so a dispatcher can see why an incident sits where it does. The system **suggests; the dispatcher decides**.

### Live voice intake and vocal stress
`voice.js` implements voice typing with the Web Speech API:
- **Toggle and visual feedback:** the microphone button pulses red while recording.
- **Interim text:** partial transcription appears in the text box in real time.
- **Accumulation:** all segments build into one transcript and are finalized only on stop.
- **Silence handling:** browsers end recognition on silence, so it restarts automatically while recording is active.
- **Stale-state safe:** recording status lives in a single mutable object (the plain-JavaScript equivalent of a React ref) that event handlers read directly.
- **Flush delay:** 800 ms after stop for trailing results.
- **Fallback:** if the browser lacks the API, a message explains and typing still works.

**Vocal stress** is estimated from the microphone with the Web Audio API. Auto-gain and noise suppression are turned off so volume is not flattened. Every 100 ms it measures loudness (dBFS). The stress index combines:
- loudness relative to the caller's own first seconds of speech,
- absolute loudness,
- how often they spike well above their baseline,
- speaking rate in words per minute.

An index of 35 or more is *elevated* (+1 point) and 60 or more is *high* (+2). A very quiet voice is flagged as *whispering* (+2). The bars show current volume and stress while recording.

> Stress is a **rough proxy**. Volume depends on microphone gain and distance, so it detects loud or fast speech, not emotion. It only adds a few points and never overrides keywords.

## Demo scenarios
The synthetic data (`data.py`, 44 calls over 65 minutes) exercises these cases:

| Scenario | Expected behavior |
|---|---|
| Warehouse fire: 19 calls, different wordings, repeat callers, a weak cell-tower fix, a brother calling from across town | One incident; escalates to P1 when "trapped" and "explosion" appear. |
| Chest-pain call 60 m from the fire | Separate incident (different emergency type). |
| School: a fight, then "shots fired" | Starts as P2, escalates to P1; "no weapon" is correctly ignored. |
| Whispering caller; silent open line | Whisper joins the school incident; silent line becomes a P3 callback. |
| Highway crash, one caller reporting an unconscious driver | Merges into the crash incident and raises it to P1. |
| Cardiac arrest reported by spouse and neighbor | Merged into one P1 incident. |
| Car in water with a child | P1. |
| Pocket dial, movie with gunshots, neighbor's barbecue | Filtered or kept at P4. |

## Project structure
```
engine.py                  Duplicate clustering, priority scoring, vocabulary export
data.py                    Synthetic post-incident call surge (seeded, reproducible)
build.py                   Runs the engine, prints a summary, bakes dashboard.html
dashboard.template.html    Dashboard: queue, map (Leaflet), replay, ranking logic
voice.js                   Live voice intake: speech, vocal stress, in-browser scoring
dashboard.html             Generated, self-contained output (data embedded)
```

## Configuration and tuning
All thresholds are plain constants at the top of `engine.py`:

| Setting | Default | Effect |
|---|---|---|
| `DUP_THRESHOLD` | 0.60 | Pair score needed to merge a call into an incident. |
| `TIME_WINDOW_MIN` | 40 | Time-proximity fade window. |
| `GEO_SLACK_M` | 300 | Distance beyond accuracy radii before the geo score is zero. |
| `SAME_CALLER_WINDOW_MIN` | 45 | Same-caller updates window. |
| `LEVELS` | P1 5, P2 3, P3 1 | Points needed for each priority level. |
| `CLUSTER_SIZE_BUMPS` | 5 and 10 callers | Surge escalation. |
| `PHRASES`, `WORDS`, `VULNERABLE`, `CRITICAL_PLACES` | see file | The keyword vocabulary and weights. |
| `GAZETTEER` | five demo landmarks | Spoken places the system can locate. |

Response-score weights are in `snapshot()` in `dashboard.template.html`; the vocal stress thresholds are in `voice.js` (`updateStress`). To move the demo to another city, change the coordinates in `data.py` and `GAZETTEER`.

## Design principles
- **Never silently drop a call.** When unsure, an uncertain call becomes its own incident and stays visible.
- **Explain every decision.** Each link and priority carries human-readable reasons, so a dispatcher can verify or undo it.
- **Human in the loop.** The system recommends; the dispatcher confirms or overrides.
- **Fail safe.** If a component fails, calls are treated as new and potentially urgent.
- **Don't merge different emergencies.** Proximity alone is never enough.

## Limitations
- Works on typed or browser-transcribed text, not telephone audio. A real deployment needs streaming speech-to-text on the phone line and server-side acoustic features (pitch, speech rate) in place of browser volume.
- The landmark lookup is a hard-coded list of five places, not a real geocoder, so street names like "Broome Street" are not located.
- Keyword weights and thresholds are hand-tuned on one synthetic dataset and would need retuning on real call data.
- The response score favors incidents with many callers, so a single-caller emergency can rank below a large surge. The weights are meant to be adjusted.
- Waiting time counts from the first report; the prototype does not yet track which units are assigned.
- Web Speech API support varies by browser, sends audio to the browser vendor's speech service, and needs internet.
- Map tiles come from the public OpenStreetMap server, which is fine for a demo but not for production traffic.
- No real call data, authentication, audit storage or privacy controls are included.

## Roadmap
- Streaming speech-to-text on live call audio, with pitch and speech-rate stress features.
- A real geocoder and address parsing, plus text-message and alarm-panel sources.
- Unit tracking and nearest-suitable-unit assignment (fire, ambulance, police).
- Reversible merge and split controls with a full audit trail.
- Multilingual transcription and embeddings for semantic matching.
- Fairness audits across neighborhoods and accents, and privacy controls on recordings and transcripts.
- Evaluation on labeled data: duplicates caught, false merges avoided, time-to-flag for P1 cases.

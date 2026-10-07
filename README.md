# Surge Triage Console

After an incident, call volumes spike. This prototype collapses duplicate reports into single incidents and flags high-priority cases for immediate response.

- **Duplicate detection** (`engine.py`): location (with GPS accuracy and spoken addresses), time, incident type and text similarity, with an explainable score per link.
- **Priority triage:** negation-aware keyword scoring, vulnerable people, critical locations, panic/distress language, vocal stress from mic volume, and surge escalation.
- **Ranked response queue:** a response score ranks P1/P2 incidents against the number of free units.
- **Live voice intake** (`voice.js`): Web Speech API transcription that scores the call while the caller speaks.
- **Map:** Leaflet with OpenStreetMap tiles.

## Run
```
python build.py                 # regenerates dashboard.html from the synthetic data
python -m http.server 8000      # then open http://localhost:8000/dashboard.html in Chrome or Edge
```
Python 3 standard library only. Needs internet for the map tiles and speech recognition. All call data is synthetic.

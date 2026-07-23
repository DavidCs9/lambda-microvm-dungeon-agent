# Data plane

Live play path for the Dungeon Agent lab.

- `http/actions.py` — accept player actions; replay session events
- `http/speech.py` — Polly TTS
- `turns.py` — async turn worker (DM → MicroVM → events)
- `agents/roles.py` — `DungeonMaster`

Same AWS stack as `control_plane/`; separate folder so control vs data stays obvious.

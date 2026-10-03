"""Speech engine (spec §13, Phase 4): 16 kHz speech track → ``Transcript``
with word timings, silences and subtitle cues.

Engines are chosen by ``SPEECH_ROUTE`` (``provider:model``) like the model
router's roles, so swapping local Whisper for an API is configuration.
"""

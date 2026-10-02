# remotion — Phase 7

Motion-graphics engine (spec §19-20). Components are implemented here once per
entry of `packages/timeline/synthcut_timeline/registry.py`; agents may place
only registered components. Remotion renders transparent overlay layers; the
final composite is FFmpeg (rule 19).

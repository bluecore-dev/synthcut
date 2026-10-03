#!/usr/bin/env bash
# Procedural sound effects for motion graphics (spec §19-20 "SFX"). Synthesised
# from formulas with FFmpeg — no third-party recordings, nothing to license.
# Re-run to regenerate; outputs are committed so deploys need no synthesis.
set -euo pipefail
cd "$(dirname "$0")"
R=48000
render() { # render <name> <filtergraph source> [extra audio filters]
  ffmpeg -hide_banner -loglevel error -y -f lavfi -i "$2" \
    -af "${3:-anull},aresample=$R,loudnorm=I=-18:TP=-3:LRA=7,apad=pad_dur=0.05" \
    -ac 2 -ar $R -c:a flac "$1.flac"
}
# pop — a fast downward chirp with a sharp decay
render pop "aevalsrc='0.9*sin(2*PI*(700*t-2400*t*t))*exp(-t*38)':s=$R:d=0.16"
# tick — a short high click, for timers and counters
render tick "aevalsrc='0.8*sin(2*PI*2200*t)*exp(-t*220)+0.3*sin(2*PI*4400*t)*exp(-t*300)':s=$R:d=0.06"
# ding — a bell: fundamental and inharmonic partials with a long tail
render ding "aevalsrc='0.6*sin(2*PI*1320*t)*exp(-t*3.2)+0.3*sin(2*PI*2650*t)*exp(-t*5)+0.15*sin(2*PI*3960*t)*exp(-t*8)':s=$R:d=1.2"
# notify — two rising tones, phone-notification style
render notify "aevalsrc='0.7*(lt(t,0.11)*sin(2*PI*880*t)*exp(-t*18)+gte(t,0.11)*sin(2*PI*1320*t)*exp(-(t-0.11)*14))':s=$R:d=0.45"
# whoosh — band-passed pink noise that swells and fades
render whoosh "anoisesrc=d=0.6:c=pink:r=$R:a=0.8" "bandpass=f=1400:width_type=o:w=2.2,afade=t=in:d=0.28:curve=qsin,afade=t=out:st=0.28:d=0.32:curve=qsin"
echo "generated: $(ls *.flac | tr '\n' ' ')"

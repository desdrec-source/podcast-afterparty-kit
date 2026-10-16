#!/usr/bin/env python3
"""Token-free speaker diarisation (SpeechBrain ECAPA + agglomerative clustering), CPU.

Usage:
  diarise.py AUDIO TRANSCRIPT [-n NUM_SPEAKERS] [-o OUT_PREFIX] [--whisper-model small.en]

TRANSCRIPT may be:
  * faster-whisper/whisper JSON: list of segments with "words" ({start,end,word} in s,
    or [ms, word] pairs), or {"segments":[...]}
  * a flat word list JSON: [[ms, "word"], ...] or [{"start":s,"end":s,"word":w}, ...]
  * a text transcript with "[mm:ss] Name: text" lines (or .srt). Word timestamps are then
    produced with faster-whisper and each transcript line gets a majority speaker label.
Outputs OUT_PREFIX.json (words, turns, lines) and OUT_PREFIX.txt (labelled transcript).
"""
import argparse, json, re, subprocess, sys, time, os
import numpy as np

SR = 16000

def load_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()

def ts(t):
    t = int(round(t)); return f"{t//3600:02d}:{t%3600//60:02d}:{t%60:02d}" if t >= 3600 else f"{t//60:02d}:{t%60:02d}"

def parse_ts(s):
    p = [float(x) for x in s.replace(",", ".").split(":")]
    v = 0
    for x in p: v = v * 60 + x
    return v

def norm_words(ws):
    out = []
    for w in ws:
        if isinstance(w, (list, tuple)):
            out.append({"start": w[0] / 1000.0, "end": None, "word": str(w[1]).strip()})
        else:
            out.append({"start": float(w["start"]), "end": w.get("end"), "word": str(w.get("word", w.get("text", ""))).strip()})
    return out

def words_from_json(d):
    if isinstance(d, dict): d = d.get("segments", d.get("words", []))
    if d and isinstance(d[0], dict) and "words" in d[0]:
        ws = [w for s in d for w in s["words"]]
    else:
        ws = d
    ws = norm_words(ws)
    if ws and max(w["start"] for w in ws) > 36000:  # looks like ms in dict form
        for w in ws:
            w["start"] /= 1000; w["end"] = w["end"] / 1000 if w["end"] else None
    return ws

def parse_text_lines(path):
    txt = open(path, encoding="utf-8", errors="ignore").read()
    lines = []
    if path.lower().endswith(".srt"):
        for b in re.split(r"\n\s*\n", txt.strip()):
            m = re.search(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)\s*\n(.*)", b, re.S)
            if m: lines.append({"start": parse_ts(m[1]), "label": "", "text": " ".join(m[3].split())})
    else:
        for l in txt.splitlines():
            m = re.match(r"\s*\[(\d+(?::\d+){1,2}(?:\.\d+)?)\]\s*(?:([^:\]]{1,40}):\s*)?(.*)", l)
            if m: lines.append({"start": parse_ts(m[1]), "label": (m[2] or "").strip(), "text": m[3].strip()})
    return lines

def whisper_words(audio_path, model):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(audio_path, word_timestamps=True, vad_filter=True)
    return [{"start": w.start, "end": w.end, "word": w.word.strip()} for s in segs for w in s.words]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio"); ap.add_argument("transcript")
    ap.add_argument("-n", "--num-speakers", type=int, default=0, help="0 = auto (threshold)")
    ap.add_argument("--threshold", type=float, default=0.55, help="cosine distance for auto mode")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--whisper-model", default="small.en")
    ap.add_argument("--win", type=float, default=1.5); ap.add_argument("--hop", type=float, default=0.5)
    ap.add_argument("--min-turn", type=float, default=1.0, help="merge turns shorter than this (s)")
    a = ap.parse_args()
    t0 = time.time()
    out = a.out or os.path.splitext(a.transcript)[0] + ".diar"

    lines = []
    if a.transcript.lower().endswith(".json"):
        words = words_from_json(json.load(open(a.transcript)))
    else:
        lines = parse_text_lines(a.transcript)
        print(f"[diarise] {len(lines)} transcript lines; running faster-whisper ({a.whisper_model}) for word timestamps", file=sys.stderr)
        words = whisper_words(a.audio, a.whisper_model)
    words = [w for w in words if w["word"]]
    words.sort(key=lambda w: w["start"])
    for i, w in enumerate(words):
        if not w["end"]:
            nxt = words[i + 1]["start"] if i + 1 < len(words) else w["start"] + 0.6
            w["end"] = min(nxt, w["start"] + 1.0)

    y = load_audio(a.audio); dur = len(y) / SR
    # speech windows: centred on word spans only (transcript acts as VAD)
    W, H = int(a.win * SR), int(a.hop * SR)
    speech = np.zeros(len(y) // H + 1, bool)
    for w in words:
        speech[int(w["start"] * SR) // H: int(w["end"] * SR) // H + 1] = True
    starts = [i * H for i in range(len(speech)) if speech[i] and i * H + W <= len(y)]

    import torch
    torch.set_num_threads(os.cpu_count() or 4)
    from speechbrain.inference.speaker import EncoderClassifier
    enc = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cpu"},
                                         savedir=os.path.expanduser("~/.cache/speechbrain/ecapa"))
    embs = []
    with torch.no_grad():
        for b in range(0, len(starts), 64):
            batch = torch.from_numpy(np.stack([y[s:s + W] for s in starts[b:b + 64]]))
            embs.append(enc.encode_batch(batch).squeeze(1).numpy())
    E = np.concatenate(embs); E /= np.linalg.norm(E, axis=1, keepdims=True)

    from sklearn.cluster import AgglomerativeClustering
    if a.num_speakers > 0:
        cl = AgglomerativeClustering(n_clusters=a.num_speakers, metric="cosine", linkage="average")
    else:
        cl = AgglomerativeClustering(n_clusters=None, distance_threshold=a.threshold, metric="cosine", linkage="average")
    lab = cl.fit_predict(E)
    # drop tiny clusters, refine by centroid re-assignment (2 passes)
    for _ in range(2):
        ks = [k for k in set(lab) if (lab == k).sum() >= max(3, 0.02 * len(lab))]
        C = np.stack([E[lab == k].mean(0) for k in ks]); C /= np.linalg.norm(C, axis=1, keepdims=True)
        lab = np.array(ks)[np.argmax(E @ C.T, 1)]
    # name speakers by first appearance
    order = []
    for k in lab:
        if k not in order: order.append(k)
    name = {k: f"SPEAKER_{i+1}" for i, k in enumerate(order)}
    C = np.stack([E[lab == k].mean(0) for k in order]); C /= np.linalg.norm(C, axis=1, keepdims=True)
    centres = np.array(starts) / SR + a.win / 2
    S = E @ C.T  # window x speaker similarity

    # word scores: average similarity of windows overlapping the word (weighted by proximity)
    for w in words:
        m = (w["end"] + w["start"]) / 2
        sel = np.abs(centres - m) <= a.win / 2 + 0.05
        if not sel.any(): sel = np.abs(centres - m) == np.abs(centres - m).min()
        wt = 1.0 / (0.2 + np.abs(centres[sel] - m))
        sc = (S[sel] * wt[:, None]).sum(0) / wt.sum()
        w["score"] = sc
    # temporal smoothing of word scores (±2 words)
    sc = np.stack([w["score"] for w in words])
    k = 2; sm = np.stack([sc[max(0, i - k):i + k + 1].mean(0) for i in range(len(sc))])
    for w, s in zip(words, sm):
        j = int(np.argmax(s)); w["speaker"] = name[order[j]]
        w["conf"] = float(s[j] - np.partition(s, -2)[-2]) if len(s) > 1 else 1.0
        del w["score"]

    def mkturns(ws):
        ts_ = []
        for w in ws:
            if ts_ and ts_[-1]["speaker"] == w["speaker"]: ts_[-1]["words"].append(w)
            else: ts_.append({"speaker": w["speaker"], "words": [w]})
        return ts_
    turns = mkturns(words)
    # merge short turns into the neighbour (repeat until stable)
    changed = True
    while changed and len(turns) > 1:
        changed = False
        for i, t in enumerate(turns):
            d = t["words"][-1]["end"] - t["words"][0]["start"]
            if d < a.min_turn and len(t["words"]) < 4:
                nb = turns[i - 1] if i > 0 else turns[i + 1]
                for w in t["words"]: w["speaker"] = nb["speaker"]
                turns = mkturns(words); changed = True; break
    T = [{"speaker": t["speaker"], "start": round(t["words"][0]["start"], 2), "end": round(t["words"][-1]["end"], 2),
          "text": " ".join(w["word"] for w in t["words"]),
          "mean_conf": round(float(np.mean([w["conf"] for w in t["words"]])), 3)} for t in turns]

    # per transcript line labels
    L = []
    for i, l in enumerate(lines):
        end = lines[i + 1]["start"] if i + 1 < len(lines) else dur + 1
        ws = [w for w in words if l["start"] - 0.3 <= w["start"] < end - 0.3]
        cnt = {}
        for w in ws: cnt[w["speaker"]] = cnt.get(w["speaker"], 0) + 1
        best = max(cnt, key=cnt.get) if cnt else "UNKNOWN"
        share = cnt.get(best, 0) / max(1, len(ws))
        inner = [t for t in T if t["end"] > l["start"] and t["start"] < end - 0.3]
        L.append({"start": l["start"], "orig_label": l["label"], "speaker": best, "share": round(share, 2),
                  "mixed": share < 0.85, "inner_turns": [(ts(t["start"]), t["speaker"], len(t["text"].split())) for t in inner],
                  "text": l["text"]})
    # map speaker -> original names (majority) when available
    mapping = {}
    for l in L:
        if l["orig_label"]: mapping.setdefault(l["speaker"], {}).setdefault(l["orig_label"], 0); mapping[l["speaker"]][l["orig_label"]] += 1
    mapping = {k: max(v, key=v.get) for k, v in mapping.items()}

    res = {"audio": a.audio, "duration": round(dur, 2), "num_speakers": len(order), "runtime_s": round(time.time() - t0, 1),
           "speaker_name_guess": mapping, "turns": T, "lines": L,
           "words": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in w.items()} for w in words]}
    json.dump(res, open(out + ".json", "w"), indent=1)
    with open(out + ".txt", "w") as f:
        if L:
            for l in L:
                flag = "  [MIXED: " + ", ".join(f"{a_}@{b}({c}w)" for a_, b, c in [(x[1], x[0], x[2]) for x in l["inner_turns"]]) + "]" if l["mixed"] else ""
                f.write(f"[{ts(l['start'])}] {l['speaker']}: {l['text']}{flag}\n\n")
        else:
            for t in T: f.write(f"[{ts(t['start'])}] {t['speaker']}: {t['text']}\n\n")
    print(f"speakers={len(order)} turns={len(T)} runtime={res['runtime_s']}s names={mapping}")
    for t in T:
        print(f"  {ts(t['start'])}-{ts(t['end'])} {t['speaker']} conf={t['mean_conf']:.2f} words={len(t['text'].split())}: {t['text'][:70]}")
    for l in L:
        if l["mixed"]: print(f"  MIXED line [{ts(l['start'])}] {l['orig_label']} -> {l['inner_turns']}")
    print(f"wrote {out}.json / {out}.txt")

if __name__ == "__main__":
    main()

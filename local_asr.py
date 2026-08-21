#!/usr/bin/env python3
"""
Local (offline) transcription core for VoiceTray.

Whisper large-v3-turbo via faster-whisper / CTranslate2, CPU int8 — the same model as
before, but used smarter:

  * The audio is transcribed WHILE it is being recorded.  Whenever the speaker makes a
    pause and enough audio has accumulated, the pending audio is handed to a worker
    thread as one <=30 s window (Whisper's native window size).  When recording stops,
    only the last window (the "tail") is left to transcribe, so the wait after "stop"
    is roughly constant instead of growing linearly with the dictation length.
  * Windows are cut at silences (Silero VAD) and each one is transcribed exactly the
    way the whole file used to be (padded 30 s window, beam 5, VAD filter, prompt), so
    the text quality is the same as the old whole-file mode.
  * cpu_threads defaults to the number of physical cores.  CTranslate2's own default
    (4 threads) is ~2x slower on hybrid Intel CPUs, because the OS spreads them over
    the slow E-cores.
  * The model is warmed up once at start-up (the first inference is always slow).

Usage from the app:

    asr = LocalASR()                       # loads the model (downloads it once)
    session = asr.start_session(prompt, language="ru")
    session.feed(pcm_int16_bytes)          # called from the recording thread
    text = session.finish()                # blocks until the tail is transcribed

Standalone benchmark / self-test (simulates a real-time recording from a WAV file):

    python local_asr.py recording.wav [--speed 1.0] [--prompt-file ~/.voice_to_text/prompt.txt]
"""

import glob
import os
import sys
import threading
import time
import wave

import numpy as np

SAMPLE_RATE = 16000

# --- Windowing policy (seconds) -------------------------------------------------------
# A window is dispatched to the worker when the speaker pauses for PAUSE_S and at least
# MIN_WINDOW_S of audio is pending.  Whisper sees at most 30 s at once; MAX_WINDOW_S
# leaves a small margin.  If the worker is busy, pending audio simply keeps growing and
# is split at silences later, so windows are naturally longer under load (fewer,
# cheaper encoder passes) and shorter when the CPU is free.
PAUSE_S = 0.6
MIN_WINDOW_S = 12.0
MAX_WINDOW_S = 28.0
CHECK_EVERY_S = 0.5     # how often feed() re-checks the pause condition
PAUSE_PROBE_S = 2.5     # the VAD probe looks for a pause in this much audio at the buffer end
CONTEXT_WORDS = 40      # tail of the previous window's text fed to the next one as context


def _default_cpu_threads():
    """Number of physical cores (env VOICE_TRAY_CPU_THREADS overrides)."""
    env = os.environ.get("VOICE_TRAY_CPU_THREADS")
    if env:
        return int(env)
    cores = set()
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/topology/core_id"):
        try:
            with open(path) as f:
                core = f.read().strip()
            pkg_path = os.path.join(os.path.dirname(path), "physical_package_id")
            with open(pkg_path) as f:
                pkg = f.read().strip()
            cores.add((pkg, core))
        except OSError:
            pass
    if cores:
        return len(cores)
    return os.cpu_count() or 4


class LocalASR:
    """Owns the faster-whisper model and hands out recording sessions."""

    def __init__(self, model_name="large-v3-turbo", cpu_threads=None, log=print,
                 beam_size=5, warmup=True):
        from faster_whisper import WhisperModel

        self.log = log
        self.model_name = model_name
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads or _default_cpu_threads()
        self._model_lock = threading.Lock()   # serialises all model use (worker / warm-up)

        self.log(f"[ASR] loading faster-whisper {model_name} (int8 CPU, {self.cpu_threads} threads)...")
        t0 = time.perf_counter()
        try:
            # local_files_only=True => use the cached model and make ZERO network calls.
            self.model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                      cpu_threads=self.cpu_threads, local_files_only=True)
            self.log(f"[ASR] model loaded from cache in {time.perf_counter() - t0:.1f}s (fully offline)")
        except Exception:
            # Not cached yet -> download once (~1.5 GB), then it stays offline forever.
            self.log("[ASR] model not cached; downloading once (~1.5 GB) from Hugging Face...")
            self.model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                      cpu_threads=self.cpu_threads, local_files_only=False)
            self.log("[ASR] model downloaded and ready")

        from faster_whisper.vad import VadOptions, get_speech_timestamps  # noqa: F401
        self._get_speech_timestamps = get_speech_timestamps
        self._VadOptions = VadOptions

        if warmup:
            threading.Thread(target=self._warmup, daemon=True, name="asr-warmup").start()

    # -- model access -------------------------------------------------------------------

    def _warmup(self):
        """First inference is slow (thread pool spin-up, allocations) — do it now, not on
        the user's first dictation."""
        with self._model_lock:
            t0 = time.perf_counter()
            audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            segments, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                                vad_filter=False, without_timestamps=True)
            list(segments)
            self.log(f"[ASR] warm-up done in {time.perf_counter() - t0:.1f}s")

    def speech_timestamps(self, audio, min_silence_ms=300, speech_pad_ms=0):
        """Silero VAD: [{'start': sample, 'end': sample}, ...] for a float32 buffer."""
        opts = self._VadOptions(min_silence_duration_ms=min_silence_ms,
                                speech_pad_ms=speech_pad_ms, min_speech_duration_ms=100)
        return self._get_speech_timestamps(audio, opts, sampling_rate=SAMPLE_RATE)

    def transcribe_window(self, audio, prompt, language):
        """Transcribe one <=30 s float32 window exactly like the old whole-file path."""
        with self._model_lock:
            # Whisper's standard temperature fallback: decode at 0.0 and retry warmer only
            # if the output looks degenerate (compression ratio > 2.4 or avg log-prob < -1).
            # With a fixed 0.0 Whisper has no way out of its classic "и другие, и другие,
            # и другие..." repetition loops.  When nothing degenerates the result is exactly
            # the temperature-0 one.  Capped at 3 retries (each costs a decode pass).
            segments, _info = self.model.transcribe(
                audio,
                language=language,
                initial_prompt=prompt or None,
                temperature=[0.0, 0.2, 0.4, 0.6],
                beam_size=self.beam_size,
                vad_filter=True,
            )
            # segments is a generator; consuming it runs the actual transcription
            return "".join(segment.text for segment in segments).strip()

    def start_session(self, prompt="", language="ru"):
        return Session(self, prompt, language)


class Session:
    """One recording: feed() PCM chunks from the recorder thread, finish() for the text."""

    def __init__(self, asr, prompt, language):
        self.asr = asr
        self.prompt = (prompt or "").strip()
        self.language = language
        self.log = asr.log

        self._chunks = []            # list of float32 arrays, in order
        self._total = 0              # samples fed so far
        self._committed = 0          # samples already transcribed
        self._in_flight_end = 0      # end of the window the worker is busy with (>= committed)
        self._cut_at = 0             # feed()'s latest "you may cut here" mark (sample index)
        self._finishing = False
        self._cv = threading.Condition()
        self._results = []           # window texts, in order
        self._timings = []           # (window_seconds, seconds_spent)
        self._error = None           # first exception raised in the worker, re-raised by finish()
        self._samples_at_last_check = 0

        self._worker = threading.Thread(target=self._run, daemon=True, name="asr-worker")
        self._worker.start()

    # -- recorder side ------------------------------------------------------------------

    def feed(self, pcm_int16_bytes):
        """Called from the recording thread for every audio chunk. Cheap."""
        audio = np.frombuffer(pcm_int16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        with self._cv:
            self._chunks.append(audio)
            self._total += len(audio)
            total = self._total
            # Pending = not yet transcribed AND not being transcribed right now, otherwise
            # a pause found while the worker is busy would produce a tiny follow-up window.
            pending = total - max(self._committed, self._in_flight_end)
            due = total - self._samples_at_last_check >= CHECK_EVERY_S * SAMPLE_RATE
            if not due:
                return
            self._samples_at_last_check = total
            if pending < MIN_WINDOW_S * SAMPLE_RATE:
                return
            if pending >= MAX_WINDOW_S * SAMPLE_RATE:
                # Long uninterrupted speech: let the worker split it at a silence.
                self._cv.notify()
                return
            probe = self._tail_audio(int(PAUSE_PROBE_S * SAMPLE_RATE))
        # VAD probe outside the lock (it is ~3 ms, but no reason to hold the lock).
        cut = self._pause_offset(probe)
        if cut is not None:
            with self._cv:
                self._cut_at = max(self._cut_at, total - len(probe) + cut)
                self._cv.notify()

    def finish(self):
        """Stop feeding; block until everything is transcribed; return the text."""
        t_stop = time.perf_counter()
        with self._cv:
            self._finishing = True
            self._cv.notify()
        self._worker.join()
        wait = time.perf_counter() - t_stop
        if self._error is not None:
            raise self._error
        rec = self._total / SAMPLE_RATE
        detail = ", ".join(f"{w:.1f}s->{s:.1f}s" for w, s in self._timings) or "no speech"
        self.log(f"[ASR] recording {rec:.1f}s, {len(self._timings)} window(s) [{detail}], "
                 f"wait after stop {wait:.1f}s")
        return " ".join(t for t in self._results if t).strip()

    # -- helpers ------------------------------------------------------------------------

    def _tail_audio(self, n):
        """Last n samples of the buffer (call with the lock held)."""
        out = []
        need = n
        for chunk in reversed(self._chunks):
            out.append(chunk if len(chunk) <= need else chunk[-need:])
            need -= len(out[-1])
            if need <= 0:
                break
        return np.concatenate(out[::-1]) if out else np.zeros(0, dtype=np.float32)

    def _pause_offset(self, probe):
        """Offset (samples) of a good cut point inside the probe: a bit into the first
        silence gap of >= PAUSE_S found in it, or None if there is no such pause.
        (Looking at a whole probe rather than only at the very end means short pauses
        are not missed between two checks.)"""
        min_gap = int(PAUSE_S * SAMPLE_RATE)
        if len(probe) < min_gap:
            return None
        speech = self.asr.speech_timestamps(probe)
        # Gaps: before the first segment, between segments, after the last one.
        edges = [0] + [x for seg in speech for x in (seg["start"], seg["end"])] + [len(probe)]
        for gap_start, gap_end in zip(edges[0::2], edges[1::2]):
            if gap_end - gap_start >= min_gap and gap_start > 0:
                return gap_start + min(gap_end - gap_start, int(0.4 * SAMPLE_RATE))
        return None

    def _buffer(self, start, end):
        return np.concatenate(self._chunks)[start:end]

    # -- worker -------------------------------------------------------------------------

    def _run(self):
        max_samples = int(MAX_WINDOW_S * SAMPLE_RATE)
        while True:
            with self._cv:
                while True:
                    pending = self._total - self._committed
                    if self._finishing:
                        break
                    if pending >= max_samples or self._cut_at > self._committed:
                        break
                    self._cv.wait()
                finishing = self._finishing
                start = self._committed
                if pending >= max_samples:
                    end = start + max_samples
                elif finishing:
                    end = self._total
                else:
                    end = self._cut_at
                if end <= start:
                    if finishing:
                        return
                    continue
                self._in_flight_end = end
                # Slice a bit more than needed so a long window can be split at a silence.
                audio = self._buffer(start, min(self._total, end + SAMPLE_RATE))

            if end - start >= max_samples:
                end = start + self._split_point(audio[:max_samples + SAMPLE_RATE], max_samples)
                with self._cv:
                    self._in_flight_end = end
            audio = audio[: end - start]

            try:
                text = self._transcribe(audio)
            except Exception as e:  # keep going so finish() never hangs; it re-raises
                self.log(f"[ASR] window failed: {e!r}")
                if self._error is None:
                    self._error = e
                text = ""

            with self._cv:
                self._committed = end
                if self._cut_at < end:
                    self._cut_at = end
                self._results.append(text)
                if self._finishing and self._committed >= self._total:
                    return

    def _split_point(self, audio, max_samples):
        """Best place to cut a too-long window: inside the LONGEST silence gap that lies
        in the second half of the allowed range (a mid-phrase cut is what makes Whisper
        hallucinate). Falls back to a hard cut at max_samples if there is no gap."""
        speech = self.asr.speech_timestamps(audio[:max_samples], min_silence_ms=200)
        best_len, best_cut = 0, None
        for prev, nxt in zip(speech, speech[1:]):
            gap_start, gap_end = prev["end"], nxt["start"]
            if gap_start < max_samples // 2:
                continue
            if gap_end - gap_start > best_len:
                best_len = gap_end - gap_start
                best_cut = gap_start + min(gap_end - gap_start, int(0.4 * SAMPLE_RATE))
        if speech and len(audio) > speech[-1]["end"] + int(0.2 * SAMPLE_RATE) and \
                speech[-1]["end"] >= max_samples // 2 and (len(audio) - speech[-1]["end"]) > best_len:
            best_cut = speech[-1]["end"] + min(len(audio) - speech[-1]["end"], int(0.4 * SAMPLE_RATE))
        if best_cut is None:
            return max_samples
        return min(max_samples, best_cut)

    def _transcribe(self, audio):
        t0 = time.perf_counter()
        seconds = len(audio) / SAMPLE_RATE
        # Skip windows without any speech: no encoder pass, no hallucinated text.
        speech = self.asr.speech_timestamps(audio, min_silence_ms=500)
        if not speech:
            self.log(f"[ASR] window {seconds:.1f}s: no speech, skipped")
            return ""
        # Trim long leading/trailing silence (keeps ~0.5 s of context on both sides).
        pad = int(0.5 * SAMPLE_RATE)
        lo = max(0, speech[0]["start"] - pad)
        hi = min(len(audio), speech[-1]["end"] + pad)
        # Like faster-whisper's condition_on_previous_text across its own 30 s windows: the
        # terms prompt plus the tail of what was said before.  The prompt is always kept
        # (faster-whisper keeps the LAST ~223 prompt tokens, so keep the context short).
        prev = " ".join(" ".join(t for t in self._results if t).split()[-CONTEXT_WORDS:])
        prompt = f"{self.prompt} {prev}".strip() if prev else self.prompt
        text = self.asr.transcribe_window(audio[lo:hi], prompt, self.language)
        spent = time.perf_counter() - t0
        self._timings.append((seconds, spent))
        self.log(f"[ASR] window {seconds:.1f}s -> {spent:.1f}s: {text[:60]!r}")
        return text


# --- standalone self-test / benchmark ---------------------------------------------------

def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="Simulate a recording from a WAV file (16 kHz mono int16).")
    ap.add_argument("wav")
    ap.add_argument("--speed", type=float, default=1.0, help="feed N times faster than real time")
    ap.add_argument("--language", default="ru")
    ap.add_argument("--prompt-file", default=os.path.expanduser("~/.voice_to_text/prompt.txt"))
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--batch", action="store_true", help="also run the old whole-file mode for comparison")
    args = ap.parse_args(argv)

    with wave.open(args.wav) as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, \
            "need 16 kHz mono 16-bit WAV"
        pcm = w.readframes(w.getnframes())
    prompt = ""
    if os.path.exists(args.prompt_file):
        with open(args.prompt_file, encoding="utf-8") as f:
            prompt = f.read().strip()

    asr = LocalASR(cpu_threads=args.threads, warmup=True)
    time.sleep(0.1)
    with asr._model_lock:      # wait for warm-up to finish before timing anything
        pass

    chunk = 1024 * 2           # bytes per 1024-sample chunk, like the recorder
    session = asr.start_session(prompt, args.language)
    t0 = time.perf_counter()
    for i in range(0, len(pcm), chunk):
        session.feed(pcm[i:i + chunk])
        target = ((i + chunk) / 2 / SAMPLE_RATE) / args.speed
        delay = target - (time.perf_counter() - t0)
        if delay > 0:
            time.sleep(delay)
    t_stop = time.perf_counter()
    text = session.finish()
    print(f"\n=== pipelined: wait after stop {time.perf_counter() - t_stop:.1f}s\n{text}\n")

    if args.batch:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        t0 = time.perf_counter()
        old = asr.transcribe_window(audio, prompt, args.language)
        print(f"=== old whole-file mode: {time.perf_counter() - t0:.1f}s\n{old}\n")


if __name__ == "__main__":
    _main(sys.argv[1:])

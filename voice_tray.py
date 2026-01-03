#!/usr/bin/env python3
"""
Voice-to-Text System Tray Application
Signal-activated voice recording with visual feedback

sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 xdotool xclip portaudio19-dev
pip install groq pyaudio PyGObject-stubs

Send SIGUSR1 signal to toggle recording (bind to any hotkey in system settings)
"""

import os
os.environ['ALSA_CARD'] = 'default'
import warnings
warnings.filterwarnings('ignore')

from contextlib import contextmanager
import sys

@contextmanager
def suppress_stderr():
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    sys.stderr.flush()
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)

import pyaudio
import wave
import tempfile
from groq import Groq
import subprocess
from threading import Thread, Event
import signal
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3, GLib
import array


class AudioRecorder:
    """Audio recording with level monitoring"""

    # Audio configuration constants
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    NORMALIZATION_DIVISOR = 3276.70  # For 16-bit audio: 32767 / 10

    def __init__(self, device_index=None):
        self.device_index = device_index
        
        with suppress_stderr():
            self.audio = pyaudio.PyAudio()
        
        if self.device_index is None:
            self.device_index = self._find_microphone()
    
    def _find_microphone(self):
        """Find working microphone"""
        try:
            default = self.audio.get_default_input_device_info()
            return default['index']
        except:
            for i in range(self.audio.get_device_count()):
                try:
                    info = self.audio.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        return i
                except:
                    continue
        return None
    
    def record(self, stop_event, level_callback=None):
        """Record audio until stop_event is set"""
        if self.device_index is None:
            return None
        
        with suppress_stderr():
            stream = self.audio.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.CHUNK
            )
        
        frames = []
        
        while not stop_event.is_set():
            try:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                frames.append(data)
                
                # Calculate audio level for visual feedback
                if level_callback:
                    audio_data = array.array('h', data)
                    if len(audio_data) > 0:
                        level = max(abs(min(audio_data)), abs(max(audio_data)))
                        normalized_level = int((level / self.NORMALIZATION_DIVISOR) * 100)
                        GLib.idle_add(level_callback, normalized_level)
            except:
                break
        
        stream.stop_stream()
        stream.close()
        
        if not frames:
            return None
        
        # Save to temporary file
        tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        wf = wave.open(tmp_file.name, 'wb')
        wf.setnchannels(self.CHANNELS)
        wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
        wf.setframerate(self.RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        return tmp_file.name
    
    def cleanup(self):
        """Cleanup audio resources"""
        self.audio.terminate()


class VoiceToTextApp:
    """System tray application for voice-to-text"""

    # Audio level thresholds (tuned for typical speech level 300-500)
    LEVEL_HIGH = 15
    LEVEL_MEDIUM = 7
    LEVEL_LOW = 4

    # Status display timeouts (seconds)
    SUCCESS_TIMEOUT = 3
    ERROR_TIMEOUT = 2

    # Default prompt for technical terms
    DEFAULT_PROMPT = (
        "Technical terms: PyAudio, PyGObject, GTK3, AppIndicator3, Groq API, "
        "Whisper, xclip, xdotool, Claude Code, Python, threading, GLib, "
        "SIGUSR1, transcription, audio recording"
    )

    def __init__(self):
        # Check API key
        self.api_key = os.environ.get('GROQ_API_KEY')
        if not self.api_key:
            print("ERROR: GROQ_API_KEY not set")
            sys.exit(1)

        # Setup transcription log file
        self.log_dir = os.path.expanduser("~/.voice_to_text")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "transcriptions.log")
        self.prompt_file = os.path.join(self.log_dir, "prompt.txt")

        # Create default prompt file if it doesn't exist
        if not os.path.exists(self.prompt_file):
            with open(self.prompt_file, 'w', encoding='utf-8') as f:
                f.write(f"{self.DEFAULT_PROMPT}\n")

        print(f"[DEBUG] Transcription log: {self.log_file}")
        print(f"[DEBUG] Prompt file: {self.prompt_file}")

        self.client = Groq(api_key=self.api_key)
        print("[DEBUG] Creating AudioRecorder...")
        self.recorder = AudioRecorder()

        if self.recorder.device_index is None:
            print("ERROR: No microphone found")
            sys.exit(1)

        print(f"[DEBUG] Microphone found: device_index={self.recorder.device_index}")

        # State
        self.is_recording = False
        self.stop_recording = Event()
        self.recording_thread = None
        self.current_level = 0

        # Setup signal handler for SIGUSR1
        signal.signal(signal.SIGUSR1, self._handle_signal)
        print(f"[DEBUG] Signal handler registered for SIGUSR1 (PID: {os.getpid()})")

        # Create indicator
        print("[DEBUG] Creating AppIndicator...")
        self.indicator = AppIndicator3.Indicator.new(
            "voice-to-text",
            "microphone-sensitivity-high",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        # Try absolute icon path as fallback
        self.indicator.set_icon_full("microphone-sensitivity-high", "Voice to Text")
        # Set label to make it always visible
        self.indicator.set_label("🎤", "🎤")
        print("[DEBUG] AppIndicator created and activated")

        # Create menu
        self.menu = Gtk.Menu()

        # Title item (shows app name)
        title_item = Gtk.MenuItem(label="🎤 Voice to Text")
        title_item.set_sensitive(False)
        self.menu.append(title_item)

        # Status item (shows current state)
        self.status_item = Gtk.MenuItem(label="Ready")
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)
        
        self.menu.append(Gtk.SeparatorMenuItem())
        
        # Quit
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self.quit)
        self.menu.append(quit_item)
        
        self.menu.show_all()
        self.indicator.set_menu(self.menu)

        print("Voice-to-Text started")
        print(f"To toggle recording, send: kill -SIGUSR1 {os.getpid()}")
        print("You can bind this to any hotkey in your system settings")
    
    def update_status(self, text, icon=None):
        """Update status in menu and icon"""
        GLib.idle_add(self._do_update_status, text, icon)
    
    def _do_update_status(self, text, icon):
        """Actual status update (must run in main thread)"""
        self.status_item.set_label(text)
        if icon:
            self.indicator.set_icon(icon)

        # Update label based on status - always keep it visible
        if "Recording" in text:
            # Extract recording indicator from text (e.g., "Recording ●●●")
            if "●●●" in text:
                self.indicator.set_label("🎤●●●", "🎤●●●")
            elif "●●○" in text:
                self.indicator.set_label("🎤●●○", "🎤●●○")
            elif "●○○" in text:
                self.indicator.set_label("🎤●○○", "🎤●○○")
            else:
                self.indicator.set_label("🎤○○○", "🎤○○○")
        elif "Processing" in text:
            self.indicator.set_label("🎤...", "🎤...")
        else:
            self.indicator.set_label("🎤", "🎤")

        return False
    
    def update_level_indicator(self, level):
        """Update visual feedback based on audio level"""
        self.current_level = level

        # Determine indicator based on audio level thresholds
        if level > self.LEVEL_HIGH:
            indicator = "●●●"
        elif level > self.LEVEL_MEDIUM:
            indicator = "●●○"
        elif level > self.LEVEL_LOW:
            indicator = "●○○"
        else:
            indicator = "○○○"

        self.update_status(f"Recording {indicator}")
        return False

    def _handle_signal(self, _signum, _frame):
        """Handle SIGUSR1 signal to toggle recording"""
        print("[DEBUG] SIGUSR1 received, toggling recording")
        # Use GLib.idle_add to safely call toggle from signal handler
        GLib.idle_add(self._toggle_recording)

    def _toggle_recording(self):
        """Toggle recording on/off (called from signal handler)"""
        if not self.is_recording:
            print("[DEBUG] Signal: Starting recording...")
            self.start_recording()
        else:
            print("[DEBUG] Signal: Stopping recording...")
            self.stop_recording_action()
        return False

    def start_recording(self):
        """Start audio recording"""
        print("[DEBUG] start_recording() called")
        self.is_recording = True
        self.stop_recording.clear()

        self.update_status("Recording ○○○")
        print("[DEBUG] Status updated, starting recording thread...")

        # Start recording in background thread
        self.recording_thread = Thread(target=self._record_and_transcribe, daemon=True)
        self.recording_thread.start()
        print("[DEBUG] Recording thread started")
    
    def stop_recording_action(self):
        """Stop audio recording"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        self.stop_recording.set()
    
    def _record_and_transcribe(self):
        """Record audio and transcribe (runs in background thread)"""
        # Record
        audio_file = self.recorder.record(self.stop_recording, self.update_level_indicator)

        if not audio_file:
            self.update_status("Ready")
            return

        # Transcribe
        self.update_status("Processing...")

        try:
            # Load custom prompt for technical terms
            custom_prompt = self._load_prompt()

            with open(audio_file, "rb") as f:
                api_params = {
                    "file": (audio_file, f.read()),
                    "model": "whisper-large-v3-turbo",
                    "language": "ru",
                    "response_format": "text",
                    "temperature": 0.0
                }

                # Add prompt if available
                if custom_prompt:
                    api_params["prompt"] = custom_prompt

                transcription = self.client.audio.transcriptions.create(**api_params)
            
            text = transcription.strip()

            if text:
                # Save to log file (permanent storage)
                self._save_to_log(text)

                # Copy to clipboard (NO auto-paste for security)
                self._copy_to_clipboard(text)

                # Show success
                preview = text[:30] + "..." if len(text) > 30 else text
                self.update_status(f"✓ Copied: {preview}")

                # Reset to ready after timeout
                GLib.timeout_add_seconds(self.SUCCESS_TIMEOUT, lambda: self._reset_to_ready())
            else:
                self.update_status("No speech detected")
                GLib.timeout_add_seconds(self.ERROR_TIMEOUT, lambda: self._reset_to_ready())

        except Exception as e:
            print(f"Transcription error: {e}")
            self.update_status("Error")
            GLib.timeout_add_seconds(self.ERROR_TIMEOUT, lambda: self._reset_to_ready())
        
        finally:
            # Clean up temp file
            try:
                os.remove(audio_file)
            except:
                pass
    
    def _copy_to_clipboard(self, text):
        """Copy text to clipboard"""
        try:
            process = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'],
                stdin=subprocess.PIPE
            )
            process.communicate(text.encode('utf-8'))
        except Exception as e:
            print(f"Clipboard error: {e}")

    def _save_to_log(self, text):
        """Save transcription to log file"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {text}\n")
        except Exception as e:
            print(f"Log write error: {e}")

    def _reset_to_ready(self):
        """Reset status to ready"""
        self.update_status("Ready")
        return False

    def _load_prompt(self):
        """Load custom prompt from file for technical terms"""
        try:
            if os.path.exists(self.prompt_file):
                with open(self.prompt_file, 'r', encoding='utf-8') as f:
                    prompt = f.read().strip()
                    return prompt if prompt else None
        except Exception as e:
            print(f"Prompt file read error: {e}")
        return None

    def quit(self, _=None):
        """Quit application"""
        self.recorder.cleanup()
        Gtk.main_quit()
    
    def run(self):
        """Run the application"""
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        Gtk.main()


def check_dependencies():
    """Check required system dependencies"""
    required = ['xclip']
    missing = []

    for cmd in required:
        if subprocess.run(['which', cmd], capture_output=True).returncode != 0:
            missing.append(cmd)

    if missing:
        print(f"ERROR: Missing dependencies: {', '.join(missing)}")
        print(f"Install: sudo apt install {' '.join(missing)}")
        return False

    return True


if __name__ == '__main__':
    if not check_dependencies():
        sys.exit(1)
    
    app = VoiceToTextApp()
    app.run()
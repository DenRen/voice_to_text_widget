# Voice-to-Text System Tray Application - Development Context

## Project Overview

Professional voice-to-text application for Ubuntu that runs as a system tray app with signal-based activation. Records audio, transcribes it using Groq's Whisper API, and copies the result to clipboard.

**Status**: Production-ready, fully functional

## Platform Requirements

- **OS**: Ubuntu/Debian Linux only
- **Display Server**: X11 (required for xclip)
- **Desktop Environment**: Any with system tray support (GNOME, KDE, XFCE, etc.)
- **NOT compatible with**: macOS, Windows, Wayland (without XWayland)

## Technical Stack

### Core Technologies
- **Python 3**: Main language
- **PyGObject (GTK3)**: System tray GUI
- **AppIndicator3**: Tray icon indicator
- **PyAudio**: Audio recording (16-bit PCM, 16kHz, mono)
- **Groq API**: Whisper Large v3 Turbo for transcription
- **xclip**: Clipboard operations
- **SIGUSR1**: Unix signal for activation (no keyboard library needed)

### System Dependencies
```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 xclip portaudio19-dev
```

### Python Dependencies
```bash
pip install groq pyaudio PyGObject-stubs
```

**Important**: PyGObject MUST be installed via apt (python3-gi), NOT pip. This is a GTK requirement.

## Architecture & Design Decisions

### Activation Method: SIGUSR1 Signal (NOT Keyboard Hotkeys)

**Why signals instead of keyboard libraries?**
- Keyboard detection (pynput, keyboard) was unreliable on Ubuntu
- Space key wasn't detected properly in key combinations
- Signals are more reliable and system-independent
- User can bind ANY hotkey in system settings to send the signal

**How it works:**
1. User binds a hotkey (e.g., Ctrl+Shift+Space) in Ubuntu Settings → Keyboard
2. Hotkey executes: `kill -SIGUSR1 <PID>`
3. Application toggles recording on/off

### Audio Recording Architecture

**Recording Parameters:**
- Format: 16-bit signed PCM (paInt16)
- Sample Rate: 16kHz (Whisper optimized)
- Channels: Mono
- Chunk Size: 1024 samples
- Normalization: Raw level / 3276.70 = 0-100 scale

**Audio Level Calculation:**
```python
level = max(abs(min(audio_data)), abs(max(audio_data)))  # Raw: 0-32767
normalized = int((level / 3276.70) * 100)  # Scaled: 0-100
```

**Thresholds (tuned for typical speech at 300-500 raw level):**
- LEVEL_HIGH = 15 (loud speech) → ●●●
- LEVEL_MEDIUM = 7 (normal speech) → ●●○
- LEVEL_LOW = 4 (quiet speech) → ●○○
- Below 4 → ○○○

### Threading Model

- **Main Thread**: GTK event loop (Gtk.main)
- **Recording Thread**: Background daemon thread for audio recording and transcription
- **Thread Safety**: GLib.idle_add for GUI updates from background thread
- **Signal Handler**: SIGUSR1 handled safely via GLib.idle_add

### Security Design

**NO AUTO-PASTE** - Clipboard only:
- Original design included auto-paste with xdotool
- **Removed for security**: Prevents accidental command execution in terminal
- User explicitly pastes when ready (Ctrl+V)
- Transcription also saved to permanent log file

### Data Persistence

**Transcription Log**: `~/.voice_to_text/transcriptions.log`
- Append-only log of all transcriptions
- Format: `[YYYY-MM-DD HH:MM:SS] transcribed text`
- Never lost, even if clipboard overwritten

**Custom Prompt File**: `~/.voice_to_text/prompt.txt`
- User-editable technical terms for Whisper
- Created automatically with defaults on first run
- Loaded on each transcription
- Passed to Whisper API `prompt` parameter for better recognition

## Key Features

1. ✅ System tray icon (always visible with 🎤 emoji)
2. ✅ Toggle recording mode (SIGUSR1 signal)
3. ✅ Real-time audio level indicator (○○○ → ●●● visual feedback)
4. ✅ No focus loss - cursor stays in place
5. ✅ Clipboard copy (NO auto-paste for security)
6. ✅ Persistent logging to disk
7. ✅ Custom prompt support for technical terms
8. ✅ Clean, minimal UI
9. ✅ All messages in English
10. ✅ ALSA/JACK error suppression

## User Workflow

### Setup (One-time)
1. Install system dependencies
2. Install Python packages
3. Set `GROQ_API_KEY` environment variable
4. Run `python3 voice_tray.py`
5. Note the PID from output
6. Bind hotkey in system settings to: `kill -SIGUSR1 <PID>`

### Daily Usage
1. Start app: `python3 voice_tray.py` (or add to autostart)
2. See 🎤 icon in system tray
3. Press hotkey → recording starts (○○○ indicator appears)
4. Speak (indicator changes: ●○○ → ●●○ → ●●●)
5. Press hotkey again → recording stops
6. Wait for "Processing..." → "✓ Copied: preview..."
7. Paste anywhere with Ctrl+V
8. All transcriptions saved to `~/.voice_to_text/transcriptions.log`

### Customization
Edit `~/.voice_to_text/prompt.txt` to add project-specific technical terms:
```
Technical terms: MyCustomClass, API endpoint, React hooks, TypeScript, async/await, ...
```

## Code Structure

### Class: AudioRecorder
**Purpose**: Audio recording with real-time level monitoring

**Constants:**
- CHUNK = 1024
- FORMAT = paInt16
- CHANNELS = 1
- RATE = 16000
- NORMALIZATION_DIVISOR = 3276.70

**Methods:**
- `_find_microphone()`: Auto-detect working microphone
- `record(stop_event, level_callback)`: Record until event, call callback with levels
- `cleanup()`: Terminate PyAudio

### Class: VoiceToTextApp
**Purpose**: Main application with system tray and transcription logic

**Constants:**
- LEVEL_HIGH/MEDIUM/LOW: Audio level thresholds
- SUCCESS_TIMEOUT/ERROR_TIMEOUT: Status display durations
- DEFAULT_PROMPT: Default technical terms

**Key Methods:**
- `__init__()`: Setup API, files, tray icon, signal handler
- `_handle_signal()`: SIGUSR1 handler
- `_toggle_recording()`: Start/stop recording
- `_record_and_transcribe()`: Background thread worker
- `update_level_indicator(level)`: Real-time visual feedback
- `_load_prompt()`: Read custom prompt file
- `_save_to_log(text)`: Append to transcription log
- `_copy_to_clipboard(text)`: Copy via xclip

## API Configuration

### Groq Whisper API
- **Model**: `whisper-large-v3-turbo`
- **Language**: `ru` (Russian with English technical terms)
- **Response Format**: `text`
- **Temperature**: 0.0 (deterministic)
- **Prompt**: Loaded from `~/.voice_to_text/prompt.txt` (optional)
- **Cost**: ~$0.04 per hour of audio

### Environment Variables
```bash
export GROQ_API_KEY="your-api-key-here"
```

## Design Philosophy

- **Minimal UI**: No windows, only system tray
- **No focus interruption**: Recording works in background
- **Security first**: No auto-paste, user controls when text appears
- **Reliability**: Signal-based activation (no fragile keyboard detection)
- **Data safety**: All transcriptions logged to disk
- **Maintainability**: Single file, constants extracted, well-documented
- **User control**: Editable prompt file for technical terms
- **Professional**: Clean code, English messages, no emojis in console

## Known Limitations

1. **Platform**: Ubuntu/Debian only (AppIndicator3 dependency)
2. **Display Server**: X11 required (xclip limitation)
3. **Internet**: Requires connection for Groq API
4. **Audio Length**: Whisper has 30-second processing limit (can chunk if needed)
5. **Language Model**: Optimized for Russian with English technical terms
6. **Hotkey Setup**: Manual PID-based binding (could use wrapper script for autostart)

## Troubleshooting

### Microphone Issues
- Check `device_index` in debug output
- Test with: `arecord -l` to list devices
- Ensure ALSA_CARD environment variable is correct

### Tray Icon Not Visible
- Icon always shows 🎤 emoji (even if system icon missing)
- Check AppIndicator3 support in DE
- Try restarting the app

### Audio Levels Always ○○○
- Check normalization divisor (3276.70)
- Verify microphone input volume in system settings
- Test recording with another app

### Transcription Errors
- Verify `GROQ_API_KEY` is set
- Check internet connection
- See error in console output
- Check `~/.voice_to_text/transcriptions.log` for successful transcriptions

### Signal Not Working
- Verify correct PID: `ps aux | grep voice_tray.py`
- Test manually: `kill -SIGUSR1 <PID>`
- Check hotkey command in system settings

## Future Enhancement Ideas

1. **Auto-start wrapper**: Script to capture PID and update hotkey binding automatically
2. **Chunking**: Support for recordings > 30 seconds
3. **Multiple languages**: Language selector in tray menu
4. **Voice profiles**: Different prompts for different contexts
5. **Local Whisper**: Offline mode with local model (larger, slower)
6. **Wayland support**: Use wl-clipboard instead of xclip

## Development Notes

### Evolution of the Project
1. Started with keyboard hotkey detection (pynput)
2. Switched to SIGUSR1 signals (more reliable)
3. Added audio level visualization
4. Fixed normalization formula (32767 → 3276.70)
5. Removed auto-paste for security
6. Added persistent logging
7. Added custom prompt support
8. Refactored constants and magic numbers

### Testing
- Test on clean Ubuntu installation
- Verify with different microphones
- Test with long recordings (near 30s limit)
- Test Russian + English mixed speech
- Test custom prompt effectiveness

### Code Quality
- All constants extracted to class level
- No magic numbers in methods
- Thread-safe GUI updates
- Proper resource cleanup
- Comprehensive error handling
- Clear documentation

## Files

- `voice_tray.py`: Main application (single file, ~450 lines)
- `CONTEXT_FOR_CLAUDE_CODE.md`: This file
- `~/.voice_to_text/transcriptions.log`: Transcription history (created at runtime)
- `~/.voice_to_text/prompt.txt`: Custom technical terms (created at runtime)

## Quick Reference

### Start Application
```bash
export GROQ_API_KEY="your-key"
python3 voice_tray.py
```

### Bind Hotkey (Ubuntu Settings)
1. Settings → Keyboard → View and Customize Shortcuts
2. Custom Shortcuts → Add
3. Name: "Voice to Text"
4. Command: `kill -SIGUSR1 $(pgrep -f voice_tray.py)`
5. Shortcut: Ctrl+Shift+Space

### View Logs
```bash
tail -f ~/.voice_to_text/transcriptions.log
```

### Edit Technical Terms
```bash
nano ~/.voice_to_text/prompt.txt
```

---

**Last Updated**: 2026-01-03
**Status**: Production Ready
**Maintainer**: User + Claude Code

# Voice-to-Text System Tray App

Professional voice-to-text application for Ubuntu that runs in your system tray. Record audio with a hotkey, transcribe with Whisper AI, and paste anywhere.

![Status](https://img.shields.io/badge/status-production--ready-green)
![Platform](https://img.shields.io/badge/platform-Ubuntu%20%7C%20Debian-orange)
![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-blue)

## Features

- 🎤 **System tray integration** - Minimal UI, runs in background
- ⚡ **Hotkey activation** - Press once to start, press again to stop
- 📊 **Real-time audio levels** - Visual feedback while recording (○○○ → ●●●)
- 🔒 **Security-first** - Copies to clipboard only (no auto-paste)
- 💾 **Persistent logging** - All transcriptions saved to disk
- 🎯 **Custom vocabulary** - Add technical terms for better accuracy
- 🌍 **Multilingual** - Optimized for Russian with English technical terms
- 🧵 **Thread-safe** - Reliable background processing

## Demo

```
User workflow:
1. Press hotkey → 🎤○○○ (recording starts)
2. Speak       → 🎤●●● (audio levels shown)
3. Press again → 🎤... (processing)
4. Done        → ✓ Copied: "Your transcribed text..."
5. Paste       → Ctrl+V anywhere
```

## Installation

### System Dependencies

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
                 gir1.2-appindicator3-0.1 xclip portaudio19-dev
```

### Python Dependencies

```bash
pip install groq pyaudio PyGObject-stubs
```

**Important:** Install PyGObject via apt (`python3-gi`), not pip.

### Get Groq API Key

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. Export it:
```bash
export GROQ_API_KEY="your-api-key-here"
# Add to ~/.bashrc to make permanent
echo 'export GROQ_API_KEY="your-api-key-here"' >> ~/.bashrc
```

## Quick Start

### 1. Run the Application

```bash
python3 voice_tray.py
```

You'll see:
```
[DEBUG] Transcription log: /home/user/.voice_to_text/transcriptions.log
[DEBUG] Prompt file: /home/user/.voice_to_text/prompt.txt
[DEBUG] Microphone found: device_index=0
[DEBUG] Signal handler registered for SIGUSR1 (PID: 12345)
Voice-to-Text started
To toggle recording, send: kill -SIGUSR1 12345
```

### 2. Bind a Hotkey

**Ubuntu Settings:**
1. Settings → Keyboard → View and Customize Shortcuts
2. Custom Shortcuts → Add
3. Name: `Voice to Text`
4. Command: `kill -SIGUSR1 $(pgrep -f voice_tray.py)`
5. Shortcut: `Ctrl+Shift+Space` (or any key you prefer)

### 3. Use It

- Press `Ctrl+Shift+Space` to start recording
- Speak your message
- Press `Ctrl+Shift+Space` again to stop
- Text is copied to clipboard
- Paste with `Ctrl+V` anywhere

## Configuration

### Custom Technical Terms

Edit `~/.voice_to_text/prompt.txt` to improve recognition of project-specific terms:

```bash
nano ~/.voice_to_text/prompt.txt
```

Example:
```
Technical terms: PyAudio, PyGObject, GTK3, React, TypeScript,
async/await, Kubernetes, PostgreSQL, MyCustomClass, API endpoint
```

The prompt is sent to Whisper AI on each transcription to improve accuracy.

### View Transcription History

All transcriptions are logged:

```bash
tail -f ~/.voice_to_text/transcriptions.log
```

Format:
```
[2026-01-03 14:23:45] Привет, это тестовая запись
[2026-01-03 14:24:12] Testing English with technical terms like PyAudio
[2026-01-03 14:25:01] Смешанный Russian and English text
```

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     System Tray Icon 🎤                     │
└─────────────────────┬───────────────────────────────────────┘
                      │
         User presses hotkey (Ctrl+Shift+Space)
                      │
                      ▼
         ┌────────────────────────────┐
         │  Send SIGUSR1 to process   │
         └────────────┬───────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   Toggle Recording State   │
         └────────────┬───────────────┘
                      │
        ┌─────────────┴──────────────┐
        │                            │
        ▼                            ▼
   Recording ON                 Recording OFF
        │                            │
        ▼                            ▼
┌──────────────┐              ┌──────────────┐
│ Record Audio │              │ Stop & Save  │
│ Show Levels  │              │ to temp file │
│  🎤●●●       │              └──────┬───────┘
└──────────────┘                     │
                                     ▼
                            ┌─────────────────┐
                            │ Send to Groq    │
                            │ Whisper API     │
                            └────────┬────────┘
                                     │
                            ┌────────┴─────────┐
                            │                  │
                            ▼                  ▼
                    ┌──────────────┐   ┌──────────────┐
                    │ Copy to      │   │ Save to Log  │
                    │ Clipboard    │   │ File         │
                    └──────────────┘   └──────────────┘
```

### Why SIGUSR1 Instead of Keyboard Libraries?

- **Reliability**: Keyboard libraries (pynput, keyboard) had detection issues on Ubuntu
- **Flexibility**: User can bind ANY hotkey in system settings
- **Simplicity**: No complex keyboard hook management
- **Security**: Works within OS permission model

## API & Costs

- **Model**: Whisper Large v3 Turbo (via Groq)
- **Cost**: ~$0.04 per hour of audio
- **Speed**: Very fast (Groq's LPU inference)
- **Limit**: 30 seconds per request (sufficient for most use cases)

## Platform Requirements

| Requirement | Notes |
|------------|-------|
| OS | Ubuntu/Debian Linux |
| Display Server | X11 (not Wayland without XWayland) |
| Desktop | Any with system tray (GNOME, KDE, XFCE) |
| Python | 3.8+ |
| Internet | Required for Groq API |

## Troubleshooting

### Tray Icon Not Visible

The icon always shows a 🎤 emoji label. If missing:
- Check if AppIndicator3 is supported in your desktop environment
- Try restarting the app
- Look in the system tray area (top-right corner)

### No Audio Levels (Always ○○○)

- Check microphone volume in system settings
- Verify the correct device is selected: `arecord -l`
- Test recording with: `arecord -d 3 test.wav && aplay test.wav`

### "ERROR: GROQ_API_KEY not set"

```bash
export GROQ_API_KEY="your-key"
# Or add to ~/.bashrc
echo 'export GROQ_API_KEY="your-key"' >> ~/.bashrc
source ~/.bashrc
```

### Hotkey Doesn't Work

Test manually:
```bash
# Find the PID
ps aux | grep voice_tray.py

# Send signal manually
kill -SIGUSR1 <PID>
```

If manual signal works but hotkey doesn't, check your hotkey binding command.

### Transcription Errors

- Verify API key is valid
- Check internet connection
- See console output for error details
- Verify `~/.voice_to_text/transcriptions.log` for successful transcriptions

## Advanced Usage

### Auto-start on Login

Create `~/.config/autostart/voice-to-text.desktop`:

```desktop
[Desktop Entry]
Type=Application
Name=Voice to Text
Exec=/usr/bin/python3 /path/to/voice_tray.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
```

### Custom Audio Settings

Edit constants in `voice_tray.py`:

```python
class AudioRecorder:
    CHUNK = 1024          # Buffer size
    RATE = 16000          # Sample rate (Whisper optimized)
    CHANNELS = 1          # Mono audio
    NORMALIZATION_DIVISOR = 3276.70  # Level scaling
```

### Adjust Level Thresholds

Edit in `voice_tray.py`:

```python
class VoiceToTextApp:
    LEVEL_HIGH = 15    # Loud speech
    LEVEL_MEDIUM = 7   # Normal speech
    LEVEL_LOW = 4      # Quiet speech
```

### Quick Start Alias

Add to your `~/.bashrc` for easy launching from anywhere:

```bash
# Voice-to-Text widget alias
voice-tray() {
    local VENV_DIR="$HOME/projects/voice_to_text_widget"
    "$VENV_DIR/venv/bin/python3" "$VENV_DIR/voice_tray.py"
}
```

Then reload and use:

```bash
source ~/.bashrc
voice-tray  # Launch from anywhere without activating venv
```

**Prerequisites**: Run `./setup_venv.sh` first to create the virtual environment.

**Note**: This runs Python directly from the venv without activating it, keeping your terminal environment clean.

## Project Structure

```
.
├── voice_tray.py              # Main application (~450 lines)
├── CONTEXT_FOR_CLAUDE_CODE.md # Developer documentation
├── README.md                  # This file
└── ~/.voice_to_text/          # Runtime directory (auto-created)
    ├── transcriptions.log     # All transcription history
    └── prompt.txt             # Custom technical terms
```

## Contributing

Contributions welcome! Areas for improvement:

- [ ] Wayland support (replace xclip with wl-clipboard)
- [ ] Audio chunking for >30 second recordings
- [ ] Language selector in tray menu
- [ ] Auto-start setup script
- [ ] Multiple voice profiles
- [ ] Local Whisper model option (offline mode)

## License

MIT License - See LICENSE file for details

## Credits

- **Whisper AI**: OpenAI's speech recognition model
- **Groq**: Fast LPU inference for Whisper
- **GTK/AppIndicator**: System tray integration
- **PyAudio**: Audio recording

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/voice-to-text-tray/issues)
- **Documentation**: See `CONTEXT_FOR_CLAUDE_CODE.md` for technical details

---

**Made with ❤️ for Ubuntu power users**

**Star ⭐ this repo if you find it useful!**

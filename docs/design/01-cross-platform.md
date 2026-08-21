# Трек 1. Кроссплатформенность

> Цель: тула запускается на любом Linux-дистрибутиве (X11 и Wayland),
> на macOS — обязательно, на Windows — если это не потребует несоразмерных усилий.
> Статус: спроектировано, не реализовано.

## 1. Инвентаризация: что в текущем коде привязано к платформе

Разбор `voice_tray.py` по зависимостям:

| Компонент | Сейчас | Привязка | Переносимость |
|---|---|---|---|
| Tray-иконка + анимированный label `🎤●●●` | GTK3 + AppIndicator3 (PyGObject) | Linux | ❌ на macOS/Windows не существует |
| Event loop | `Gtk.main()` + `GLib.idle_add` | Linux | ❌ тянется за GTK |
| Clipboard | `xclip` (subprocess) | **только X11** | ❌ ломается даже на Wayland |
| Триггер записи | сигнал `SIGUSR1` + системный хоткей | POSIX | ✅ Linux и macOS; ❌ Windows |
| Запись звука | PyAudio (PortAudio) | кроссплатформенный | ⚠️ требует системный `portaudio19-dev` |
| `ALSA_CARD=default`, suppress_stderr | ALSA-шум | Linux | безвредно на других ОС |
| Транскрипция (Groq / faster-whisper) | чистый Python | — | ✅ |
| Конфиг/лог `~/.voice_to_text/` | чистый Python | — | ✅ (на Windows — `%USERPROFILE%`) |

**Главная удача текущего дизайна** — активация через внешний сигнал, а не
через keyboard-hook библиотеку. Это решение (принятое когда-то из-за глюков
pynput на Ubuntu) оказывается стратегически верным для портирования:

- глобальные keyboard-hooks на macOS требуют Accessibility-разрешений и капризны;
- на Wayland глобальный перехват клавиатуры приложению вообще недоступен;
- а «повесь системный хоткей на команду» работает везде: GNOME/KDE Settings,
  macOS Shortcuts.app / skhd / Hammerspoon, Windows — ярлык с хоткеем или AutoHotkey.

Значит, обобщаем сигнал до понятия **trigger backend**, но саму модель
«хоткей вешает пользователь системными средствами» сохраняем.

## 2. Архитектура: ядро + бэкенды

Интерфейсы (см. также структуру пакета в [00-overview.md](00-overview.md)):

```python
class TrayBackend(Protocol):
    def set_label(self, text: str) -> None: ...   # "🔒🎤●●●"
    def set_status(self, text: str) -> None: ...  # пункт меню "Recording"
    def run(self) -> None: ...                    # блокирующий event loop
    def quit(self) -> None: ...

class ClipboardBackend(Protocol):
    def copy(self, text: str) -> None: ...

class TriggerBackend(Protocol):
    def listen(self, on_toggle: Callable[[], None]) -> None: ...
```

Ядро (state machine + запись + транскрипция) не знает, на какой ОС работает.
Потоковая модель остаётся прежней: event loop в главном потоке, запись и
транскрипция — в фоновом, UI-обновления маршалятся в главный поток
(аналог `GLib.idle_add` есть у каждого tray-фреймворка).

## 3. Решения по бэкендам

### 3.1 Tray

| ОС | Решение | Обоснование |
|---|---|---|
| Linux | **оставить GTK3 + AppIndicator3** (текущий код переезжает в `platform/linux_gtk.py`) | работает, отлажен, AppIndicator жив и на KDE, и на GNOME (с расширением) |
| macOS | **rumps** (обёртка над NSStatusBar) | нативно поддерживает произвольный **текстовый** title в menu bar — наша анимация `🔒🎤●●●` ложится идеально |
| Windows | **pystray** | единственный вменяемый вариант; ⚠️ анимированный текст рядом с иконкой невозможен — только перерисовка самой иконки (см. ниже) |

Рассматривался вариант «pystray везде» (один код на три ОС), но отвергнут:
pystray на Linux сам оборачивает AppIndicator (ничего не выигрываем), а на
macOS не даёт текстового title — потеряли бы анимацию уровня звука, которая
является ключевой фичей UX.

**Проверено веб-ресёрчем (2026-07):**

- **rumps жив**: PyPI 0.4.0, поддержка медленная, но библиотека — тонкая
  обёртка над PyObjC/NSStatusItem и от версии macOS почти не зависит;
  подтверждена работа на Apple Silicon. Динамический `app.title` — штатная
  фича (люди делают на нём посекундные таймеры в menu bar), наша анимация
  ложится тривиально. [rumps](https://github.com/jaredks/rumps)
- **Текст рядом с иконкой на Windows невозможен принципиально** — это не
  ограничение pystray, а самой ОС: notification area — это `Shell_NotifyIcon`
  (иконка + tooltip + меню, всё). Стандартный обходной путь — рендерить
  состояние **внутрь иконки** через PIL (`ImageDraw` + присвоение
  `icon.icon = new_image` на лету), так делают CPU-индикаторы на pystray.
  [pystray docs](https://pystray.readthedocs.io/en/latest/usage.html),
  [issue #30](https://github.com/moses-palmer/pystray/issues/30)
- **Единого кроссплатформенного tray с текстовым label не появилось и не
  появится** — даже у Tauri/tray-icon `set_title` реализован только для
  macOS, на Windows title всюду маппится в tooltip.

**Следствие для интерфейса `TrayBackend`** (важно, чтобы не сломать его потом):
контракт — не «покажи текст», а «покажи состояние»: `set_state(mode, level,
phase)`. Текстовый label — роскошь, доступная на macOS (и на Linux в текущем
DE автора); бэкенды Windows (и Linux-DE без label) обязаны уметь рендерить
то же состояние перерисовкой иконки. Рендер иконки с индикатором уровня
делаем общей утилитой (PIL), чтобы Windows- и fallback-Linux-путь не дублировали код.

### 3.2 Clipboard

| Окружение | Команда |
|---|---|
| X11 | `xclip -selection clipboard` (как сейчас) |
| Wayland | `wl-copy` (пакет wl-clipboard) |
| macOS | `pbcopy` (встроен в ОС) |
| Windows | `pyperclip` или win32 API |

Автодетект: `WAYLAND_DISPLAY` в env → wl-copy, иначе xclip; на macOS/Windows —
безусловно своё. Можно взять готовый `pyperclip`, который делает ровно этот
автодетект, и оставить subprocess-путь как fallback.

### 3.3 Триггер записи

Единый UX на всех ОС: **`voice-tray --toggle`** — вторая инвокация CLI сама
находит запущенный инстанс и дёргает его. Пользователь вешает системный
хоткей на эту команду и больше не думает про PID.

| ОС | Механизм под капотом |
|---|---|
| Linux, macOS | как сейчас: SIGUSR1 (PID берём из pid-файла `~/.voice_to_text/voice_tray.pid`) — плюс `--toggle` как обёртка |
| Windows | SIGUSR1 нет → **named pipe** (`\\.\pipe\voice_tray`) или локальный TCP/unix socket; `--toggle` пишет в pipe |

Куда пользователь вешает хоткей:
- GNOME/KDE: Settings → Keyboard → Custom Shortcut → `voice-tray --toggle`
  (работает и на X11, и на Wayland — custom shortcut просто запускает команду);
- macOS: **решено (по итогам веб-ресёрча) — Shortcuts.app**, единственный путь
  без стороннего софта; подробности в §5.1;
- Windows: ярлык с hotkey-полем либо AutoHotkey-однострочник.

### 3.4 Аудио

Мигрировать **PyAudio → sounddevice**:
- у sounddevice есть бинарные wheels с вшитым PortAudio — на macOS/Windows
  ставится `pip install sounddevice` без системных зависимостей
  (PyAudio требует `portaudio19-dev` и компиляцию);
- callback-API sounddevice удобнее для ring buffer из трека 3 — синергия;
- отдаёт numpy-массивы, что убирает ручную работу с `array('h', ...)`.

Параметры не меняются: 16 kHz, mono, int16.

### 3.5 Wayland — почти бесплатно

Отдельно зафиксировать: поддержка Wayland (а это дефолт современных Ubuntu,
Fedora) требует только замены xclip → wl-copy (§3.2). Хоткей через custom
shortcut и AppIndicator уже работают. Это первый шаг трека — дешёвый и нужный
самому автору.

## 4. Установка и дистрибуция

Целевая аудитория — коллеги-технари, поэтому не усложняем:

1. **Основной путь**: `uv tool install` / `pipx install` из git-репозитория.
   Требует оформить проект как пакет (`pyproject.toml`, entry point
   `voice-tray`) — всё равно нужно для рефакторинга.
2. Extras по режимам: `voice-tray[local]` (faster-whisper), `voice-tray[cloud]` (groq).
3. Windows (если дойдём): PyInstaller onefile.
4. macOS: без подписи приложения (Gatekeeper) обойдёмся, пока ставим через
   pipx из терминала — это не «.app из интернета», предупреждений не будет.

**Грабли `uv tool install` из приватного git (проверено веб-ресёрчем), учесть
в README:**

- Аутентификация: для разработчиков — SSH (`git+ssh://git@host/repo.git`,
  username обязательно `git`); для остальных — PAT через git credential
  helper, **не** в URL (осядет в истории shell).
- uv пинит git-зависимость на конкретный commit hash → «поставил вчера,
  сегодня не видит новых коммитов» лечится `uv tool upgrade voice-tray`,
  а не повторным install. Апгрейд перезапрашивает git — протухший токен
  = молчаливое падение с git-ошибкой.
- Синтаксис с extras требует кавычек, иначе shell съест скобки:
  `uv tool install "voice-tray[local] @ git+ssh://git@host/repo.git"` —
  прописать в README буквально.
- Self-hosted GitLab: первый клон по ssh падает с «Host key verification
  failed», если хоста нет в known_hosts — один `ssh-keyscan` или ручной
  `git clone` до установки.
  [uv docs: git auth](https://docs.astral.sh/uv/concepts/authentication/git/)

## 5. Специфика macOS, о которой надо помнить

### 5.1 Хоткей: блессед-путь — Shortcuts.app (решено)

По итогам веб-ресёрча в инструкции даём **один** путь, без выбора из четырёх
утилит: Shortcuts.app (встроен, GUI) → шорткат с действием «Run Shell Script»
(`voice-tray --toggle`) → в деталях шортката назначить сочетание клавиш.
Три known issues, которые обязаны попасть в инструкцию, иначе «не заведётся
у половины людей»:

1. «Run Shell Script» требует включить Advanced → **Allow Running Scripts**
   (на managed корпоративных маках настройка может не сохраняться — эскалация
   к IT);
2. клавиатурные шорткаты работают, только пока Shortcuts.app запущен →
   добавить его в **Login Items** (окно можно закрыть);
3. возможна ошибка «Operation not permitted» при запуске скрипта → выдать
   **Full Disk Access**.

Сочетание обязано включать модификатор, конфликты с системными хоткеями
Shortcuts не детектирует — в инструкции сразу предлагаем безопасное
сочетание (например ⌃⌥⌘V). Для терминальных коллег fallback — skhd, но
основной репозиторий в maintenance mode (автор указывает на Zig-форк),
поэтому в основную инструкцию он не идёт.
[skhd](https://github.com/koekeishiya/skhd)

### 5.2 Остальное

- **Разрешение на микрофон (TCC)**: первый запуск спросит разрешение у того,
  кто владеет процессом (Terminal/iTerm). Задокументировать в README.
- Автозапуск: LaunchAgent plist вместо `~/.config/autostart`.
- `~/.voice_to_text/` работает как есть.
- Модели faster-whisper на Apple Silicon у коллег будут быстрее, чем на
  нашем x86-ноуте (ARM NEON в CTranslate2), отдельных усилий не требует.

## 6. Оценка Windows: вердикт «не ебанутая хуйня, но и не бесплатно»

Что ломается: SIGUSR1 (→ named pipe, §3.3), GTK (→ pystray), автозапуск
(→ реестр/Startup folder). Что работает из коробки: sounddevice, clipboard,
faster-whisper, конфиг. Оценка — умеренные усилия, **но** тестировать и
поддерживать третью ОС дорого. Решение: заложить в архитектуру (интерфейсы
уже позволяют), реализовывать только если появится реальный коллега на Windows.

## 7. Порядок реализации

| Фаза | Содержание | Ценность |
|---|---|---|
| 0 | Рефакторинг в пакет + `pyproject.toml` + entry point, поведение 1-в-1 | фундамент |
| 1 | `--toggle` + pid-файл; clipboard-автодетект (Wayland) | сам автор получает Wayland |
| 2 | sounddevice вместо PyAudio | ставится без apt на любой ОС |
| 3 | macOS: rumps-бэкенд, доки по хоткею и микрофону | коллеги на маках |
| 4 | Windows: pystray + named pipe | по требованию |

## 8. Открытые вопросы

Закрыто веб-ресёрчем 2026-07 (отчёт: [research/2026-07-07-blocks-C-D.md](research/2026-07-07-blocks-C-D.md)):

- [x] pystray на Windows без текстового label → текст рядом с иконкой
  невозможен на уровне ОС; уровень записи рендерим внутрь иконки через PIL (§3.1).
- [x] Блессед-способ хоткея на macOS → Shortcuts.app с тремя known issues (§5.1).
- [x] Кроссплатформенный tray-фреймворк с текстовым label на всех трёх ОС →
  не существует и не появится (ограничение Windows Shell_NotifyIcon), остаёмся
  на сменных бэкендах (§3.1).

Остаётся проверить при реализации:

- [ ] rumps: совместимость с фоновым потоком записи (PyObjC run loop) —
  маршалинг UI-обновлений из recording-треда; ресёрч подтвердил живость
  библиотеки, но потоки проверяются только практикой.

"""macOS sound and notification delivery."""

import subprocess


DEFAULT_SOUND = "/System/Library/Sounds/Hero.aiff"


def play_sound(path, times=1):
    for _ in range(times):
        subprocess.run(["afplay", path], check=False)


def notify(title, message):
    script = f'display notification "{message}" with title "{title}" sound name "Hero"'
    subprocess.run(["osascript", "-e", script], check=False)

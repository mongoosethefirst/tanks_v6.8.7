# -*- coding: utf-8 -*-
import sys
from pathlib import Path


def roots():
    result = []
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        result.append(executable.parent)
        if hasattr(sys, "_MEIPASS"):
            result.append(Path(sys._MEIPASS))
        if sys.platform == "darwin" and ".app" in str(executable):
            for parent in executable.parents:
                if parent.suffix == ".app":
                    result.append(parent.parent)
                    break
    else:
        result.append(Path(__file__).resolve().parent.parent)
    return result


def asset_path(folder, name):
    for root in roots():
        for candidate in [root / folder / name, root / "tanks" / folder / name]:
            if candidate.exists():
                return str(candidate)
    return str(roots()[0] / folder / name)


def image_path(name):
    return asset_path("images", name)


def font_path(name="PressStart2P-Regular.ttf"):
    return asset_path("fonts", name)

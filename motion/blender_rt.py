"""Blender 内の Python で使う補助。bpy 以外に依存しないこと (motion パッケージは読み込めない)。"""
import json
import sys

import bpy


def args() -> dict:
    return json.loads(sys.argv[sys.argv.index("--") + 1])


def reset_scene() -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def render(a: dict, engine: str = "CYCLES", samples: int = 64, transparent: bool = True,
           denoise: bool = True) -> None:
    sc = bpy.context.scene
    sc.render.engine = engine
    sc.render.resolution_x = a["width"]
    sc.render.resolution_y = a["height"]
    sc.render.resolution_percentage = 100
    sc.render.fps = a["fps"]
    sc.frame_start = a["frame_start"]
    sc.frame_end = a["frame_end"]
    sc.render.film_transparent = transparent
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    sc.render.filepath = a["out"]
    if engine == "CYCLES":
        sc.cycles.samples = samples
        sc.cycles.use_denoising = denoise
        prefs = bpy.context.preferences.addons.get("cycles")
        if prefs:
            # Apple Silicon では Metal の GPU を使うと桁違いに速い
            try:
                prefs.preferences.compute_device_type = "METAL"
                prefs.preferences.get_devices()
                for d in prefs.preferences.devices:
                    d.use = True
                sc.cycles.device = "GPU"
            except Exception:
                sc.cycles.device = "CPU"
    bpy.ops.render.render(animation=True)

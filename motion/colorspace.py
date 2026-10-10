import cv2
import numpy as np


def _to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _to_srgb(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(np.maximum(x, 0), 1 / 2.4) - 0.055)


# uint8 の画素値で直接引ける表
SRGB_TO_LINEAR = _to_linear(np.arange(256) / 255.0).astype(np.float32)
IDENTITY = (np.arange(256) / 255.0).astype(np.float32)

# リニア → sRGB は 4096 段に量子化して表引きする (pow を 1080p で毎フレーム計算すると重い)
_ENC_N = 4096
_ENC = _to_srgb(np.linspace(0, 1, _ENC_N)).astype(np.float32)


def encode(lin: np.ndarray) -> np.ndarray:
    idx = np.clip(lin * (_ENC_N - 1) + 0.5, 0, _ENC_N - 1).astype(np.int32)
    return _ENC[idx]


def lookup(rgba: np.ndarray, table: np.ndarray) -> np.ndarray:
    """skia の RGBA uint8 を表で float32 の RGB に変える。OpenCV の表引きは numpy の添字より 10 倍速い。"""
    return cv2.LUT(cv2.cvtColor(rgba, cv2.COLOR_RGBA2RGB), table.reshape(256, 1))


def to_linear(srgb: np.ndarray) -> np.ndarray:
    return _to_linear(np.asarray(srgb, np.float32)).astype(np.float32)

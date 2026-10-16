"""Opus codec helpers for the Qwen realtime bridge.

Uplink   (client -> server): 16 kHz mono PCM s16le, 20 ms frames (320 samples).
Downlink (server -> client): 24 kHz mono PCM s16le, 20 ms frames (480 samples / 960 bytes).

Only codec factories and framing constants live here.
"""

import opuslib

DEC_SAMPLE_RATE = 16000
ENC_SAMPLE_RATE = 24000
CHANNELS = 1
DEC_FRAME_SAMPLES = 320     # 20 ms @ 16 kHz (client microphone uplink)
FRAME_SAMPLES = 480         # 20 ms @ 24 kHz (reply downlink)
FRAME_BYTES = 960           # FRAME_SAMPLES * 2 bytes (s16le mono)
FRAME_MS = 20


def OpusDec16():
    """Decoder for 16 kHz mono client microphone frames."""
    return opuslib.Decoder(DEC_SAMPLE_RATE, CHANNELS)


def OpusEnc24():
    """Encoder for 24 kHz mono reply frames."""
    enc = opuslib.Encoder(ENC_SAMPLE_RATE, CHANNELS, opuslib.APPLICATION_VOIP)
    enc.bitrate = 24000
    return enc
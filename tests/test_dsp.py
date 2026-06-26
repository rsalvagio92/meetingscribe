import numpy as np

from meetingscribe.audio import dsp


def test_to_mono_stereo():
    stereo = np.array([[1.0, 3.0], [2.0, 4.0]])
    mono = dsp.to_mono(stereo)
    assert np.allclose(mono, [2.0, 3.0])


def test_to_mono_passthrough():
    mono = np.array([1.0, 2.0])
    assert np.allclose(dsp.to_mono(mono), mono)


def test_resample_changes_length():
    sig = np.sin(np.linspace(0, 2 * np.pi, 48000)).astype(np.float32)
    out = dsp.resample_linear(sig, 48000, 16000)
    assert abs(len(out) - 16000) <= 1


def test_resample_noop_same_rate():
    sig = np.ones(100, dtype=np.float32)
    assert dsp.resample_linear(sig, 16000, 16000) is sig or np.allclose(
        dsp.resample_linear(sig, 16000, 16000), sig
    )


def test_int16_float_roundtrip():
    f = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    i = dsp.float32_to_int16(f)
    back = dsp.int16_to_float32(i)
    assert np.allclose(back, f, atol=1e-3)


def test_mix_pads_and_limits():
    a = np.array([0.8, 0.8, 0.8], dtype=np.float32)
    b = np.array([0.8], dtype=np.float32)
    mixed = dsp.mix(a, b)
    assert len(mixed) == 3
    assert np.max(np.abs(mixed)) <= 1.0 + 1e-6

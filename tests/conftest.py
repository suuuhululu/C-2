"""Test-wide guard: pytest must never reach a real microphone, speaker or network.

voice.py opens sounddevice lazily and both voice.py and llm.py call urllib.request.urlopen.
Tests that exercise those paths install their own fakes on top of this guard; anything that
slips through fails loudly instead of touching hardware or the OpenAI API.
"""

import urllib.request

import pytest

from app.c_design import voice


def _blocked(*args, **kwargs):
    raise RuntimeError("blocked in tests: real audio device or network access")


@pytest.fixture(autouse=True)
def _no_real_audio_or_network(monkeypatch):
    monkeypatch.setattr(voice, "_sounddevice", _blocked, raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)

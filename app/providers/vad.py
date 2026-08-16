def load_vad():
    from livekit.plugins import silero

    return silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.40,
        activation_threshold=0.5,
    )

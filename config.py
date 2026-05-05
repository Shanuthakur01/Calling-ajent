from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

_PROMPT_FILE = Path(__file__).parent / "system_prompt.txt"

_CONVERSATION_RULES = (
    "CONVERSATION RULES:\n"
    '- If the candidate says any of: "sorry", "pardon", "could you repeat", "say again",'
    ' "I didn\'t catch that", "I didn\'t understand", "what did you say", "come again",'
    " or asks you to repeat — immediately repeat your previous question, rephrased more"
    " simply and slowly. Do NOT advance to the next question.\n"
    "- If they ask to repeat twice in a row, break the question into smaller parts.\n"
    "- Track which questions you've asked; don't repeat them unless asked.\n"
    "- Wait for the candidate to finish speaking before responding."
    " Pauses are natural — never interrupt."
)


def _load_system_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8").strip()
    return (
        "You are a friendly and professional voice AI assistant. "
        "Keep your answers concise and conversational since the user is listening, not reading. "
        "Avoid lists, bullet points, markdown, or special characters. Speak naturally."
    )


class Settings(BaseSettings):
    # Plivo
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_phone_number: str = ""

    # Deepgram (STT)
    deepgram_api_key: str

    # ElevenLabs (TTS)
    elevenlabs_api_key: str = ""

    # Groq (primary LLM)
    groq_api_key: str

    # OpenAI (fallback LLM)
    openai_api_key: Optional[str] = None

    # App
    host: str = "0.0.0.0"
    port: int = 8000
    base_url: str = ""
    debug_mode: bool = False    # env: DEBUG_MODE — enables /debug/config endpoint

    # ElevenLabs tuning
    elevenlabs_voice_id: str = "EMh4QfWp9dtmYomyxDic"
    elevenlabs_model: str = "eleven_turbo_v2_5"      # env: ELEVENLABS_MODEL

    # ElevenLabs voice settings — all env-overridable
    tts_stability: float = 0.5          # env: TTS_STABILITY       (0–1; lower = more expressive)
    tts_similarity: float = 0.75        # env: TTS_SIMILARITY_BOOST (0–1)
    tts_style: float = 0.30             # env: TTS_STYLE            (0–1; adds prosodic variation)
    tts_speaker_boost: bool = True      # env: TTS_SPEAKER_BOOST
    tts_speed: float = 1.0              # env: TTS_SPEED            (0.7–1.2)
    tts_optimize_streaming_latency: int = 4  # env: TTS_OPTIMIZE_STREAMING_LATENCY (0–4)

    # Groq tuning (legacy alias — also read by LLM chain as llm_primary_model default)
    groq_model: str = "llama-3.3-70b-versatile"

    # LLM provider chain
    llm_primary_provider: str = "openai"                  # env: LLM_PRIMARY_PROVIDER  ("openai" | "groq")
    llm_primary_model: str = "gpt-4o-mini"                # env: LLM_PRIMARY_MODEL
    llm_primary_timeout_s: float = 8.0                    # env: LLM_PRIMARY_TIMEOUT_S
    llm_fallback_provider: str = "groq"                   # env: LLM_FALLBACK_PROVIDER  ("groq" | "openai")
    llm_fallback_model: str = "llama-3.3-70b-versatile"   # env: LLM_FALLBACK_MODEL
    llm_fallback_timeout_s: float = 4.0                   # env: LLM_FALLBACK_TIMEOUT_S
    llm_circuit_fail_threshold: int = 2                   # env: LLM_CIRCUIT_FAIL_THRESHOLD
    llm_circuit_cooldown_s: float = 120.0                 # env: LLM_CIRCUIT_COOLDOWN_S

    # Deepgram tuning — endpointing fires speech_final after this many ms of silence
    dg_endpointing_ms: int = 800        # env: DG_ENDPOINTING_MS  (was 1200; primary silence detector)
    dg_utterance_end_ms: int = 1500     # env: DG_UTTERANCE_END_MS (backup end-of-speech)

    # Turn-end detection — client-side coalescing buffer on top of Deepgram endpointing.
    # Intentionally small: its job is only to merge rapid is_final bursts, NOT to add
    # silence time. Real silence detection is done by dg_endpointing_ms above.
    endpoint_ms: int = 250              # env: ENDPOINT_MS  (was 1200 — was wrongly doubling silence)
    min_utterance_words: int = 2        # env: MIN_UTTERANCE_WORDS

    # Agent
    system_prompt: str = ""
    greeting_message: str = (
        "Good day, this is Saanvi calling from the recruitment team. "
        "I'm reaching out regarding the Production Support Engineer position. "
        "Is this a convenient time to speak?"
    )
    max_conversation_turns: int = 30
    hangup_silence_secs: float = 30.0
    barge_in_threshold: float = 0.85   # STT confidence required for interim barge-in
    sentence_delimiters: str = ".!?"   # chars that end a TTS sentence chunk

    # Phase 3 — Speculative LLM
    speculative_llm_enabled: bool = True   # env: SPECULATIVE_LLM_ENABLED

    # Phase 4 — Echo Guard / Barge-in Cascade Fix
    post_speech_mute_ms: int = 600   # env: POST_SPEECH_MUTE_MS (300→600)
    min_barge_in_words: int = 3      # env: MIN_BARGE_IN_WORDS (2→3)

    # Backchannel acks — brief audio clips played while candidate is speaking
    enable_backchannels: bool = True          # env: ENABLE_BACKCHANNELS
    backchannel_min_interval_s: float = 4.0   # env: BACKCHANNEL_MIN_INTERVAL_S
    backchannel_min_user_speech_s: float = 2.0  # env: BACKCHANNEL_MIN_USER_SPEECH_S

    # Phrases to silently drop from STT (IVR/hold-music self-echo).
    # Comma-separated substrings; matched case-insensitively.  env: STT_DROP_PHRASES
    stt_drop_phrases: str = (
        "please hold,please stay on the line,your call is important,"
        "on hold,hold music,thank you for holding,we'll be with you shortly"
    )

    # Single words that bypass the min_utterance_words filter because they carry
    # meaningful intent (acknowledgements, confusion, repeat requests).
    # Comma-separated exact words matched after lowercasing + stripping punctuation.
    # env: SHORT_UTTERANCE_WHITELIST
    short_utterance_whitelist: str = (
        "sorry,pardon,repeat,again,what,huh,"
        "yes,no,yeah,okay,ok,sure,right,correct,"
        "wait,hold,stop"
    )

    # Phase 6 — Recording
    recording_enabled: bool = True     # env: RECORDING_ENABLED
    record_audio: bool = False         # env: RECORD_AUDIO
    recording_dir: str = "recordings"  # env: RECORDING_DIR

    # Phase 7 — Safety & hardening
    hard_timeout_s: float = 600.0       # env: HARD_TIMEOUT_S
    max_llm_response_chars: int = 400   # env: MAX_LLM_RESPONSE_CHARS
    forbidden_phrases: str = (
        "you're hired,you got the job,I'll send you the offer,"
        "interview is confirmed,your salary will be"
    )                                   # env: FORBIDDEN_PHRASES
    tts_circuit_fail_threshold: int = 2    # env: TTS_CIRCUIT_FAIL_THRESHOLD
    tts_circuit_cooldown_s: float = 120.0  # env: TTS_CIRCUIT_COOLDOWN_S

    def stt_drop_phrases_list(self) -> list[str]:
        return [p.strip().lower() for p in self.stt_drop_phrases.split(",") if p.strip()]

    def short_utterance_whitelist_set(self) -> set[str]:
        return {w.strip().lower() for w in self.short_utterance_whitelist.split(",") if w.strip()}

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def model_post_init(self, __context) -> None:
        # If system_prompt is empty or not overridden via .env, load from file
        if not self.system_prompt:
            object.__setattr__(self, "system_prompt", _load_system_prompt())
        # Append conversation rules if not already present
        if _CONVERSATION_RULES not in self.system_prompt:
            object.__setattr__(
                self, "system_prompt",
                self.system_prompt + "\n\n" + _CONVERSATION_RULES,
            )
        # Strip trailing slash so all URL construction avoids double-slashes
        if self.base_url.endswith("/"):
            object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        if not self.base_url:
            import warnings
            warnings.warn(
                "BASE_URL is not set — /incoming-call and /media-stream URLs will be wrong. "
                "Set BASE_URL in .env to your tunnel URL.",
                stacklevel=2,
            )


settings = Settings()

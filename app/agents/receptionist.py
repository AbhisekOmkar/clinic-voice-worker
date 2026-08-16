"""AgentSession assembly for the clinic receptionist."""

from livekit import rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.agents import metrics as lk_metrics
from loguru import logger

from app.config.settings import settings
from app.metrics.latency import LatencyCollector
from app.prompts.system import build_system_prompt, opening_line
from app.state.session_state import CallState
from app.tools import ALL_TOOLS


class ReceptionistRunner:
    def __init__(self, ctx, state: CallState, vad, participant=None):
        self.ctx = ctx
        self.state = state
        self.vad = vad
        self.participant = participant
        self.session: AgentSession | None = None
        self.latency = LatencyCollector()

    def build_session(self, stt=None, llm=None, tts=None, turn_detection=None) -> AgentSession:
        from app.providers.llm import create_llm
        from app.providers.stt import create_stt
        from app.providers.tts import create_tts

        if turn_detection is None:
            try:
                from livekit.plugins.turn_detector.multilingual import MultilingualModel

                turn_detection = MultilingualModel()
            except Exception as exc:
                logger.warning(f"turn detector unavailable, falling back to VAD-only: {exc}")
                turn_detection = None

        session = AgentSession(
            userdata=self.state,
            stt=stt or create_stt(),
            llm=llm or create_llm(),
            tts=tts or create_tts(),
            vad=self.vad,
            turn_detection=turn_detection,
            allow_interruptions=settings.allow_interruptions,
            min_endpointing_delay=settings.min_endpointing_delay,
            max_endpointing_delay=settings.max_endpointing_delay,
        )
        self.session = session
        self._register_handlers(session)
        return session

    def _register_handlers(self, session: AgentSession) -> None:
        @session.on("metrics_collected")
        def _on_metrics(event):
            metric_obj = getattr(event, "metrics", event)
            self.latency.on_metrics(metric_obj, self.state.language)

        @session.on("conversation_item_added")
        def _on_item(event):
            item = getattr(event, "item", None)
            if item is None:
                return
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None) or ""
            if role in ("user", "assistant") and text:
                self.state.add_turn("user" if role == "user" else "agent", text)
                self.state.persist_soon()

    def build_agent(self) -> Agent:
        return Agent(instructions=build_system_prompt(self.state), tools=ALL_TOOLS)

    def room_input_options(self) -> RoomInputOptions | None:
        if not settings.enable_noise_cancellation:
            return None
        try:
            from livekit.plugins import noise_cancellation

            is_sip = (
                self.participant is not None
                and self.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            )
            nc = noise_cancellation.BVCTelephony() if is_sip else noise_cancellation.BVC()
            return RoomInputOptions(noise_cancellation=nc)
        except Exception as exc:
            logger.warning(f"noise cancellation unavailable, continuing without: {exc}")
            return None

    async def start(self) -> None:
        agent = self.build_agent()
        await self.session.start(
            agent=agent, room=self.ctx.room, room_input_options=self.room_input_options()
        )
        self.session.say(opening_line(self.state), allow_interruptions=True)

    async def usage_summary(self) -> dict:
        return self.latency.payload()

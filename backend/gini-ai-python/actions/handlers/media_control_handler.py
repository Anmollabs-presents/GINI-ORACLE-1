# actions/handlers/media_control_handler.py
import re
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from actions.system_executor import create_media_executor, ActionStatus


class MediaControlHandler(BaseIntentHandler):
    intent_name = "media_control"

    def __init__(self, mock: bool = False):
        super().__init__()
        self._executor = create_media_executor(mock=mock)

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "play"

        if sub == "play":
            track = self._extract_track(cmd)
            result_exec = self._executor.media_play()
            if track:
                return self._from_result(
                    result_exec,
                    "play",
                    track=track,
                    response_override=f"Attempting to play '{track}'."
                )
            return self._from_result(result_exec, "play", response_override="Resuming playback.")

        elif sub == "pause":
            result_exec = self._executor.media_pause()
            return self._from_result(result_exec, "pause", response_override="Paused.")

        elif sub == "stop":
            result_exec = self._executor.media_stop()
            return self._from_result(result_exec, "stop", response_override="Playback stopped.")

        elif sub == "next":
            result_exec = self._executor.media_next()
            return self._from_result(result_exec, "next", response_override="Skipping to the next track.")

        elif sub == "previous":
            result_exec = self._executor.media_previous()
            return self._from_result(result_exec, "previous", response_override="Going to the previous track.")

        elif sub == "shuffle":
            state = "off" if cmd.has_negation else "on"
            return self._ok(f"Shuffle turned {state}.", sub="shuffle", shuffle=state)

        elif cmd.has_any("repeat"):
            state = "off" if cmd.has_negation else "on"
            return self._ok(f"Repeat turned {state}.", sub="repeat", repeat=state)

        return self._ok(f"Media command '{sub}' executed.", sub=sub)

    def _from_result(self, result, sub: str, response_override: str = None, **extra) -> dict:
        message = response_override or result.message
        if result.success:
            return self._ok(message, sub=sub, **extra)
        if result.status == ActionStatus.NOT_SUPPORTED:
            return self._ok(result.message, sub=sub, **extra)
        return self._error(message, reason=result.error or result.status.value)

    def _extract_track(self, cmd: ParsedCommand) -> str:
        # "play [song name] by [artist]" or "play [song name]"
        match = re.search(r"play\s+(.+?)(?:\s+by\s+.+)?$", cmd.normalized)
        if match:
            track = match.group(1).strip()
            # Exclude generic media words
            if track not in {"music", "song", "video", "podcast", "something"}:
                return track.title()
        return ""


__all__ = ["MediaControlHandler"]

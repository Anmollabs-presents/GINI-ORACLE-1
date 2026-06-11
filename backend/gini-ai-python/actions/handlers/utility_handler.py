# actions/handlers/utility_handler.py
import re
from datetime import datetime, date
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult


class UtilityHandler(BaseIntentHandler):
    intent_name = "utility"

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "general"

        if sub == "timer":
            return await self._handle_timer(cmd)
        elif sub == "alarm":
            return await self._handle_alarm(cmd)
        elif sub == "reminder":
            return await self._handle_reminder(cmd)
        elif sub == "time":
            return await self._handle_time(cmd)
        elif sub == "date":
            return await self._handle_date(cmd)
        elif sub == "calculate":
            return await self._handle_calculate(cmd)
        elif sub == "convert":
            return await self._handle_convert(cmd)
        elif sub == "note":
            return await self._handle_note(cmd)

        return self._ok(f"Utility command '{sub}' acknowledged.", sub=sub)

    async def _handle_timer(self, cmd: ParsedCommand) -> dict:
        duration = self._extract_duration(cmd)
        if duration:
            mins, secs = duration
            label = f"{mins}m {secs}s" if secs else f"{mins} minute{'s' if mins != 1 else ''}"
            return self._ok(
                f"Timer set for {label}.",
                sub="timer", minutes=mins, seconds=secs,
            )
        return self._ok("How long should I set the timer for?", sub="timer")

    async def _handle_alarm(self, cmd: ParsedCommand) -> dict:
        time_str = cmd.entities.get("time", "")
        if time_str:
            return self._ok(f"Alarm set for {time_str}.", sub="alarm", time=time_str)
        return self._ok("What time should I set the alarm for?", sub="alarm")

    async def _handle_time(self, cmd: ParsedCommand) -> dict:
        now = datetime.now()
        formatted = now.strftime("%I:%M %p").lstrip("0")
        return self._ok(f"The current time is {formatted}.", sub="time", time=formatted)

    async def _handle_date(self, cmd: ParsedCommand) -> dict:
        today = date.today()
        formatted = today.strftime("%A, %B %d, %Y")
        return self._ok(f"Today is {formatted}.", sub="date", date=today.isoformat())

    async def _handle_reminder(self, cmd: ParsedCommand) -> dict:
        match = re.search(r"remind(?:\s+me)?(?:\s+to)?\s+(.+?)(?:\s+at\s+(.+))?$", cmd.normalized)
        task = match.group(1).strip() if match else ""
        time_str = cmd.entities.get("time", "")
        if isinstance(time_str, list):
            time_str = time_str[0]
        if task:
            msg = f"Reminder set: '{task}'"
            msg += f" at {time_str}" if time_str else "."
            return self._ok(msg, sub="reminder", task=task, time=time_str)
        return self._ok("What would you like me to remind you about?", sub="reminder")

    async def _handle_calculate(self, cmd: ParsedCommand) -> dict:
        # Extract math expression
        expr = re.sub(
            r"\b(?:calculate|calc|compute|what\s+is|whats)\b", "",
            cmd.normalized,
        ).strip()
        # Only allow safe math chars
        safe = re.sub(r"[^\d\s\+\-\*\/\.\(\)\%]", "", expr).strip()
        if safe:
            try:
                result_val = eval(safe)  # Safe: only digits/operators allowed
                return self._ok(
                    f"The result is {result_val}.",
                    sub="calculate", expression=safe, result=result_val,
                )
            except Exception:
                pass
        return self._ok("What would you like me to calculate?", sub="calculate")

    async def _handle_convert(self, cmd: ParsedCommand) -> dict:
        return self._ok(
            "Conversion feature is coming soon. Please specify the value and unit.",
            sub="convert",
        )

    async def _handle_note(self, cmd: ParsedCommand) -> dict:
        match = re.search(r"(?:note|write|add)\s+(?:that\s+|down\s+)?(.+)$", cmd.normalized)
        content = match.group(1).strip() if match else ""
        if content:
            return self._ok(f"Note saved: '{content}'.", sub="note", content=content)
        return self._ok("What would you like to note down?", sub="note")

    def _extract_duration(self, cmd: ParsedCommand):
        """Extract minutes and seconds from command."""
        mins = 0
        secs = 0
        m = re.search(r"(\d+)\s*(?:minute|min|m)\b", cmd.normalized)
        s = re.search(r"(\d+)\s*(?:second|sec|s)\b", cmd.normalized)
        if m: mins = int(m.group(1))
        if s: secs = int(s.group(1))
        if mins or secs:
            return mins, secs
        # Fallback: bare number → minutes
        nums = re.findall(r"\b(\d+)\b", cmd.normalized)
        if nums:
            return int(nums[0]), 0
        return None


__all__ = ["UtilityHandler"]

# actions/handlers/question_answer_handler.py
import re
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult


KNOWLEDGE_BASE = {
    "photosynthesis": (
        "Photosynthesis is the process by which plants and some other organisms "
        "convert sunlight into chemical energy, using carbon dioxide and water."
    ),
    "gravity": (
        "Gravity is the force that pulls objects with mass toward each other, "
        "giving weight to physical objects and keeping planets in orbit."
    ),
    "earth": (
        "Earth is the third planet from the Sun and the only planet known to support life."
    ),
    "python": (
        "Python is a popular programming language known for its readability, "
        "versatility, and large ecosystem of libraries."
    ),
    "albert einstein": (
        "Albert Einstein was a theoretical physicist who developed the theory of relativity "
        "and helped shape modern physics."
    ),
    "eiffel tower": (
        "The Eiffel Tower is an iconic iron tower in Paris, France, built for the 1889 World's Fair."
    ),
    "new year's day": (
        "New Year's Day is celebrated on January 1st each year as the first day of the Gregorian calendar."
    ),
    "the sky": (
        "The sky appears blue because air molecules scatter blue light from the sun more than they scatter red light."
    ),
    "the sky is blue": (
        "The sky appears blue because air molecules scatter blue light from the sun more than they scatter red light."
    ),
    "computer": (
        "A computer is an electronic device that processes data and performs calculations based on instructions."
    ),
    "internet": (
        "The Internet is a global network of computers that allows people to share information and communicate."
    ),
    "photosynthesis process": (
        "The photosynthesis process uses sunlight to turn carbon dioxide and water into glucose and oxygen."
    ),
}


FALLBACK_RESPONSES = [
    "I don't have a precise answer for that yet, but I can help with simple definitions and general facts.",
    "That's a great question. I don't know it yet, but I can explain terms like photosynthesis, gravity, or Python.",
    "I don't have enough knowledge for that one yet. Try asking me something like 'what is gravity' or 'who is Albert Einstein'.",
]


class QuestionAnswerHandler(BaseIntentHandler):
    intent_name = "question_answer"

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        question = cmd.raw.strip()
        sub = self._classify_question(cmd)
        answer = self._answer_question(cmd, sub)

        response = answer if answer else self._fallback_answer(question)
        known = bool(answer)

        if not known:
            response = self._fallback_answer(question)

        return self._ok(
            response,
            sub=sub,
            question=question,
            source="knowledge" if known else "fallback",
            known=known,
        )

    def _classify_question(self, cmd: ParsedCommand) -> str:
        if cmd.has_any("define", "meaning", "explain"):
            return "definition"
        if cmd.has_any("compare", "difference"):
            return "comparison"
        if cmd.has_any("what"):    return "what"
        if cmd.has_any("who"):     return "who"
        if cmd.has_any("where"):   return "where"
        if cmd.has_any("when"):    return "when"
        if cmd.has_any("why"):     return "why"
        if cmd.has_any("how"):     return "how"
        return "general"

    def _answer_question(self, cmd: ParsedCommand, sub: str) -> str:
        topic = self._extract_topic(cmd)
        if not topic:
            return ""

        normalized_topic = self._normalize_topic(topic)

        # Direct knowledge lookup by normalized topic.
        if normalized_topic in KNOWLEDGE_BASE:
            return KNOWLEDGE_BASE[normalized_topic]

        # Fuzzy matching: use contains checks to handle phrases.
        for key, answer in KNOWLEDGE_BASE.items():
            if key in normalized_topic or normalized_topic in key:
                return answer

        return ""

    def _extract_topic(self, cmd: ParsedCommand) -> str:
        patterns = [
            r"what is (.+)",
            r"who is (.+)",
            r"where is (.+)",
            r"when is (.+)",
            r"why is (.+)",
            r"how (?:does|do|is|are|can|should|did) (.+)",
            r"define (.+)",
            r"explain (.+)",
            r"meaning of (.+)",
            r"what does (.+) mean",
        ]
        normalized = cmd.normalized
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(1).strip()
        return normalized

    def _normalize_topic(self, topic: str) -> str:
        topic = topic.lower().strip()
        topic = re.sub(r"[?!.]$", "", topic)
        topic = re.sub(r"[^\w\s']", "", topic)
        topic = re.sub(r"\b(the|a|an)\b", "", topic)
        return " ".join(topic.split()).strip()

    def _fallback_answer(self, question: str) -> str:
        index = len(question) % len(FALLBACK_RESPONSES)
        return FALLBACK_RESPONSES[index]


__all__ = ["QuestionAnswerHandler"]

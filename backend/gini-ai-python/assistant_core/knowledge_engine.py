# ============================================================
# GINI-ORACLE-1 — Local Knowledge Engine
# assistant_core/knowledge_engine.py
# ============================================================
"""
Offline knowledge base covering:
  - Science (physics, chemistry, biology, astronomy)
  - Computer science and programming
  - Mathematics concepts
  - Geography and history basics
  - General facts

All knowledge is stored locally — no internet required.
Query: exact match → prefix match → keyword match → None
"""

import re
from typing import Optional
from utils.logger import get_logger

log = get_logger(__name__)


# ── Knowledge base ────────────────────────────────────────────
# Format: "normalized topic key": "explanation"

KNOWLEDGE_BASE: dict[str, str] = {

    # ── Science — Biology ────────────────────────────────────
    "photosynthesis": (
        "Photosynthesis is the process by which plants, algae, and some bacteria "
        "convert sunlight, water, and carbon dioxide into glucose (sugar) and oxygen. "
        "It takes place mainly in the chloroplasts of plant cells using the green pigment chlorophyll. "
        "The overall equation is: 6CO₂ + 6H₂O + light → C₆H₁₂O₆ + 6O₂."
    ),
    "cell": (
        "A cell is the basic structural and functional unit of all living organisms. "
        "There are two main types: prokaryotic cells (no nucleus, like bacteria) and "
        "eukaryotic cells (with a nucleus, found in plants, animals, and fungi). "
        "Cells contain DNA, carry out metabolism, and reproduce by division."
    ),
    "dna": (
        "DNA (deoxyribonucleic acid) is the molecule that carries the genetic instructions "
        "for the development, functioning, and reproduction of all known organisms. "
        "It is a double helix made of four nucleotide bases: adenine (A), thymine (T), "
        "guanine (G), and cytosine (C). The sequence of these bases encodes genes."
    ),
    "evolution": (
        "Evolution is the process of change in inherited characteristics of biological populations "
        "over successive generations. Proposed by Charles Darwin, natural selection is the mechanism "
        "where individuals with favorable traits survive and reproduce more successfully, "
        "passing those traits to offspring over time."
    ),
    "mitosis": (
        "Mitosis is a type of cell division that produces two genetically identical daughter cells. "
        "It has four stages: prophase, metaphase, anaphase, and telophase. "
        "Mitosis is used for growth, tissue repair, and asexual reproduction."
    ),

    # ── Science — Physics ────────────────────────────────────
    "gravity": (
        "Gravity is the fundamental force of attraction between objects that have mass. "
        "On Earth, it gives weight to objects and causes them to fall at 9.8 m/s² (g). "
        "Isaac Newton described gravity as an attractive force between masses. "
        "Albert Einstein later redefined it as the curvature of spacetime caused by mass and energy."
    ),
    "newton's laws": (
        "Newton's Three Laws of Motion: "
        "1) An object at rest stays at rest and an object in motion stays in motion unless acted upon by a force. "
        "2) Force equals mass times acceleration (F = ma). "
        "3) For every action there is an equal and opposite reaction."
    ),
    "speed of light": (
        "The speed of light in a vacuum is approximately 299,792,458 metres per second (about 3×10⁸ m/s). "
        "It is denoted by 'c' and is the fastest speed anything can travel in the universe. "
        "This constant is fundamental to Einstein's theory of special relativity (E = mc²)."
    ),
    "electricity": (
        "Electricity is the flow of electric charge, typically carried by electrons through a conductor. "
        "Key concepts: voltage (V) is electrical pressure, current (I) is flow of charge in amperes, "
        "resistance (R) opposes flow in ohms. Ohm's Law: V = I × R."
    ),
    "electromagnetism": (
        "Electromagnetism is one of the four fundamental forces, describing the interaction between "
        "electrically charged particles. It encompasses both electric and magnetic phenomena, "
        "unified by Maxwell's equations. Light itself is an electromagnetic wave."
    ),
    "thermodynamics": (
        "Thermodynamics studies heat, work, and energy. The four laws: "
        "0th — thermal equilibrium exists. "
        "1st — energy cannot be created or destroyed (conservation of energy). "
        "2nd — entropy of an isolated system always increases. "
        "3rd — absolute zero temperature is unattainable."
    ),

    # ── Science — Chemistry ──────────────────────────────────
    "atom": (
        "An atom is the smallest unit of a chemical element. It consists of a nucleus "
        "containing protons (positively charged) and neutrons (neutral), surrounded by "
        "electrons (negatively charged) in orbitals. The number of protons defines the element."
    ),
    "periodic table": (
        "The periodic table organises all 118 known chemical elements by atomic number, "
        "electron configuration, and recurring chemical properties. "
        "Elements in the same column (group) share similar properties. "
        "It was first systematically arranged by Dmitri Mendeleev in 1869."
    ),
    "chemical bond": (
        "A chemical bond is the attraction between atoms that allows molecules to form. "
        "Types: ionic bonds (electron transfer between metals and non-metals), "
        "covalent bonds (electron sharing between non-metals), "
        "and metallic bonds (electron sea in metals)."
    ),

    # ── Science — Astronomy ──────────────────────────────────
    "solar system": (
        "The solar system consists of the Sun and everything gravitationally bound to it: "
        "8 planets (Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune), "
        "dwarf planets, moons, asteroids, comets, and dust. "
        "It is located in the Milky Way galaxy, about 26,000 light-years from its centre."
    ),
    "black hole": (
        "A black hole is a region of spacetime where gravity is so strong that nothing — "
        "not even light — can escape once past the event horizon. "
        "They form when massive stars collapse at the end of their lives. "
        "The boundary around a black hole is called the event horizon; "
        "the centre is called the singularity."
    ),
    "big bang": (
        "The Big Bang is the prevailing cosmological model explaining the origin of the universe. "
        "About 13.8 billion years ago, the universe began from an extremely hot, dense state "
        "and has been expanding and cooling ever since. "
        "Evidence includes cosmic microwave background radiation and the redshift of distant galaxies."
    ),
    "earth": (
        "Earth is the third planet from the Sun and the only known planet to support life. "
        "It has a diameter of about 12,742 km, one natural satellite (the Moon), "
        "and takes 365.25 days to orbit the Sun. "
        "About 71% of its surface is covered by water."
    ),

    # ── Computer Science ─────────────────────────────────────
    "algorithm": (
        "An algorithm is a step-by-step procedure or set of rules for solving a problem or "
        "performing a computation. Key properties: finite (terminates), definite (each step is clear), "
        "effective (each step is feasible), and produces output. "
        "Examples: sorting algorithms, search algorithms, pathfinding algorithms."
    ),
    "binary": (
        "Binary is the base-2 number system using only digits 0 and 1. "
        "Computers use binary because transistors have two states: on (1) and off (0). "
        "Decimal 10 = binary 1010. Each binary digit is called a bit; 8 bits make 1 byte."
    ),
    "cpu": (
        "A CPU (Central Processing Unit) is the primary component of a computer that executes instructions. "
        "It fetches, decodes, and executes instructions from memory. "
        "Modern CPUs have multiple cores allowing parallel processing. "
        "Speed is measured in GHz (billions of clock cycles per second)."
    ),
    "ram": (
        "RAM (Random Access Memory) is temporary, fast memory used to store data that the CPU "
        "is actively using. It is volatile — data is lost when power is cut. "
        "More RAM allows more applications to run simultaneously without slowdown. "
        "Common sizes today: 8 GB, 16 GB, 32 GB."
    ),
    "operating system": (
        "An operating system (OS) is software that manages computer hardware and provides services "
        "for programs. It handles memory management, process scheduling, file systems, and I/O. "
        "Examples: Windows, macOS, Linux, Android, iOS."
    ),
    "internet": (
        "The Internet is a global network of interconnected computers communicating via standardised "
        "protocols (mainly TCP/IP). It supports services like the World Wide Web, email, video calls, "
        "and file sharing. The Web (HTTP/HTTPS) is one service that runs on top of the Internet."
    ),
    "machine learning": (
        "Machine learning (ML) is a branch of AI where systems learn patterns from data to make "
        "decisions without being explicitly programmed for each case. "
        "Types: supervised learning (labelled data), unsupervised learning (unlabelled data), "
        "reinforcement learning (reward-based). Examples: image recognition, spam filters, recommendations."
    ),
    "artificial intelligence": (
        "Artificial Intelligence (AI) is the simulation of human intelligence by machines. "
        "It encompasses machine learning, natural language processing, computer vision, robotics, "
        "and expert systems. AI can be narrow (specific task) or general (human-level reasoning)."
    ),
    "database": (
        "A database is an organised collection of structured information stored and accessed electronically. "
        "Types: relational databases (SQL — MySQL, PostgreSQL, SQLite) use tables and relationships; "
        "NoSQL databases (MongoDB, Redis) use documents, key-value pairs, or graphs. "
        "CRUD stands for Create, Read, Update, Delete — the four basic operations."
    ),
    "cloud computing": (
        "Cloud computing delivers computing services — servers, storage, databases, networking, "
        "software — over the internet. Providers: AWS, Google Cloud, Microsoft Azure. "
        "Models: IaaS (infrastructure), PaaS (platform), SaaS (software). "
        "Benefits: scalability, pay-as-you-go, no hardware maintenance."
    ),

    # ── Programming ──────────────────────────────────────────
    "python": (
        "Python is a high-level, interpreted, general-purpose programming language created by "
        "Guido van Rossum in 1991. Known for its clear, readable syntax, large standard library, "
        "and massive ecosystem (NumPy, Pandas, TensorFlow, Django, FastAPI). "
        "Used for: web development, data science, AI/ML, automation, scripting."
    ),
    "object oriented programming": (
        "Object-oriented programming (OOP) is a paradigm organising code around objects — "
        "instances of classes that bundle data (attributes) and behaviour (methods). "
        "Four pillars: Encapsulation (data hiding), Abstraction (hiding complexity), "
        "Inheritance (reusing code from parent classes), Polymorphism (same interface, different behaviour)."
    ),
    "api": (
        "An API (Application Programming Interface) is a set of rules that allows different software "
        "applications to communicate. REST APIs use HTTP methods (GET, POST, PUT, DELETE) and return "
        "JSON or XML. APIs let developers use existing services without knowing their internal workings."
    ),
    "git": (
        "Git is a distributed version control system created by Linus Torvalds in 2005. "
        "It tracks changes to source code, allowing collaboration and history management. "
        "Key commands: git init, git clone, git add, git commit, git push, git pull, git branch, git merge."
    ),
    "html": (
        "HTML (HyperText Markup Language) is the standard markup language for creating web pages. "
        "It defines the structure and content using elements like <html>, <head>, <body>, "
        "<h1>–<h6>, <p>, <a>, <img>, <div>, <form>. "
        "HTML5 introduced semantic elements like <nav>, <article>, <section>."
    ),
    "css": (
        "CSS (Cascading Style Sheets) controls the visual presentation of HTML elements. "
        "It handles layout, colours, fonts, spacing, and animations. "
        "Key concepts: selectors, the box model, flexbox, grid, media queries for responsiveness."
    ),
    "javascript": (
        "JavaScript is the programming language of the web, running in browsers to make pages interactive. "
        "It also runs server-side via Node.js. Key features: dynamic typing, event-driven, "
        "asynchronous (Promises, async/await), prototype-based OOP."
    ),
    "fastapi": (
        "FastAPI is a modern, high-performance Python web framework for building APIs. "
        "It uses Python type hints for automatic data validation via Pydantic, "
        "generates OpenAPI docs automatically, and supports async/await natively. "
        "Typically used with Uvicorn as the ASGI server."
    ),
    "recursion": (
        "Recursion is a programming technique where a function calls itself to solve a smaller "
        "version of the same problem. Every recursive function needs a base case (termination condition) "
        "to prevent infinite loops. Examples: factorial, Fibonacci, tree traversal."
    ),

    # ── Mathematics ──────────────────────────────────────────
    "pi": (
        "Pi (π) is the ratio of a circle's circumference to its diameter, approximately 3.14159. "
        "It is an irrational number — its decimal expansion never ends or repeats. "
        "Pi appears in formulas for circles, spheres, waves, and many areas of mathematics."
    ),
    "pythagoras theorem": (
        "The Pythagorean theorem states that in a right-angled triangle, "
        "the square of the hypotenuse (longest side) equals the sum of the squares of the other two sides: "
        "a² + b² = c². Named after the ancient Greek mathematician Pythagoras."
    ),
    "prime number": (
        "A prime number is a natural number greater than 1 that has no positive divisors other than 1 and itself. "
        "Examples: 2, 3, 5, 7, 11, 13. 2 is the only even prime. "
        "The Fundamental Theorem of Arithmetic states every integer > 1 is a product of primes."
    ),

    # ── History & People ─────────────────────────────────────
    "albert einstein": (
        "Albert Einstein (1879–1955) was a German-born theoretical physicist. "
        "He developed the theory of special relativity (1905) and general relativity (1915). "
        "His most famous equation, E = mc², shows mass and energy are interchangeable. "
        "He received the 1921 Nobel Prize in Physics for his explanation of the photoelectric effect."
    ),
    "world war 2": (
        "World War II (1939–1945) was a global conflict involving most of the world's nations. "
        "The Allies (UK, USA, USSR, France) fought against the Axis powers (Germany, Italy, Japan). "
        "It began with Germany's invasion of Poland and ended with the surrender of Germany (May 1945) "
        "and Japan (September 1945). Over 70 million people died, making it the deadliest conflict in history."
    ),

    # ── Geography ────────────────────────────────────────────
    "india": (
        "India is a country in South Asia and the world's most populous nation with over 1.4 billion people. "
        "It is the seventh-largest country by area, bordered by Pakistan, China, Nepal, Bhutan, Bangladesh, "
        "and Myanmar. Capital: New Delhi. It has 28 states and 8 union territories."
    ),
    "himalayas": (
        "The Himalayas are a mountain range in Asia, forming the world's highest mountains. "
        "They span five countries: India, Nepal, Bhutan, China, and Pakistan. "
        "Mount Everest (8,848.86 m) is the highest peak on Earth, located on the Nepal-China border."
    ),

    # ── Health ───────────────────────────────────────────────
    "diabetes": (
        "Diabetes is a chronic condition where the body cannot properly regulate blood sugar (glucose). "
        "Type 1: the immune system attacks insulin-producing cells (autoimmune). "
        "Type 2: the body becomes resistant to insulin or doesn't produce enough (lifestyle-related, most common). "
        "Management includes diet, exercise, medication, and insulin therapy."
    ),
    "virus": (
        "A virus is a tiny infectious agent that can only replicate inside a living host cell. "
        "Viruses are not considered fully alive — they have no metabolism of their own. "
        "Examples: influenza, HIV, SARS-CoV-2. "
        "Antiviral drugs and vaccines help prevent or treat viral infections."
    ),
}


class KnowledgeEngine:
    """
    Offline knowledge retrieval engine.
    Searches the local knowledge base using exact, prefix, and keyword matching.
    Returns (answer, confidence_0_to_1) or (None, 0) if not found.
    """

    # Question prefixes to strip before topic extraction
    _STRIP = re.compile(
        r"^(what\s+is|what\s+are|who\s+is|who\s+are|where\s+is|when\s+is|"
        r"explain|define|tell\s+me\s+about|describe|how\s+does|how\s+do|"
        r"what\s+does|meaning\s+of|definition\s+of)\s+",
        re.IGNORECASE,
    )
    _CLEAN = re.compile(r"[?!.]$")

    def query(self, user_input: str) -> tuple[Optional[str], float]:
        """
        Search the knowledge base for user_input.

        Returns:
            (answer, confidence)   — confidence 0.0–1.0
            (None, 0.0)            — not found
        """
        topic = self._extract_topic(user_input)
        if not topic:
            return None, 0.0

        # 1. Exact match
        if topic in KNOWLEDGE_BASE:
            return KNOWLEDGE_BASE[topic], 1.0

        # 2. Prefix match (query contains key)
        for key, answer in KNOWLEDGE_BASE.items():
            if key in topic:
                return answer, 0.95
            if topic in key:
                return answer, 0.90

        # 3. Word overlap match
        topic_words = set(topic.split())
        best_key = None
        best_score = 0.0
        for key, answer in KNOWLEDGE_BASE.items():
            key_words = set(key.split())
            overlap = len(topic_words & key_words)
            if overlap == 0:
                continue
            score = overlap / max(len(topic_words), len(key_words))
            if score > best_score:
                best_score = score
                best_key = key

        if best_key and best_score >= 0.5:
            return KNOWLEDGE_BASE[best_key], round(best_score * 0.85, 2)

        return None, 0.0

    def _extract_topic(self, text: str) -> str:
        """Strip question words and punctuation to get the core topic."""
        t = text.strip().lower()
        t = self._CLEAN.sub("", t)
        t = self._STRIP.sub("", t)
        # Remove "the", "a", "an"
        t = re.sub(r"\b(the|a|an)\b", "", t)
        return " ".join(t.split())


# Singleton
_engine: Optional[KnowledgeEngine] = None

def get_knowledge_engine() -> KnowledgeEngine:
    global _engine
    if _engine is None:
        _engine = KnowledgeEngine()
    return _engine


__all__ = ["KnowledgeEngine", "get_knowledge_engine", "KNOWLEDGE_BASE"]

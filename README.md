# 🌟 GINI-ORACLE-1

> **Gini.ai** — Emotion-aware AI Operating System  
> Controls smart homes, hospitals, vehicles, mobile devices — all through one unified AI brain.

---

## 🚀 Quick Start

```bash
# 1. Navigate to backend
cd backend/gini-ai-python

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment
cp .env.example .env
# Edit .env and add your API keys

# 5. Start Gini
python main.py
```

Server runs at: `http://localhost:8000`  
API Docs at: `http://localhost:8000/docs`

---

## 📁 Project Structure

```
GINI-ORACLE-1/
├── backend/
│   └── gini-ai-python/
│       ├── core/           # Assistant brain, emotion engine
│       ├── voice/          # Voice input/output
│       ├── actions/        # Device control routing
│       ├── models/         # Pydantic schemas
│       ├── utils/          # Logger, health checks
│       ├── config/         # Centralized settings
│       ├── logs/           # Auto-generated log files
│       ├── tests/          # pytest test suite
│       ├── main.py         # Startup entrypoint
│       └── requirements.txt
├── frontend/               # (Phase 2)
├── configs/                # Global config files
└── .gitignore
```

---

## 🧪 Run Tests

```bash
cd backend/gini-ai-python
pytest tests/ -v
```

---

## 🔑 Key Features (Phase 1)

- ✅ Modular production-grade architecture
- ✅ Centralized config system (pydantic-settings)
- ✅ Centralized logging (loguru — rotating file + console)
- ✅ Startup health checks
- ✅ FastAPI backend with `/health` and `/chat` endpoints
- ✅ Emotion detection from text (positive/negative/neutral)
- ✅ Action router (smart home, hospital, vehicle, mobile)
- ✅ Full test suite

---

## 📍 Roadmap

| Phase | Focus |
|-------|-------|
| ✅ Phase 1 | Foundation architecture |
| 🔜 Phase 2 | LLM integration + full emotion engine |
| 🔜 Phase 3 | Device control (IoT, hospital, vehicles) |
| 🔜 Phase 4 | Frontend dashboard + voice |
| 🔜 Phase 5 | Mobile OS layer |

---

*Built with ❤️ for India — by Anmol Srivastav*

# GINI-ORACLE-1
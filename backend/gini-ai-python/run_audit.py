import sys
import os
import asyncio
from fastapi.testclient import TestClient

sys.path.append(r'c:\anmol\HELL MARRY\GINI-ORACLE-1-resilience\GINI-ORACLE-1\backend\gini-ai-python')

from main import app

client = TestClient(app)

def run_tests():
    print("=== STARTING GINI AUDIT ===")
    
    # Check Health
    print("\n--- Testing Health ---")
    response = client.get("/health")
    print(f"Health Status Code: {response.status_code}")
    if response.status_code == 200:
        print("Health check PASSED")
    else:
        print(f"Health check FAILED: {response.json()}")

    # Test Chat & Memory
    print("\n--- Testing Memory & Chat ---")
    user_id = "audit_user_1"
    session_id = "session_1"
    
    # 1. Store Memory
    msg1 = {"message": "Remember my name is Anmol", "user_id": user_id, "session_id": session_id}
    res1 = client.post("/chat", json=msg1)
    print(f"Msg1 ('Remember my name is Anmol'): {res1.json() if res1.status_code==200 else res1.text}")
    
    # 2. Retrieve Memory
    msg2 = {"message": "What is my name?", "user_id": user_id, "session_id": session_id}
    res2 = client.post("/chat", json=msg2)
    print(f"Msg2 ('What is my name?'): {res2.json() if res2.status_code==200 else res2.text}")
    
    # 3. Store Another Memory
    msg3 = {"message": "Remember my favorite color is blue", "user_id": user_id, "session_id": session_id}
    res3 = client.post("/chat", json=msg3)
    print(f"Msg3 ('Remember my favorite color is blue'): {res3.json() if res3.status_code==200 else res3.text}")
    
    # 4. Context Follow up
    msg4 = {"message": "What is Python?", "user_id": user_id, "session_id": session_id}
    res4 = client.post("/chat", json=msg4)
    print(f"Msg4 ('What is Python?'): {res4.json() if res4.status_code==200 else res4.text}")
    
    msg5 = {"message": "Tell me more about it.", "user_id": user_id, "session_id": session_id}
    res5 = client.post("/chat", json=msg5)
    print(f"Msg5 ('Tell me more about it.'): {res5.json() if res5.status_code==200 else res5.text}")
    
    # Check Memory Endpoint
    print("\n--- Checking SQLite Memory Persistence ---")
    mem_res = client.get(f"/memory?user_id={user_id}")
    print(f"Memory API response: {mem_res.json() if mem_res.status_code==200 else mem_res.text}")

    print("\n--- Testing Action Engine ---")
    act_res = client.post("/chat", json={"message": "open chrome", "user_id": user_id, "session_id": session_id})
    print(f"Action (open chrome): {act_res.json() if act_res.status_code==200 else act_res.text}")

with client:
    run_tests()

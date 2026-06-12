import asyncio
import httpx
import time
import os

BASE_URL = "http://localhost:8000"
DB_PATH = r"backend\gini-ai-python\gini.db"

async def send_chat(client, message, session_id, user_id):
    start = time.time()
    try:
        response = await client.post(
            f"{BASE_URL}/chat",
            json={"message": message, "session_id": session_id, "user_id": user_id},
            timeout=300.0
        )
        if response.status_code == 200:
            return {"status": "success", "response": response.json()["response"], "latency": time.time() - start}
        else:
            return {"status": "error", "error": response.text, "latency": time.time() - start}
    except Exception as e:
        return {"status": "error", "error": str(e), "latency": time.time() - start}

async def test_20_turn_conversation(client):
    print("\n=== TEST 4: 20-TURN CONVERSATION ===")
    session_id = "turn-20-real-test"
    
    # Pre-seed memory
    await send_chat(client, "Hi! My name is Alpha. Remember this.", session_id, "user-20")
    
    for i in range(1, 21):
        print(f"Turn {i}/20...")
        msg = f"This is message number {i}. If I told you my name earlier, what is it?" if i % 5 == 0 else f"This is message number {i}. Acknowledge."
        res = await send_chat(client, msg, session_id, "user-20")
        print(f"  Latency: {res.get('latency', 0):.2f}s | Status: {res['status']}")
        if res['status'] == 'success':
            print(f"  Response: {res['response'][:60]}...")

async def test_100_messages_memory_growth(client):
    print("\n=== TESTS 12, 13, 14: MEMORY GROWTH (100 MESSAGES) ===")
    db_size_before = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    print(f"DB Size Before: {db_size_before} bytes")
    
    # 10 batches of 10 concurrent requests
    for batch in range(10):
        print(f"Batch {batch+1}/10...")
        tasks = [send_chat(client, f"Message {batch*10 + i}. Remember that my favorite number is {batch*10 + i}.", f"growth-{batch}", "growth-user") for i in range(10)]
        results = await asyncio.gather(*tasks)
        successes = sum(1 for r in results if r['status'] == 'success')
        print(f"  Batch {batch+1} Success: {successes}/10")
        
    db_size_after = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    print(f"DB Size After: {db_size_after} bytes")
    print(f"Growth: {db_size_after - db_size_before} bytes")

async def main():
    async with httpx.AsyncClient() as client:
        await test_20_turn_conversation(client)
        await test_100_messages_memory_growth(client)

if __name__ == "__main__":
    asyncio.run(main())

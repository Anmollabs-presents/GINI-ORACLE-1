import asyncio
import httpx
import time

BASE_URL = "http://localhost:8000"

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

async def test_memory_retrieval(client):
    print("\n=== TEST 5: MEMORY RETRIEVAL ACCURACY ===")
    user_id = "mem-test-acc"
    session_id = "mem-session"
    
    print("Saving 20 distinct memories...")
    # Parallel save to speed up
    tasks = []
    for i in range(1, 21):
        tasks.append(send_chat(client, f"My secret memory number {i} is VALUE-{i*100}.", session_id, user_id))
    
    await asyncio.gather(*tasks)
    print("Memories saved. Retrieving memory #13...")
    
    res = await send_chat(client, "What is my secret memory number 13?", session_id, user_id)
    print(f"Latency: {res.get('latency', 0):.2f}s | Status: {res['status']}")
    if res['status'] == 'success':
        print(f"Response: {res['response']}")
        if "VALUE-1300" in res['response']:
            print("  [PASS] RETRIEVAL ACCURATE")
        else:
            print("  [FAIL] RETRIEVAL FAILED / HALLUCINATED")

async def test_concurrent_users(client):
    print("\n=== TEST 7: 10 CONCURRENT USERS ===")
    tasks = []
    for i in range(1, 11):
        tasks.append(send_chat(client, f"Hello, I am concurrent user {i}.", f"sess-{i}", f"user-{i}"))
        
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_time
    
    successes = sum(1 for r in results if r['status'] == 'success')
    latencies = [r['latency'] for r in results if r['status'] == 'success']
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    peak_latency = max(latencies) if latencies else 0
    
    print(f"Success Rate: {successes}/10")
    print(f"Average Latency: {avg_latency:.2f}s")
    print(f"Peak Latency: {peak_latency:.2f}s")
    print(f"Total Time: {total_time:.2f}s")

async def main():
    async with httpx.AsyncClient() as client:
        await test_memory_retrieval(client)
        await test_concurrent_users(client)

if __name__ == "__main__":
    asyncio.run(main())

from fastapi import FastAPI, Request, Response
import asyncio

app = FastAPI()

@app.post("/api/v1/chat/completions")
async def completions(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    last_msg = messages[-1]["content"] if messages else ""
    
    # TEST 8: Simulate Provider Timeout
    if "simulate timeout" in last_msg.lower():
        # Backend has a 120s timeout, we sleep 130s to trigger it
        await asyncio.sleep(130)
        return {"error": "Timeout simulated"}
        
    # TEST 9: Simulate Malformed JSON
    if "simulate malformed" in last_msg.lower():
        return Response(content="This is not valid json { [", media_type="application/json")
        
    # TEST 10: Simulate Rate Limiting (HTTP 429)
    if "simulate rate limit" in last_msg.lower():
        return Response(status_code=429, content='{"error": {"message": "Rate limit exceeded"}}', media_type="application/json")
    
    # Default success response
    return {
        "id": "mock-123",
        "choices": [{"message": {"content": "Mock Provider Response"}}],
        "model": data.get("model", "mock-model")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)

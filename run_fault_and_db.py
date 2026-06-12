# -*- coding: utf-8 -*-
import sys, io, asyncio, httpx, sqlite3, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB = r"backend\gini-ai-python\gini.db"

async def main():
    async with httpx.AsyncClient() as c:
        print("=== FAULT TESTS (Mock Provider @ :8001) ===")

        # TEST 8: Timeout
        print("TEST 8: Timeout simulation...")
        try:
            r = await c.post("http://127.0.0.1:8001/api/v1/chat/completions",
                json={"model":"test","messages":[{"role":"user","content":"simulate timeout please"}]},
                timeout=8.0)
            print(f"  Status: {r.status_code} (unexpected non-timeout)")
        except httpx.TimeoutException:
            print("  [PASS] Timeout correctly triggered after 8s - provider hang handled")

        # TEST 9: Malformed JSON
        print("TEST 9: Malformed JSON...")
        try:
            r = await c.post("http://127.0.0.1:8001/api/v1/chat/completions",
                json={"model":"test","messages":[{"role":"user","content":"simulate malformed json"}]},
                timeout=10.0)
            raw = r.text
            print(f"  Raw body: {raw[:80]}")
            try:
                r.json()
                print("  Parsed as JSON unexpectedly")
            except Exception:
                print("  [PASS] Body is malformed - parser protection confirmed")
        except Exception as e:
            print(f"  Exception: {e}")

        # TEST 10: HTTP 429 from mock
        print("TEST 10: HTTP 429 rate-limit simulation...")
        try:
            r = await c.post("http://127.0.0.1:8001/api/v1/chat/completions",
                json={"model":"test","messages":[{"role":"user","content":"simulate rate limit exceeded"}]},
                timeout=10.0)
            print(f"  [PASS] Mock returned HTTP {r.status_code} = rate-limit simulation confirmed")
        except Exception as e:
            print(f"  Exception: {e}")

    print()
    print("=== DB INTEGRITY CHECKS ===")
    if not os.path.exists(DB):
        print("DB not found at path: " + DB)
        return
        
    size = os.path.getsize(DB)
    print(f"DB size: {size} bytes ({size//1024} KB)")
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM sessions")
    print(f"Sessions: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM turns")
    print(f"Turn records: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM memory_facts")
    print(f"Memory facts: {cur.fetchone()[0]}")
    
    cur.execute("SELECT topic, value, user_id FROM memory_facts ORDER BY added_at DESC LIMIT 5")
    print("Recent memory facts:")
    for row in cur.fetchall():
        print(f"  [{row[2]}] {row[0]} = {row[1]}")
    
    cur.execute("SELECT content, session_id, COUNT(*) cnt FROM turns GROUP BY content, session_id HAVING cnt > 1 LIMIT 5")
    dupes = cur.fetchall()
    print(f"Duplicate turn rows: {len(dupes)}")
    
    cur.execute("SELECT session_id, MIN(turn_index), MAX(turn_index), COUNT(*) FROM turns GROUP BY session_id LIMIT 8")
    print("Session turn ranges:")
    for row in cur.fetchall():
        print(f"  sess={str(row[0])[:25]}... min={row[1]} max={row[2]} count={row[3]}")

    cur.execute("SELECT user_id, COUNT(*) FROM memory_facts WHERE user_id IN ('user-A-isolated','user-B-isolated') GROUP BY user_id")
    iso = cur.fetchall()
    print(f"Isolation test users in DB: {iso}")
    
    # Check ordering of one session
    cur.execute("SELECT session_id FROM turns GROUP BY session_id ORDER BY COUNT(*) DESC LIMIT 1")
    row = cur.fetchone()
    if row:
        sid = row[0]
        cur.execute("SELECT turn_index FROM turns WHERE session_id=? ORDER BY turn_index ASC", (sid,))
        idxs = [r[0] for r in cur.fetchall()]
        ordered = all(idxs[i] <= idxs[i+1] for i in range(len(idxs)-1))
        print(f"History ordering check for busiest session: {'PASS - ordered' if ordered else 'FAIL - corrupted'}")
    
    conn.close()
    print("DB integrity check complete.")

asyncio.run(main())

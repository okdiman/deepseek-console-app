import requests
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8000"

SCENARIO = [
    "I want to build a new mobile app called 'TaskMaster'.",
    "It needs to be built with React Native.",
    "The primary color should be Hex #FF5733.",
    "It must have offline support.",
    "Users need to be able to upload avatars.",
    "The backend will be Node.js.",
    "We need push notifications via Firebase.",
    "There should be a 'Dark Mode' toggle.",
    "Please add social login (Google and Apple).",
    "Tasks should have sub-tasks.",
    "We need a calendar view for deadlines.",
    "The app should support English and Spanish.",
    "Data must be encrypted at rest.",
    "We require an admin dashboard on the web.",
    "What is the name, primary color, frontend framework, and backend framework of the app we are building?"
]

def run_strategy_test(strategy_name: str, session_id: str):
    print(f"\n{'='*50}")
    print(f"Running Benchmark: {strategy_name.upper()}")
    print(f"{'='*50}")
    
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_time_ms = 0
    
    final_answer = ""
    
    for i, msg in enumerate(SCENARIO):
        print(f"[{i+1}/{len(SCENARIO)}] Sending: {msg[:40]}...")
        start_time = time.time()
        
        response = requests.get(
            f"{BASE_URL}/stream",
            params={
                "message": msg,
                "agent": "general",
                "strategy": strategy_name,
                "session_id": session_id
            },
            stream=True
        )
        
        full_reply = ""
        stats = {}
        
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data: "):
                    payload = json.loads(decoded_line[6:])
                    if "delta" in payload:
                        full_reply += payload["delta"]
                    if "stats" in payload:
                        stats = payload["stats"]
                        
        elapsed_ms = (time.time() - start_time) * 1000
        total_time_ms += elapsed_ms
        
        if stats:
            total_prompt_tokens += stats.get("prompt_tokens", 0)
            total_completion_tokens += stats.get("completion_tokens", 0)
            
        if i == len(SCENARIO) - 1:
            final_answer = full_reply

    print("\n--- RESULTS ---")
    print(f"Strategy: {strategy_name}")
    print(f"Total Time: {total_time_ms/1000:.2f} seconds")
    print(f"Total Prompt Tokens: {total_prompt_tokens}")
    print(f"Total Completion Tokens: {total_completion_tokens}")
    print(f"\nFinal Test Question Response:\n{final_answer.strip()}\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        strategies = [sys.argv[1]]
    else:
        strategies = ["default", "window", "facts", "branching"]
        
    for strat in strategies:
        run_strategy_test(strat, f"bench_{strat}_{int(time.time())}")

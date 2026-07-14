import sys
import logging
from src.llm_gateway import (
    get_llm_providers, call_gemini, call_claude, call_openai_compatible, clean_json_response
)

# Configure logging to only show critical errors to keep output clean
logging.basicConfig(level=logging.ERROR)

def check_single_provider(p) -> bool:
    provider = p["provider"]
    model = p["model"]
    key = p["key"]
    
    print(f"\nTesting provider: {provider.upper()} | Model: {model}...")
    prompt = "Respond with the word 'Success!' and nothing else. Do not add punctuation."
    
    try:
        if provider == "gemini":
            res = call_gemini(model, key, prompt)
            res = res.strip()
            print(f"  --> [OK] Response: {res}")
            return True
            
        elif provider == "claude":
            res = call_claude(model, key, prompt)
            res = res.strip()
            print(f"  --> [OK] Response: {res}")
            return True
            
        elif provider == "nvidia":
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            res = call_openai_compatible(url, model, key, prompt)
            res = res.strip()
            print(f"  --> [OK] Response: {res}")
            return True
            
        elif provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            res = call_openai_compatible(url, model, key, prompt)
            res = res.strip()
            print(f"  --> [OK] Response: {res}")
            return True
            
        else:
            print(f"  --> [FAILED] Unknown provider: {provider}")
            return False
            
    except Exception as e:
        print(f"  --> [FAILED] Error: {e}")
        return False

def main():
    print("="*60)
    print("      E-Commerce Pipeline API Connection Diagnostics")
    print("="*60)
    
    providers = get_llm_providers()
    if not providers:
        print("[ERROR] No LLM providers found. Please check llm_keys.txt or env vars.")
        sys.exit(1)
        
    print(f"Found {len(providers)} active configuration(s). Starting diagnostics...\n")
    
    success_count = 0
    for p in providers:
        if check_single_provider(p):
            success_count += 1
            
    print("\n" + "="*60)
    print(f"      Diagnostic Summary: {success_count}/{len(providers)} passed.")
    print("="*60)

if __name__ == "__main__":
    main()

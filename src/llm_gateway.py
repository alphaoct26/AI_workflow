import os
import logging
import httpx
import json
from pathlib import Path
from src.config import BASE_DIR, GEMINI_MODEL

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("LLM_Gateway")

def get_llm_providers() -> list:
    """
    Reads the list of LLM providers and credentials.
    Checks llm_keys.txt at the root of the workspace.
    Falls back to environment variables if the file does not exist.
    """
    providers = []
    
    # 1. Check llm_keys.txt
    keys_file = BASE_DIR / "llm_keys.txt"
    if keys_file.exists():
        try:
            with open(keys_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                        
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        provider = parts[0].lower()
                        model = parts[1]
                        key = parts[2]
                        # Strip accidental quotes
                        if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
                            key = key[1:-1].strip()
                            
                        providers.append({
                            "provider": provider,
                            "model": model,
                            "key": key
                        })
        except Exception as e:
            logger.warning(f"Error reading llm_keys.txt: {e}")
            
    # 2. Fallback to Environment Variables if no providers configured
    if not providers:
        # Check Gemini
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            providers.append({
                "provider": "gemini",
                "model": GEMINI_MODEL,
                "key": gemini_key
            })
            
        # Check Anthropic/Claude
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            providers.append({
                "provider": "claude",
                "model": "claude-3-5-sonnet-20241022",
                "key": anthropic_key
            })
            
        # Check NVIDIA NIM
        nvidia_key = os.environ.get("NVIDIA_API_KEY")
        if nvidia_key:
            providers.append({
                "provider": "nvidia",
                "model": "meta/llama-3.1-8b-instruct",
                "key": nvidia_key
            })
            
        # Check OpenAI
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            providers.append({
                "provider": "openai",
                "model": "gpt-4o-mini",
                "key": openai_key
            })
            
    return providers

def clean_json_response(raw_text: str) -> str:
    """Strips markdown code fences (like ```json ... ```) from a text response."""
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        # Split off first line
        lines = raw_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()
    return raw_text

def call_gemini(model: str, key: str, prompt: str, system_instruction: str = None, response_schema = None) -> str:
    """Executes a call to Google Gemini API using the google-genai SDK."""
    from google import genai
    from google.genai import types
    
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000))
    
    config_params = {}
    if system_instruction:
        config_params["system_instruction"] = system_instruction
    if response_schema:
        config_params["response_mime_type"] = "application/json"
        config_params["response_schema"] = response_schema
        config_params["temperature"] = 0.1
    else:
        config_params["temperature"] = 0.2
        
    config = types.GenerateContentConfig(**config_params)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config
    )
    return response.text

def call_claude(model: str, key: str, prompt: str, system_instruction: str = None) -> str:
    """Executes a direct HTTP call to Anthropic Claude messages API."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "model": model,
        "max_tokens": 1500,
        "messages": messages,
        "temperature": 0.2
    }
    if system_instruction:
        payload["system"] = system_instruction
        
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        res_data = response.json()
        return res_data["content"][0]["text"]

def call_openai_compatible(url: str, model: str, key: str, prompt: str, system_instruction: str = None, json_mode: bool = False) -> str:
    """Executes a call to any OpenAI-compatible completions endpoint (e.g. OpenAI, NVIDIA NIM)."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        res_data = response.json()
        return res_data["choices"][0]["message"]["content"]

def generate_llm_response(prompt: str, system_instruction: str = None, response_schema = None) -> str:
    """
    Main entry point for generating responses from the active LLM provider.
    Automatically rotates through the list of providers in get_llm_providers() if one fails.
    """
    providers = get_llm_providers()
    if not providers:
        raise ValueError("No LLM credentials found. Please define them in llm_keys.txt or set environment variables.")
        
    last_err = None
    for idx, p in enumerate(providers):
        provider = p["provider"]
        model = p["model"]
        key = p["key"]
        
        logger.info(f"Gateway: Attempting call using {provider.upper()} ({model}) [Key {idx+1}/{len(providers)}]...")
        
        try:
            if provider == "gemini":
                return call_gemini(model, key, prompt, system_instruction, response_schema)
                
            elif provider == "claude":
                # For non-gemini models, if a schema is requested, we instruct the model in the prompt
                modified_prompt = prompt
                if response_schema:
                    modified_prompt += "\n\nIMPORTANT: Return ONLY a raw JSON object matching the requested schema. No markdown code blocks."
                return clean_json_response(call_claude(model, key, modified_prompt, system_instruction))
                
            elif provider == "nvidia":
                url = "https://integrate.api.nvidia.com/v1/chat/completions"
                modified_prompt = prompt
                if response_schema:
                    modified_prompt += "\n\nIMPORTANT: Return ONLY a raw JSON object matching the requested schema. No markdown code blocks."
                return clean_json_response(call_openai_compatible(url, model, key, modified_prompt, system_instruction, json_mode=False))
                
            elif provider == "openai":
                url = "https://api.openai.com/v1/chat/completions"
                return clean_json_response(call_openai_compatible(url, model, key, prompt, system_instruction, json_mode=(response_schema is not None)))
                
            else:
                raise ValueError(f"Unknown provider '{provider}'")
                
        except Exception as e:
            last_err = e
            logger.warning(f"Gateway: {provider.upper()} call failed: {e}. Rotating to next provider...")
            
    raise last_err

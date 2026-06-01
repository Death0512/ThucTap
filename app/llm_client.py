import json
import time
import threading
import urllib.request
import os


_OPCODE_CONFIG_PATH = os.path.expanduser('~/.config/opencode/config.json')
_OPCODE_AUTH_PATH = os.path.expanduser('~/.local/share/opencode/auth.json')

NVIDIA_BASE_URL   = 'https://integrate.api.nvidia.com/v1'
NVIDIA_MODEL      = 'meta/llama-3.3-70b-instruct'
NVIDIA_VIS_MODEL  = 'meta/llama-3.2-11b-vision-instruct'


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


_config = _load_json(_OPCODE_CONFIG_PATH)
_auth   = _load_json(_OPCODE_AUTH_PATH)

# Read NVIDIA NIM credentials from OpenCode config / auth, with env var overrides
_nvidia_opts = _config.get('provider', {}).get('nvidia', {}).get('options', {})
_nvidia_key  = _auth.get('nvidia', {}).get('key', '')

LLM_BASE_URL   = os.environ.get('LLM_BASE_URL')   or _nvidia_opts.get('baseURL', NVIDIA_BASE_URL)
LLM_API_KEY    = os.environ.get('LLM_API_KEY')    or _nvidia_opts.get('apiKey', _nvidia_key)
LLM_MODEL      = os.environ.get('LLM_MODEL',      NVIDIA_MODEL)
LLM_VISION_MODEL = os.environ.get('LLM_VISION_MODEL', NVIDIA_VIS_MODEL)

LLM_URL = LLM_BASE_URL.rstrip('/') + '/chat/completions'


# ── Rate limiter: NVIDIA NIM free tier = 40 requests / minute ──────────────
# Token bucket — thread-safe, shared across all modules in the same process.
# Each call to _call_api() consumes one token and waits if the bucket is empty.

_RATE_LIMIT      = 40          # max requests per minute
_RATE_WINDOW     = 60.0        # seconds
_MIN_INTERVAL    = _RATE_WINDOW / _RATE_LIMIT   # 1.5 s between requests
_rate_lock       = threading.Lock()
_rate_timestamps: list[float] = []   # sliding window of recent call timestamps


def _rate_wait():
    """Block until we are within the 40 req/min limit, then record the slot."""
    while True:
        with _rate_lock:
            now = time.monotonic()
            # Drop timestamps older than the 60-second window
            cutoff = now - _RATE_WINDOW
            while _rate_timestamps and _rate_timestamps[0] < cutoff:
                _rate_timestamps.pop(0)

            # Calculate how long we need to wait (if at all)
            wait = 0.0

            if len(_rate_timestamps) >= _RATE_LIMIT:
                # Sliding window is full — wait until oldest slot falls out
                wait = max(wait, _RATE_WINDOW - (now - _rate_timestamps[0]))

            if _rate_timestamps:
                # Enforce minimum inter-request gap
                elapsed = now - _rate_timestamps[-1]
                wait = max(wait, _MIN_INTERVAL - elapsed)

            if wait <= 0:
                # We have a free slot — claim it and proceed
                _rate_timestamps.append(time.monotonic())
                return

        # Sleep outside the lock so other threads aren't blocked on the mutex
        print(f"    [rate-limit] waiting {wait:.1f}s")
        time.sleep(wait)



def set_model(model):
    global LLM_MODEL
    LLM_MODEL = model


def check_llm():
    try:
        req = urllib.request.Request(
            f'{LLM_BASE_URL.rstrip("/")}/models',
            headers={'Authorization': f'Bearer {LLM_API_KEY}'}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def _call_api(body_dict, timeout=120):
    _rate_wait()
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(
        LLM_URL,
        data=body,
        headers={
            'Authorization': f'Bearer {LLM_API_KEY}',
            'Content-Type': 'application/json'
        }
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"    LLM API error (nvidia): {e}")
        return None


def analyze(prompt, temperature=0.1, max_tokens=2000):
    body = {
        'model': LLM_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    return _call_api(body)


def analyze_with_image(image_b64, mime_type, prompt, temperature=0.1, max_tokens=2000):
    content = [
        {'type': 'text', 'text': prompt},
        {'type': 'image_url', 'image_url': {'url': f'data:{mime_type};base64,{image_b64}'}}
    ]
    body = {
        'model': LLM_VISION_MODEL,
        'messages': [{'role': 'user', 'content': content}],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    return _call_api(body)

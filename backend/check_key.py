import os
from pathlib import Path

# Load .env the same way your app likely does
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed, trying manual read of .env")

key = os.getenv("LICENSE_PUBLIC_KEY", "")

print("=" * 50)
print(f"repr(key): {repr(key)}")
print(f"len(key):  {len(key)}")
print("=" * 50)

if not key:
    print("❌ Key is empty or not found. Check that LICENSE_PUBLIC_KEY is set in .env")
elif key.startswith("-----BEGIN"):
    print("❌ This looks like a PEM-formatted key, not raw hex.")
    print("   You need to extract the raw 32-byte public key first.")
elif len(key) != 64:
    print(f"❌ Wrong length. Expected 64 hex characters (32 bytes), got {len(key)}.")
    if len(key) == 88 or key.endswith("="):
        print("   This might be base64-encoded instead of hex.")
else:
    try:
        raw = bytes.fromhex(key)
        print(f"✅ Valid hex, decodes to {len(raw)} bytes")
        if len(raw) == 32:
            print("✅ Correct length for an Ed25519 public key!")
            # Try actually constructing the key object
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            pub = Ed25519PublicKey.from_public_bytes(raw)
            print("✅ Successfully created Ed25519PublicKey object")
    except ValueError as e:
        print(f"❌ Failed to parse: {e}")
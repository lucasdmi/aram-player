"""Prints why ARAM Player can't reach the League client. Never prints the password."""
import platform, re, subprocess, sys
sys.path.insert(0, ".")
from aram_player import lcu

print("Python:", sys.version.split()[0], platform.system())
out = subprocess.run(["ps", "-Aww", "-o", "args"], capture_output=True, text=True).stdout
lines = [l for l in out.splitlines() if "LeagueClientUx" in l]
print("LeagueClientUx processes:", len(lines))
for l in lines:
    print("  has --app-port:", bool(re.search(r"--app-port=\d+", l)),
          "| has token:", bool(re.search(r"--remoting-auth-token=", l)),
          "| token chars:", sorted(set(re.sub(r"[\w-]", "", (re.search(r"--remoting-auth-token=(\S+)", l) or [None, ""])[1]))))
creds = lcu.find_credentials()
print("Credentials found:", bool(creds), "port:", creds[0] if creds else None)
if creds:
    c = lcu.LCU()
    c.connect()
    try:
        r = c.session.get(c.base + "/lol-gameflow/v1/gameflow-phase", timeout=3)
        print("HTTP", r.status_code, r.text[:200])
    except Exception as e:
        print("Request failed:", type(e).__name__, e)
import os
print("Proxy env:", {k: v for k, v in os.environ.items() if "proxy" in k.lower()})

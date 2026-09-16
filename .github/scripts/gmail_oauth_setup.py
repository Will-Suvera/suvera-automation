#!/usr/bin/env python3
"""One-time: let a teammate authorise draft-only access to their Gmail.

Step 1 (you):   python3 gmail_oauth_setup.py --account ellena --client-json <client_secret.json>
                prints a link. Send it to that person.
Step 2 (them):  open the link while signed in as themselves, approve, and copy the
                whole http://localhost/?code=... address from the browser bar
                (the page will not load - that is expected). Send it back.
Step 3 (you):   python3 gmail_oauth_setup.py --account ellena --client-json <file> \
                        --code "<that whole address or just the code>" --set-secret
                stores GMAIL_REFRESH_TOKEN_<ACCOUNT> in the suvera-automation repo.

Scope is gmail.compose: create drafts only. It cannot read or send mail.
"""
import json
import subprocess
import sys
import urllib.parse

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gmail_draft import SCOPE, TOKEN_URL, _post  # noqa: E402

REPO = "Will-Suvera/suvera-automation"
REDIRECT = "http://localhost"


def main(argv):
    arg = lambda f, d=None: argv[argv.index(f) + 1] if f in argv else d
    account = (arg("--account") or "").lower()
    path = arg("--client-json")
    if not (account and path):
        raise SystemExit("--account and --client-json are required")
    c = json.load(open(path))
    c = c.get("installed") or c.get("web")
    code = arg("--code")
    if not code:
        q = urllib.parse.urlencode({"client_id": c["client_id"], "redirect_uri": REDIRECT,
                                    "response_type": "code", "scope": SCOPE,
                                    "access_type": "offline", "prompt": "consent"})
        print(f"Send this to {account} (they must be signed in as themselves):\n")
        print("https://accounts.google.com/o/oauth2/v2/auth?" + q)
        print("\nThey approve, then copy the whole http://localhost/?code=... address back to you.")
        return
    if "code=" in code:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)["code"][0]
    tok = _post(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c["client_secret"],
                            "code": code, "grant_type": "authorization_code",
                            "redirect_uri": REDIRECT}, form=True)
    rt = tok.get("refresh_token")
    if not rt:
        raise SystemExit("no refresh_token returned (the code may be used or expired - mint a new link)")
    name = "GMAIL_REFRESH_TOKEN_" + account.upper()
    if "--set-secret" in argv:
        subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=rt, text=True, check=True)
        print(f"{name} stored in {REPO}. {account}'s follow-up drafts will now be made automatically.")
    else:
        print(f"{name}=<refresh token printed only with --set-secret omitted deliberately>")
        print(rt)


if __name__ == "__main__":
    main(sys.argv[1:])

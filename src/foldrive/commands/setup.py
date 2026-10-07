"""Install the Google OAuth client file so `foldrive login` can work.

The Google Cloud clicking can't be automated, but the step people actually give up
on can: "save this download into a hidden app folder whose path differs per OS".
`foldrive setup <file>` does that move for them and says whether it worked.
"""

import json
from pathlib import Path

from .. import auth, paths

INSTRUCTIONS = f"""foldrive needs a Google OAuth client file before you can log in.
This is a one-time setup, and it stays on your machine.

  1. Go to https://console.cloud.google.com and create a project (any name).
  2. APIs & Services -> Library -> search "Google Drive API" -> Enable.
  3. APIs & Services -> OAuth consent screen -> User type "External"
     -> fill in an app name and your email -> Save -> PUBLISH APP.
     Don't skip publishing: while it is in "Testing", Google expires your
     login every 7 days.
  4. APIs & Services -> Credentials -> Create credentials
     -> OAuth client ID -> Application type "Desktop app" -> Create
     -> Download JSON.
  5. Run this, with the path to the file you just downloaded:

         foldrive setup ~/Downloads/client_secret_xxxx.json

     Or skip the download and paste the Client ID and Client secret instead:

         foldrive setup --manual

It will be installed at:
     {auth.CLIENT_SECRET_PATH}

Then run: foldrive login
"""


def run(args):
    if args.manual:
        _check_not_installed(args)
        _install(_prompt_credentials())
        return

    if not args.path:
        print(INSTRUCTIONS)
        return

    source_path = Path(args.path).expanduser()
    if not source_path.exists():
        raise SystemExit(f"No such file: {source_path}")

    try:
        client_file = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as parse_error:
        raise SystemExit(
            f"{source_path} is not valid JSON ({parse_error}).\n"
            "Download the file again from Google Cloud Credentials."
        )
    except OSError as read_error:
        raise SystemExit(f"Could not read {source_path}: {read_error}")

    # Google writes the credentials under "installed" for Desktop apps and "web"
    # for Web applications. Picking the wrong application type is the single most
    # common setup mistake, and the resulting login error is unhelpful - so name it.
    if "web" in client_file and "installed" not in client_file:
        raise SystemExit(
            "This is a Web application client, which cannot sign in from a terminal.\n"
            "In Google Cloud Credentials, create a new OAuth client ID with\n"
            'Application type "Desktop app", then run foldrive setup again.'
        )

    credentials = client_file.get("installed")
    if not credentials or not credentials.get("client_id"):
        raise SystemExit(
            f"{source_path} doesn't look like an OAuth client file "
            "(no installed.client_id).\n"
            "Download it from Google Cloud -> Credentials -> your OAuth client -> "
            "Download JSON."
        )

    _check_not_installed(args)
    _install(client_file)


def _check_not_installed(args):
    if auth.CLIENT_SECRET_PATH.exists() and not args.force:
        raise SystemExit(
            f"{auth.CLIENT_SECRET_PATH} already exists.\n"
            "Re-run with --force to replace it (you will need to log in again)."
        )


def _prompt_credentials():
    """Build the same file Google's "Download JSON" gives, from two pasted values.

    Both are shown on the OAuth client's page in Google Cloud Credentials. For a
    Desktop app the secret is not confidential (Google says as much), so it is
    read with input() rather than getpass - a blind paste just confuses people.
    """
    print("Paste the values from Google Cloud -> Credentials -> your Desktop OAuth client.")
    try:
        client_id = input("Client ID: ").strip()
        client_secret = input("Client secret: ").strip()
    except EOFError:
        raise SystemExit("\nCancelled.")

    # The two fields sit next to each other and are easy to swap; the id always
    # has this suffix and the secret never does.
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise SystemExit(
            "That Client ID doesn't look right - it should end in "
            ".apps.googleusercontent.com."
        )
    if not client_secret:
        raise SystemExit("The Client secret is required.")

    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"],
        }
    }


def _install(client_file):
    paths.APP_DIR.mkdir(parents=True, exist_ok=True)
    auth.CLIENT_SECRET_PATH.write_text(json.dumps(client_file, indent=2), encoding="utf-8")

    print(f"Installed: {auth.CLIENT_SECRET_PATH}")
    print(f"Client id: {client_file['installed']['client_id']}")
    print("\nReady. Run: foldrive login")

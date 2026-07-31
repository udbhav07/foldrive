from .. import auth


def run(args):
    already = auth.get_credentials() is not None
    auth.login()
    if already:
        print("Already logged in.")
    else:
        print(f"Logged in. Token saved to {auth.TOKEN_PATH}")

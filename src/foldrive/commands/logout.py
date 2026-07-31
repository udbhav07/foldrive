from .. import auth


def run(args):
    if auth.logout():
        print("Logged out.")
    else:
        print("Not logged in.")

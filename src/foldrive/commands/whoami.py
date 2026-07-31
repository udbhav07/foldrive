from .. import auth


def run(args):
    service = auth.get_service()
    info = service.about().get(fields="user").execute()
    print(f"Logged in as {info['user']['emailAddress']}")

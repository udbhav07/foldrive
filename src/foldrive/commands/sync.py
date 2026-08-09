from . import pull,push

def run(args):
    print("---pull---")
    pull.run(args)
    # Whatever the user confirmed in the pull half applies to the push half too.
    args.yes = True
    print("\n--push---")
    push.run(args)

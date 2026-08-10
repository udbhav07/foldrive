from .. import autostart,logs

def run(args):
    if(args.remove):
        autostart.uninstall()
        print("Background Sync Disabled")
        return
    if args.status:
        print(autostart.status())
        return
    autostart.install()
    print(f"Background sync enabled - foldrive tick runs every {autostart.INTERVAL_MINUTES}")
    print(f"Log: {logs.LOG_PATH}")
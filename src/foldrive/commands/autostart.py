from .. import autostart,logs

def run(args):
    if(args.remove):
        autostart.uninstall()
        print("Background Sync Disabled")
        return
    if args.status:
        print(autostart.status())
        return
    runs_on_battery = autostart.install()
    print(f"Background sync enabled - foldrive tick runs every {autostart.INTERVAL_MINUTES} minutes")
    if not runs_on_battery:
        print("Note: could not allow syncing on battery power - Windows will only")
        print("      run the background sync while this machine is plugged in.")
    print(f"Log: {logs.LOG_PATH}")
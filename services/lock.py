import os


def acquire_single_instance_lock(config, support):
    if support.is_windows:
        mutex = support.win32event.CreateMutex(None, True, config.lock_name)
        if support.win32api.GetLastError() == support.winerror.ERROR_ALREADY_EXISTS:
            raise RuntimeError("Instance already running")
        return mutex

    if support.is_posix and support.fcntl:
        lock_fd = open(config.lock_file, "w")
        try:
            support.fcntl.lockf(lock_fd, support.fcntl.LOCK_EX | support.fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Instance already running")
        return lock_fd

    raise RuntimeError("Unsupported OS for lock")

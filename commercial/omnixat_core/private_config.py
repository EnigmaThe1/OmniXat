"""Bounded Linux service configuration reads from a validated open descriptor."""
import os
import stat


def private_file(path):
    # Validate what we actually read, rather than a pathname checked before open.
    # NONBLOCK prevents an untrusted FIFO replacement from hanging the worker.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077):
            raise ValueError('Private service-owned file required')
        with os.fdopen(descriptor, 'rb', closefd=False) as source:
            content = source.read(65537)
        if not content or len(content) > 65536:
            raise ValueError('Bounded configuration required')
        value = content.decode('utf-8').strip()
        if not value:
            raise ValueError('Nonempty configuration required')
        return value
    finally:
        os.close(descriptor)

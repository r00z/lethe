#!/bin/bash
set -e

# If HOST_UID is provided, create a user matching the host user
if [ -n "$HOST_UID" ]; then
    GID="${HOST_GID:-$HOST_UID}"

    # Allow UIDs below 1000 (e.g., for macOS users)
    sed -i 's/^UID_MIN.*/UID_MIN 100/' /etc/login.defs
    sed -i 's/^GID_MIN.*/GID_MIN 100/' /etc/login.defs

    # Create group if it doesn't exist
    if ! getent group "$GID" >/dev/null; then
        groupadd -g "$GID" hostuser
    fi

    # Create user if it doesn't exist
    if ! getent passwd "$HOST_UID" >/dev/null; then
        useradd -u "$HOST_UID" -g "$GID" -m -s /bin/bash hostuser
    fi

    # Give sudo access
    echo "hostuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

    # Change ownership of app directory
    chown -R "$HOST_UID:$GID" /app
    chmod -R u+w /app/.venv

    # Run as the host user
    exec gosu hostuser "$@"
else
    # No HOST_UID - run as root
    exec "$@"
fi
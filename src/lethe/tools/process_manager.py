"""Process manager for tracking background shell processes.

Supports two modes:
1. Regular mode: subprocess.Popen with stdout/stderr capture (line-based)
2. PTY mode: pty.fork with pyte terminal emulation (for TUI apps)
"""

import os
import pty
import select
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pyte


@dataclass
class BackgroundProcess:
    """Tracks a background shell process."""
    process: Optional[subprocess.Popen]  # For regular mode
    command: str
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    status: str = "running"  # running, completed, failed
    exit_code: Optional[int] = None
    start_time: Optional[datetime] = None
    
    # PTY mode fields
    is_pty: bool = False
    pty_fd: Optional[int] = None  # Master PTY file descriptor
    pty_pid: Optional[int] = None  # Child PID
    screen: Optional[pyte.Screen] = None  # Terminal emulator screen
    stream: Optional[pyte.Stream] = None  # Connects pty output to screen
    raw_output: list[bytes] = field(default_factory=list)  # Raw PTY output buffer
    
    def get_screen_text(self) -> str:
        """Get the current terminal screen as text."""
        if not self.screen:
            return ""
        
        lines = []
        for y in range(self.screen.lines):
            line = ""
            for x in range(self.screen.columns):
                char = self.screen.buffer[y][x]
                line += char.data if char.data else " "
            lines.append(line.rstrip())
        
        # Remove trailing empty lines
        while lines and not lines[-1]:
            lines.pop()
        
        return "\n".join(lines)
    
    def get_cursor_position(self) -> tuple[int, int]:
        """Get the current cursor position (row, col)."""
        if not self.screen:
            return (0, 0)
        return (self.screen.cursor.y, self.screen.cursor.x)
    
    def resize(self, rows: int, cols: int):
        """Resize the terminal (for PTY mode)."""
        if self.screen:
            self.screen.resize(rows, cols)
        
        if self.pty_fd:
            import fcntl
            import struct
            import termios
            # Set terminal size
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.pty_fd, termios.TIOCSWINSZ, winsize)
    
    def write_input(self, data: str):
        """Write input to the PTY (for PTY mode)."""
        if self.pty_fd and self.status == "running":
            os.write(self.pty_fd, data.encode())


# Global registry of background processes
background_processes: dict[str, BackgroundProcess] = {}

# Counter for generating unique bash IDs
_bash_id_counter = 0


def get_next_bash_id() -> str:
    """Get the next unique bash ID."""
    global _bash_id_counter
    _bash_id_counter += 1
    return f"bash_{_bash_id_counter}"


def get_process(shell_id: str) -> Optional[BackgroundProcess]:
    """Get a background process by ID."""
    return background_processes.get(shell_id)


def register_process(shell_id: str, proc: BackgroundProcess):
    """Register a new background process."""
    background_processes[shell_id] = proc


def remove_process(shell_id: str) -> bool:
    """Remove a background process from tracking."""
    if shell_id in background_processes:
        proc = background_processes[shell_id]
        # Clean up PTY resources
        if proc.pty_fd:
            try:
                os.close(proc.pty_fd)
            except OSError:
                pass
        del background_processes[shell_id]
        return True
    return False


def list_processes() -> dict[str, BackgroundProcess]:
    """List all tracked background processes."""
    return background_processes.copy()


def create_pty_process(
    command: str,
    cwd: str,
    env: dict,
    rows: int = 24,
    cols: int = 80,
) -> tuple[str, BackgroundProcess]:
    """Create a process running in a PTY with terminal emulation.
    
    Args:
        command: Shell command to run
        cwd: Working directory
        env: Environment variables
        rows: Terminal rows (default 24)
        cols: Terminal columns (default 80)
    
    Returns:
        Tuple of (shell_id, BackgroundProcess)
    """
    bash_id = get_next_bash_id()
    
    # Create pyte screen and stream
    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    
    # Fork with PTY
    pid, fd = pty.fork()
    
    if pid == 0:
        # Child process
        os.chdir(cwd)
        for key, value in env.items():
            os.environ[key] = value
        os.environ["TERM"] = "xterm-256color"
        os.execvp("/bin/bash", ["/bin/bash", "-c", command])
    else:
        # Parent process
        import fcntl
        import struct
        import termios
        
        # Set terminal size
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
        
        # Set non-blocking
        import fcntl
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        bg_proc = BackgroundProcess(
            process=None,
            command=command,
            start_time=datetime.now(),
            is_pty=True,
            pty_fd=fd,
            pty_pid=pid,
            screen=screen,
            stream=stream,
        )
        register_process(bash_id, bg_proc)
        
        # Start reader thread
        def read_pty():
            """Read from PTY and feed to terminal emulator."""
            while bg_proc.status == "running":
                try:
                    # Check if there's data to read
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if r:
                        try:
                            data = os.read(fd, 4096)
                            if data:
                                bg_proc.raw_output.append(data)
                                # Feed to terminal emulator
                                stream.feed(data.decode("utf-8", errors="replace"))
                            else:
                                # EOF - process exited
                                break
                        except OSError:
                            break
                except (ValueError, OSError):
                    break
            
            # Process finished - get exit status
            try:
                _, status = os.waitpid(pid, os.WNOHANG)
                if os.WIFEXITED(status):
                    bg_proc.exit_code = os.WEXITSTATUS(status)
                    bg_proc.status = "completed" if bg_proc.exit_code == 0 else "failed"
                else:
                    bg_proc.status = "failed"
            except ChildProcessError:
                bg_proc.status = "completed"
        
        reader_thread = threading.Thread(target=read_pty, daemon=True)
        reader_thread.start()
        
        return bash_id, bg_proc

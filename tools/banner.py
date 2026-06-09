#!/usr/bin/env python3
"""
MASTER Welcome Banner — ANSI art with the MASTER logo and a ninja.

Colors: M=Red, A=White, S=Red, T=White, E=White, R=Red
"""
import sys

RED = "\033[31m\033[1m"
WHITE = "\033[37m\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m\033[1m"
RST = "\033[0m"


def color_letter(ch):
    if ch in ("M", "S", "R"):
        return f"{RED}{ch}{RST}"
    return f"{WHITE}{ch}{RST}"


def show_banner():
    """Display the MASTER welcome banner with ninja art."""
    # Build MASTER title in color
    title = " ".join(color_letter(c) for c in "MASTER")
    print()
    print(f"  {CYAN}══════════════════════════════════════════{RST}")
    print(f"  {title}")
    print(f"  {DIM}ABACO Team  ·  v1.0  ·  multi-agent orchestration{RST}")
    print(f"  {CYAN}══════════════════════════════════════════{RST}")
    print()
    print(f"  {DIM}🥷  The orchestra is tuning...{RST}")
    print()


def show_small_banner():
    """Compact banner for inline use."""
    title = "".join(color_letter(c) for c in "MASTER")
    print(f"{CYAN}╔══════════════════════════════════╗{RST}")
    print(f"{CYAN}║        {title}              ║{RST}")
    print(f"{CYAN}║   {DIM}ABACO Team  ·  v1.0        {CYAN}║{RST}")
    print(f"{CYAN}╚══════════════════════════════════╝{RST}")


if __name__ == "__main__":
    if "--small" in sys.argv:
        show_small_banner()
    else:
        show_banner()

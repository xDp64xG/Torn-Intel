"""
utils/colors.py

Color utilities for terminal output.
Provides ANSI color codes and formatting functions for readable CLI reports.
"""


class Colors:
    """ANSI color codes for terminal output."""
    
    # Text colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    # Formatting
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    REVERSE = '\033[7m'
    HIDDEN = '\033[8m'
    STRIKETHROUGH = '\033[9m'
    
    # Reset
    RESET = '\033[0m'


def color_text(text, color):
    """Wrap text with a color code."""
    return f"{color}{text}{Colors.RESET}"


def bold(text):
    """Make text bold."""
    return f"{Colors.BOLD}{text}{Colors.RESET}"


def dim(text):
    """Make text dim."""
    return f"{Colors.DIM}{text}{Colors.RESET}"


def success(text):
    """Format text as success (green)."""
    return color_text(text, Colors.GREEN)


def error(text):
    """Format text as error (red)."""
    return color_text(text, Colors.RED)


def warning(text):
    """Format text as warning (yellow)."""
    return color_text(text, Colors.YELLOW)


def info(text):
    """Format text as info (blue)."""
    return color_text(text, Colors.BLUE)


def highlight(text):
    """Highlight text (cyan)."""
    return color_text(text, Colors.CYAN)


def muted(text):
    """Make text muted (bright black)."""
    return color_text(text, Colors.BRIGHT_BLACK)


def money(amount):
    """Format monetary amount (green)."""
    return color_text(f"${amount:,.2f}", Colors.GREEN)


def percentage(value, threshold_low=50, threshold_high=80):
    """
    Format percentage with color based on value.
    Green: >= threshold_high
    Yellow: >= threshold_low
    Red: < threshold_low
    """
    if value >= threshold_high:
        return color_text(f"{value:.1f}%", Colors.GREEN)
    elif value >= threshold_low:
        return color_text(f"{value:.1f}%", Colors.YELLOW)
    else:
        return color_text(f"{value:.1f}%", Colors.RED)


def rank(rank_num, total):
    """
    Format rank with color.
    Gold (bright yellow) for 1st, Silver (bright white) for 2nd, Bronze (dim) for 3rd
    """
    if rank_num == 1:
        return color_text(f"#{rank_num}", Colors.BRIGHT_YELLOW)
    elif rank_num == 2:
        return color_text(f"#{rank_num}", Colors.BRIGHT_WHITE)
    elif rank_num == 3:
        return color_text(f"#{rank_num}", Colors.DIM)
    else:
        return f"#{rank_num}"


def number_color(value, low_threshold=100, high_threshold=500):
    """
    Format number with color based on magnitude.
    Green for high, yellow for medium, red for low.
    """
    if value >= high_threshold:
        return color_text(f"{value:.2f}", Colors.GREEN)
    elif value >= low_threshold:
        return color_text(f"{value:.2f}", Colors.YELLOW)
    else:
        return color_text(f"{value:.2f}", Colors.RED)


def header(text):
    """Format text as a header (bold cyan)."""
    return f"{Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}"


def subheader(text):
    """Format text as a subheader (cyan)."""
    return color_text(text, Colors.CYAN)


def divider(width=140, char='='):
    """Create a colored divider line."""
    return color_text(char * width, Colors.BRIGHT_BLACK)


def box_header(title, width=140):
    """Create a formatted box header."""
    box = divider(width)
    title_line = color_text(f"  {title}", Colors.BOLD + Colors.CYAN)
    return f"{box}\n{title_line}\n{box}"

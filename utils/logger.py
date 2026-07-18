from datetime import datetime


class Logger:

    def _log(self, level: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def info(self, message: str):
        self._log("INFO", message)

    def warning(self, message: str):
        self._log("WARN", message)

    def error(self, message: str):
        self._log("ERROR", message)

    def success(self, message: str):
        self._log("SUCCESS", message)
"""Count prose including headings/link labels; exclude fences, URL targets and count line."""
import re
from pathlib import Path
path = Path(__file__).resolve().parent.parent / "README.md"
source = path.read_text(encoding="utf-8")
prose = re.sub(r"```.*?```", "", source, flags=re.S)
prose = re.sub(r"^README prose word count:.*$", "", prose, flags=re.M)
prose = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", prose)
prose = re.sub(r"<https?://[^>]+>", "", prose)
count = len(re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", prose))
path.write_text(re.sub(r"^README prose word count:.*$", f"README prose word count: {count} (excluding setup commands and URL targets).", source, flags=re.M), encoding="utf-8")
print(count)

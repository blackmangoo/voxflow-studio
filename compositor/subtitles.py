import json
import sys
from pathlib import Path
from typing import List, Dict, Any

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import SUBTITLE_CONFIG, TEMP_DIR

def ms_to_ass_time(ms: int) -> str:
    """Converts milliseconds to ASS timestamp format: H:MM:SS.cc (centiseconds)"""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    centiseconds = (ms % 1000) // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

class SubtitleGenerator:
    """
    Generates stylized karaoke / word-highlight subtitles in ASS format.
    Groups spoken words into 2-4 word readable chunks with neon active-word glow.
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.cfg = config or SUBTITLE_CONFIG

    def generate_ass(self, words: List[Dict[str, Any]], output_path: Path = None) -> Path:
        if output_path is None:
            output_path = TEMP_DIR / "subtitles.ass"

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{self.cfg['font_name']},{self.cfg['font_size'] * 4},{self.cfg['primary_color']},{self.cfg['secondary_color']},{self.cfg['outline_color']},{self.cfg['outline_color']},-1,0,0,0,100,100,2,0,1,{self.cfg['outline_width'] * 2},{self.cfg['shadow_depth'] * 2},{self.cfg['alignment']},50,50,{self.cfg['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        # Chunk words into groups of 3 (or by sentence pauses)
        CHUNK_SIZE = 3
        chunks = []
        for i in range(0, len(words), CHUNK_SIZE):
            chunk = words[i:i + CHUNK_SIZE]
            chunks.append(chunk)

        events = []
        for chunk in chunks:
            chunk_start_ms = chunk[0]["start_ms"]
            chunk_end_ms = chunk[-1]["end_ms"]

            # Highlight each word sequentially during its active speech window
            for idx, active_word in enumerate(chunk):
                w_start = ms_to_ass_time(active_word["start_ms"])
                w_end = ms_to_ass_time(active_word["end_ms"])

                # Build the chunk text with active word styled in neon yellow
                text_parts = []
                for other_idx, other_word in enumerate(chunk):
                    w_text = other_word["word"].upper()
                    if other_idx == idx:
                        # Neon yellow highlight with slight scale boost
                        text_parts.append(f"{{\\c{self.cfg['highlight_color']}\\fscx108\\fscy108}}{w_text}{{\\r}}")
                    else:
                        text_parts.append(w_text)

                line_text = " ".join(text_parts)
                events.append(
                    f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{line_text}"
                )

        content = header + "\n".join(events) + "\n"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path


if __name__ == "__main__":
    with open(TEMP_DIR / "test_voice_timestamps.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    gen = SubtitleGenerator()
    out = gen.generate_ass(data["words"])
    print(f"ASS subtitle generated: {out}")

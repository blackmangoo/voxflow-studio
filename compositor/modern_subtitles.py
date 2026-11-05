import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import TEMP_DIR, CHANNEL_SUBTITLE_CONFIGS, SUBTITLE_CONFIG_DEFAULT


def ms_to_ass_time(ms: int) -> str:
    """Converts milliseconds to ASS timestamp: H:MM:SS.cc"""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    centiseconds = (ms % 1000) // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


class ModernSubtitleGenerator:
    """
    Generates per-channel branded ASS subtitle files.
    - 2-word karaoke-style pop, one word highlighted per tick
    - Hook text burns in for the first 3 seconds at the top
    - Font/colour/outline are per-channel (body_simulator ≠ code_classroom)
    """

    def generate_ass(
        self,
        words: List[Dict[str, Any]],
        lang: str = "english",
        output_path: Optional[Path] = None,
        hook_text: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> Path:
        if output_path is None:
            output_path = TEMP_DIR / f"{lang}_subtitles.ass"

        cfg = CHANNEL_SUBTITLE_CONFIGS.get(channel or "", SUBTITLE_CONFIG_DEFAULT)

        # Urdu needs a Unicode-capable font; override font for Urdu regardless of channel
        if lang == "urdu":
            font = "Segoe UI"
            font_size = max(cfg["size"] - 4, 64)
        else:
            font = cfg["font"]
            font_size = cfg["size"]

        primary   = cfg["primary"]
        highlight = cfg["highlight"]
        outline   = cfg["outline"]
        outline_w = cfg["outline_w"]
        shadow    = cfg["shadow"]

        # Hook style is always bold + bigger than body, centred high in frame
        hook_size = font_size + 20

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "PlayResX: 1080\n"
            "PlayResY: 1920\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: ReelStyle,{font},{font_size},"
            f"{primary},{highlight},{outline},&H00000000,"
            f"-1,0,0,0,100,100,2,0,1,{outline_w:.1f},{shadow:.1f},2,60,60,240,1\n"
            f"Style: HookStyle,{font},{hook_size},"
            f"{highlight},{primary},{outline},&H80000000,"
            f"-1,0,0,0,100,100,2,0,3,{outline_w + 2:.1f},{shadow + 2:.1f},8,60,60,400,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        events = []

        # Hook text — top 3 seconds, full-screen banner
        if hook_text:
            end_time = ms_to_ass_time(3000)
            clean_hook = hook_text.replace("\n", "\\N")
            events.append(
                f"Dialogue: 1,0:00:00.00,{end_time},HookStyle,,0,0,0,,{{\\fad(200,200)}} {clean_hook} "
            )

        # 2-word karaoke pop: each word is highlighted in sequence
        CHUNK_SIZE = 2
        for i in range(0, len(words), CHUNK_SIZE):
            chunk = words[i : i + CHUNK_SIZE]
            if not chunk:
                continue
            for idx, active_word in enumerate(chunk):
                w_start = ms_to_ass_time(active_word["start_ms"])
                w_end   = ms_to_ass_time(active_word["end_ms"])
                parts = []
                for o_idx, o_word in enumerate(chunk):
                    w_text = o_word["word"].upper() if lang == "english" else o_word["word"]
                    if o_idx == idx:
                        parts.append(
                            f"{{\\c{highlight}\\fscx112\\fscy112}}{w_text}{{\\r}}"
                        )
                    else:
                        parts.append(f"{{\\c{primary}}}{w_text}{{\\r}}")
                line_text = " ".join(parts)
                events.append(
                    f"Dialogue: 0,{w_start},{w_end},ReelStyle,,0,0,0,,{line_text}"
                )

        content = header + "\n".join(events) + "\n"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path


if __name__ == "__main__":
    gen = ModernSubtitleGenerator()
    dummy = [{"word": "Test", "start_ms": 0, "end_ms": 500}]
    for ch in ["body_simulator", "xray_mechanics", "crazy_characters", "health_coach", "garage_guru", "code_classroom"]:
        p = gen.generate_ass(dummy, channel=ch, output_path=Path(f"/tmp/sub_{ch}.ass"))
        print(f"{ch}: {p}")

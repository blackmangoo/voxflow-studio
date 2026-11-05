import json
import os
import sys
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import GLOBAL_STYLE_DNA, TEMP_DIR

class Scene(BaseModel):
    scene_num: int = Field(description="Sequential scene number starting at 1")
    audio_script: str = Field(description="Exact spoken sentence for this scene beat")
    flow_prompt: str = Field(description="Detailed visual prompt engineered for Google Flow/Veo with camera motion and bright lighting")

class VideoScript(BaseModel):
    title: str = Field(description="High-CTR controversial video title")
    topic: str = Field(description="Core subject")
    viral_hook_type: str = Field(description="Hook methodology used, e.g., 'Pattern Interrupt', 'Unspoken Truth'")
    full_audio_script: str = Field(description="Complete continuous spoken narration (100-140 words, 30-40s)")
    scenes: List[Scene] = Field(description="5 to 7 visual scene beats mapped to the narration")
    hashtags: List[str] = Field(description="High-reach hashtags for TikTok/Shorts/Reels")
    caption: str = Field(description="Engaging caption asking a debate question")


SYSTEM_PROMPT = f"""You are an elite short-form video director specializing in hyper-viral, high-retention controversial vertical videos (YouTube Shorts, TikTok, Instagram Reels).

YOUR RULES:
1. THE HOOK (0-3s): The first sentence must be a startling pattern interrupt or counter-intuitive claim that shatters common assumptions. Never start with "Did you know" or "Today we will explore".
2. THE TENSION (3-25s): Present 2-3 rapid, compelling arguments or historical/psychological twists. Maintain curiosity gap throughout.
3. THE COMMENT TRAP (Final 5s): Conclude with a polarizing binary question that forces viewers into the comments to debate.
4. WORD COUNT: Total spoken words MUST be between 100 and 135 words (approx 30 to 40 seconds spoken at natural pace).
5. VEO / FLOW PROMPTS — MANDATORY STRUCTURE for every scene:
   a. OPEN with a named shot type + camera movement on the very first line, e.g.:
      "Extreme close-up Dutch angle — ", "Low-angle tracking shot — ", "Slow orbital push-in — ",
      "Rapid zoom-out from macro — ", "Handheld shaky push-in — ", "Bird's-eye pull-back — ".
   b. Describe the PRIMARY ACTION: what is physically happening in the frame (not just what exists there).
   c. Include one PARTICLE or LIGHT FX: sparks flying, steam erupting, glowing pulses spreading, sweat arcing.
   d. Every scene prompt MUST end with this exact aesthetic style: "{GLOBAL_STYLE_DNA}".
   e. Do NOT include text, logos, or chaotic multi-character scenes. Focus on bold, iconic imagery.
"""

class ScriptWriter:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def generate_script(self, topic: str) -> VideoScript:
        """
        Generates a structured controversial video script and Flow prompts using Gemini 2.5.
        """
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found! Please set the GEMINI_API_KEY environment variable "
                "or pass your Google AI Studio API key."
            )

        from google import genai
        from google.genai import types

        import concurrent.futures

        def _call_gemini():
            client = genai.Client(api_key=self.api_key)
            prompt = f"Create a viral, controversial vertical video script about this topic: '{topic}'"
            response = client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=VideoScript,
                    temperature=0.85,
                ),
            )
            data = json.loads(response.text)
            script = VideoScript(**data)
            script_file = TEMP_DIR / "last_script.json"
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(script.model_dump_json(indent=2))
            return script

        # Run with strict 5-second timeout to avoid tenacity retry hangs
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call_gemini)
            try:
                return future.result(timeout=6)
            except concurrent.futures.TimeoutError:
                raise TimeoutError("Gemini API took longer than 6 seconds (high demand spike).")
            except Exception as e:
                raise e


if __name__ == "__main__":
    print("ScriptWriter ready. Pass GEMINI_API_KEY to test.")

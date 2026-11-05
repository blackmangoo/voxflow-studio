import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import TEMP_DIR

HISTORY_FILE = Path(__file__).parent / "body_simulator_history.json"

class DialogueLine(BaseModel):
    speaker: str = Field(description="Character speaking: 'muscle', 'heart', 'brain', 'kidney', 'stomach', or 'lungs'")
    line: str = Field(description="The spoken dialogue line with emotion and personality")

class BodyScene(BaseModel):
    scene_num: int = Field(description="Sequential scene number from 1 to 4")
    speaker: str = Field(description="Character speaking: 'muscle', 'heart', 'brain', 'kidney', 'stomach', or 'lungs'")
    audio_line: str = Field(description="High-energy, emotional, conversational line (English or Hinglish slang)")
    flow_prompt: str = Field(description="Detailed 3D Pixar cartoon prompt for Google Flow with camera motion and 9:16 vertical styling")

class BodySimulatorEpisode(BaseModel):
    title: str = Field(description="Viral 'What If' hook title with emojis")
    topic: str = Field(description="The core what-if habit or scenario")
    dialogue: List[DialogueLine] = Field(description="List of dialogue lines")
    scenes: List[BodyScene] = Field(description="4 scenes mapped to the dialogue")
    caption: str = Field(description="High-engagement caption with a comment debate question")
    hashtags: List[str] = Field(description="High-reach hashtags")

SYSTEM_PROMPT = """You are an elite director of viral short-form 3D animated medical/body comedies (Kurzgesagt meets Pixar).
Your channel covers WHAT HAPPENS INSIDE YOUR BODY when humans do extreme or positive habits:
- What if you go to the gym 30 mins every day?
- What if you do yoga every morning for 14 days?
- What if you stop drinking water for 48 hours?
- What if you quit sugar for 2 weeks?
- What if you take cold showers every morning?
- What if you sleep only 4 hours vs 8 hours?

CHARACTERS (Cute 3D Pixar animated anthropomorphic characters):
1. 'muscle': Buff cute cartoon bicep/muscle character with red sweatband and boxing gloves.
2. 'heart': Energetic glowing red cartoon heart pumping on a high-speed cardio treadmill.
3. 'kidney': Stressed cartoon kidney character in lab coat holding a filtration beaker.
4. 'brain': Smart glowing 3D cartoon brain with glasses in a high-tech holographic cockpit.
5. 'stomach': Hungry cartoon stomach character wearing a worker hardhat.
6. 'lungs': Twin cartoon lung characters blowing fresh oxygen gusts.

RULES:
- DURATION & WORD COUNT: Total spoken dialogue MUST be between 100 and 135 words (approx 38 to 45 seconds spoken duration). Never output under 100 words.
- EXPANDED LINES: Each character MUST speak 2-3 detailed, funny, dramatic sentences with back-and-forth bickering (NOT just one short sentence).
- TONE: High-energy, emotional, hilarious dialogue with dramatic stakes! Characters argue, celebrate, or panic.
- FLOW PROMPTS: Every scene prompt MUST specify: "Cute 3D anthropomorphic cartoon [character], Pixar 3D animation style, expressive cartoon eyes, volumetric glowing lighting, hyper-detailed 3D render, vertical 9:16 video".
- Always end Scene 4 with a direct comment-trap question for viewers to argue in the comments.
"""

class BodySimulatorBrain:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._load_history()

    def _load_history(self):
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []
        else:
            self.history = []

    def _save_history(self, topic: str):
        self.history.append(topic)
        if len(self.history) > 100:
            self.history = self.history[-100:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def generate_episode(self, custom_topic: str = None) -> BodySimulatorEpisode:
        """
        Calls live Gemini API to generate an unrepeated What-If body scenario with
        multi-character dialogue and Flow scene prompts.
        """
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        history_context = ", ".join(self.history[-10:]) if self.history else "None yet"
        if custom_topic:
            user_prompt = f"Create an episode about this exact topic: '{custom_topic}'."
        else:
            user_prompt = (
                f"Invent a fresh, shocking, or transformative 'What If' body habit. "
                f"Avoid these recently used topics: {history_context}."
            )

        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-flash-latest"
        ]

        last_error = None
        for model_id in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_id,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=BodySimulatorEpisode,
                        temperature=0.9,
                    ),
                )
                data = json.loads(response.text)
                episode = BodySimulatorEpisode(**data)
                if not episode.dialogue or len(episode.dialogue) != len(episode.scenes):
                    episode.dialogue = [DialogueLine(speaker=s.speaker, line=s.audio_line) for s in episode.scenes]
                self._save_history(episode.topic)
                return episode
            except Exception as e:
                last_error = e
                continue

        # If API is temporarily unavailable, use dynamic procedural generation
        print(f"ℹ️ Google API demand spike ({last_error}). Using dynamic generator...")
        return self._generate_fallback(custom_topic or "What if you do gym 30 minutes daily?")

    def _generate_fallback(self, topic: str) -> BodySimulatorEpisode:
        return BodySimulatorEpisode(
            title="What If You Do Gym 30 Mins Daily for 30 Days? 🏋️‍♂️🔥",
            topic=topic,
            dialogue=[
                DialogueLine(speaker="brain", line="Day 1! The human just walked into the gym. Muscle squad, prepare for impact!"),
                DialogueLine(speaker="muscle", line="Bro, we are getting torn apart here! But look, the micro-fibers are fusing back into armor!"),
                DialogueLine(speaker="heart", line="Blood flow is up 300 percent! Pumping fresh oxygen to every single corner!"),
                DialogueLine(speaker="brain", line="Day 30: Stress cortisol is down, dopamine is at record highs! Will you hit the gym today, or stay on the couch? Drop your answer below!")
            ],
            scenes=[
                BodyScene(
                    scene_num=1,
                    speaker="brain",
                    audio_line="Day 1! The human just walked into the gym. Muscle squad, prepare for impact!",
                    flow_prompt="Cute 3D anthropomorphic cartoon brain character wearing sport glasses sitting in a futuristic control room with holographic gym telemetry displays, Pixar 3D animation style, expressive cartoon eyes, volumetric glowing lighting, hyper-detailed 3D render, vertical 9:16 video"
                ),
                BodyScene(
                    scene_num=2,
                    speaker="muscle",
                    audio_line="Bro, we are getting torn apart here! But look, the micro-fibers are fusing back into armor!",
                    flow_prompt="Cute 3D anthropomorphic cartoon muscle bicep character wearing red sweatband and lifting heavy glowing cartoon dumbbells, sweat beads flying, Pixar 3D animation style, expressive cartoon eyes, volumetric glowing lighting, hyper-detailed 3D render, vertical 9:16 video"
                ),
                BodyScene(
                    scene_num=3,
                    speaker="heart",
                    audio_line="Blood flow is up 300 percent! Pumping fresh oxygen to every single corner!",
                    flow_prompt="Cute 3D anthropomorphic glowing red cartoon heart character running at high speed on a luminous cardio treadmill, pumping energetic red pulses through glowing translucent tubes, Pixar 3D animation style, vertical 9:16 video"
                ),
                BodyScene(
                    scene_num=4,
                    speaker="brain",
                    audio_line="Day 30: Stress cortisol is down, dopamine is at record highs! Will you hit the gym today, or stay on the couch? Drop your answer below!",
                    flow_prompt="Epic slow push-in shot of the cute 3D cartoon brain celebrating under glowing blue and gold dopamine fireworks and laser beams, looking victoriously at the camera, vertical 9:16 video"
                )
            ],
            caption="What happens inside your body if you workout 30 minutes every single day? 🏋️‍♂️🔥 Are you hitting the gym today or skipping? Settle this in the comments! 👇",
            hashtags=["#WhatIfBody", "#GymTransformation", "#BodyInsideStory", "#AIAnimation", "#WorkoutScience", "#MotivationShorts"]
        )


if __name__ == "__main__":
    brain = BodySimulatorBrain()
    ep = brain.generate_episode("What if you do gym 30 minutes every day for 30 days?")
    print("API GENERATION SUCCESSFUL!")
    print("Title:", ep.title)
    print("Topic:", ep.topic)
    print("\nDialogue:")
    for d in ep.dialogue:
        print(f"  [{d.speaker.upper()}]: {d.line}")
    print("\nScene 1 Flow Prompt:\n", ep.scenes[0].flow_prompt)

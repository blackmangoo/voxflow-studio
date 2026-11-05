import json
import random
import sys
from pathlib import Path
from typing import List, Dict, Any
from pydantic import BaseModel

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HISTORY_FILE = Path(__file__).parent / "organ_comedy_history.json"

# Locked visual DNA for consistent 3D cartoon characters across scenes
CHARACTER_VISUALS = {
    "stomach": (
        "cute 3D anthropomorphic cartoon stomach character wearing a yellow construction hardhat, "
        "big expressive glossy cartoon eyes, inside a steamy biological pipeline control room with glowing pressure gauges, "
        "Pixar 3D animation style, cinematic 9:16 vertical composition, vivid vibrant lighting, 8k render"
    ),
    "pancreas": (
        "cute 3D anthropomorphic cartoon pancreas character with round glasses and a stressed expression, "
        "holding a tiny clipboard in a futuristic glowing sugar-sorting warehouse, "
        "Pixar 3D animation style, cinematic 9:16 vertical composition, electric neon cyan and violet highlights, 8k render"
    ),
    "brain": (
        "hyper-detailed glowing 3D cartoon brain character sitting in an executive swivel chair, "
        "surrounded by floating holographic food delivery menus and pulsating blue dopamine sparks, "
        "Pixar 3D animation style, cinematic 9:16 vertical composition, high-contrast neon glow, 8k render"
    )
}

# Dialogue-driven viral scenarios inspired by the top Instagram reels
DIALOGUE_SCENARIOS = [
    {
        "food": "Midnight Extra-Spicy Biryani",
        "title": "When You Order Biryani at 2 AM 😂🍛🚨",
        "dialogue": [
            {"speaker": "stomach", "line": "Arre Maalik! Raat ke do baje biryani kaun mangwata hai?!"},
            {"speaker": "brain", "line": "Bhai bas do bite khayenge, chill kar na!"},
            {"speaker": "stomach", "line": "Chill kar?! Do plate double-masala aa chuka hai! Poora system blast hone wala hai!"},
            {"speaker": "stomach", "line": "Subah bathroom mein mujhe mat bolna. Tumhari galti thi!"}
        ],
        "scene_prompts": [
            f"Close-up low angle shot of {CHARACTER_VISUALS['stomach']}. The character suddenly wakes up with wide shocked eyes as a red emergency alarm siren flashes overhead, steam venting from brass pipes in background, 9:16 vertical",
            f"Medium shot of {CHARACTER_VISUALS['brain']}, relaxing in chair holding a phone with food delivery app on screen, laughing dismissively, blue dopamine sparks floating around, vertical 9:16",
            "Dynamic action shot inside glowing pipeline, massive cartoon avalanche of steaming spicy orange biryani rice and fiery red chili peppers exploding through pressure valves, cartoon smoke, 9:16 vertical",
            f"Dramatic push-in shot of {CHARACTER_VISUALS['stomach']}. Character pointing an accusatory finger forward with a deadpan angry glare, warning the viewer, dark moody background with neon rim light, 9:16 vertical"
        ],
        "caption": "Maalik ne Swiggy khola aur Stomach Kumar ki night shift lag gayi 😂🍛 Who else commits this crime at 2 AM? Tell us in the comments! 👇",
        "hashtags": ["#AIComedy", "#BodyInsideStory", "#StomachKumar", "#BiryaniComedy", "#FunnyReels", "#RelatableHumor"]
    },
    {
        "food": "Five Warm Gulab Jamuns at Wedding Buffet",
        "title": "When You Eat 5 Gulab Jamuns on a Diet 😂🍮🚨",
        "dialogue": [
            {"speaker": "pancreas", "line": "Sir ji, hum diet par the na? Yeh paanch gulab jamun kahan se aa gaye?!"},
            {"speaker": "brain", "line": "Shadi ka khana hai bhai! Free ka item kaise chhod dein?"},
            {"speaker": "pancreas", "line": "Free ke chakkar mein mera insulin factory crash ho gaya hai!"},
            {"speaker": "pancreas", "line": "Ab sari raat extra shift karo! Tumhari diet ka kalyan ho gaya!"}
        ],
        "scene_prompts": [
            f"Close-up shot of {CHARACTER_VISUALS['pancreas']}, waking up in shock, eyes wide behind round glasses, glowing warning sirens flashing, 9:16 vertical",
            f"Medium shot of {CHARACTER_VISUALS['brain']}, holding a glowing fork with a hot gulab jamun, smiling proudly, dopamine particles swirling, vertical 9:16",
            "Dynamic high-angle shot inside glowing pipeline, golden syrup rivers and giant cartoon sugar crystals flooding through pipes, alarm lights flashing, vertical 9:16",
            f"Comedic action shot of {CHARACTER_VISUALS['pancreas']}, frantically typing on a glowing emergency console with sweat flying, screaming in panic, 9:16 vertical"
        ],
        "caption": "Shadi ke buffet ne Pancreas Babu ka poora schedule bigad diya 😂🍮 Share this with your friend who breaks diet at every wedding! 👇",
        "hashtags": ["#AIComedy", "#PancreasBabu", "#GulabJamun", "#DietFails", "#FunnyReels", "#FoodHumor"]
    },
    {
        "food": "Fourth Cup of Strong Kadak Chai on Empty Stomach",
        "title": "Chai on an Empty Stomach Be Like 😂☕🚨",
        "dialogue": [
            {"speaker": "stomach", "line": "Subah se paani nahi diya, aur seedha ubalti hui kadak chai daal di?!"},
            {"speaker": "brain", "line": "Bhai neend nahi khul rahi thi, thoda caffeine toh banta hai!"},
            {"speaker": "stomach", "line": "Caffeine nahi, yeh direct acid attack hai! Meri deewarein jal rahi hain!"},
            {"speaker": "stomach", "line": "Ek biscuit toh de dete zalimo! Ab jhelo acidity ka keher!"}
        ],
        "scene_prompts": [
            f"Close-up low angle shot of {CHARACTER_VISUALS['stomach']}, staring up at ceiling in horror as boiling dark tea drops splash around, steam hissing, 9:16 vertical",
            f"Medium shot of {CHARACTER_VISUALS['brain']}, half-asleep sipping an espresso cup with droopy eyelids, blue electric arcs sputtering, vertical 9:16",
            "Action shot inside metal biological pipe, bubbling caustic amber liquid boiling and dissolving cartoon metal pipes with smoke rising, vertical 9:16",
            f"Dramatic push-in on {CHARACTER_VISUALS['stomach']}, holding a tiny umbrella against sizzling hot tea drops, shouting angrily at the screen, 9:16 vertical"
        ],
        "caption": "Empty stomach par 4th cup chai ka nateeja… Stomach Kumar is in critical condition 😂☕ How many cups do you drink every day? 👇",
        "hashtags": ["#ChaiLovers", "#StomachKumar", "#AIComedy", "#AcidityProblems", "#FunnyReels", "#DesiHumor"]
    }
]

class DialogueEpisode(BaseModel):
    title: str
    food: str
    dialogue: List[Dict[str, str]]
    scene_prompts: List[str]
    caption: str
    hashtags: List[str]

class OrganComedyBrain:
    def __init__(self):
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

    def _save_history(self, food: str):
        self.history.append(food)
        if len(self.history) > 50:
            self.history = self.history[-50:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def generate_autonomous_episode(self) -> DialogueEpisode:
        available = [s for s in DIALOGUE_SCENARIOS if s["food"] not in self.history]
        if not available:
            self.history.clear()
            available = DIALOGUE_SCENARIOS

        chosen = random.choice(available)
        self._save_history(chosen["food"])

        return DialogueEpisode(
            title=chosen["title"],
            food=chosen["food"],
            dialogue=chosen["dialogue"],
            scene_prompts=chosen["scene_prompts"],
            caption=chosen["caption"],
            hashtags=chosen["hashtags"]
        )


if __name__ == "__main__":
    brain = OrganComedyBrain()
    ep = brain.generate_autonomous_episode()
    print("Episode:", ep.title)
    for d in ep.dialogue:
        print(f"  [{d['speaker'].upper()}]: {d['line']}")

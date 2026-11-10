import json
import os
import random
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HISTORY_FILE = Path(__file__).parent / "autonomous_channel_history.json"

class LocalizedDialogue(BaseModel):
    speaker: str = Field(description="Character name or role")
    voice_persona: str = Field(description="Persona key e.g. 'stomach', 'narrator', 'mechanic', 'doctor', 'cpp_professor'")
    line: str = Field(description="Spoken dialogue line")

class SceneVisual(BaseModel):
    scene_num: int = Field(description="1 to 4")
    flow_prompt: str = Field(description="High-precision Google Flow Veo prompt (9:16 vertical, 10s clip)")

class DualLanguageEpisode(BaseModel):
    channel: str = Field(description="Channel identifier")
    concept: str = Field(description="Core hook concept")
    title_urdu: str = Field(description="High-CTR viral title in Urdu")
    title_english: str = Field(description="High-CTR viral title in English")
    hook_text_urdu: str = Field(description="3-second bold on-screen hook (Urdu)")
    hook_text_english: str = Field(description="3-second bold on-screen hook (English)")
    dialogue_urdu: List[LocalizedDialogue] = Field(description="4-part spoken dialogue in Urdu")
    dialogue_english: List[LocalizedDialogue] = Field(description="4-part spoken dialogue in English")
    scenes: List[SceneVisual] = Field(description="4 scene visual prompts for Google Flow")
    caption_urdu: str = Field(description="Urdu social media caption with comment-bait question")
    caption_english: str = Field(description="English social media caption with comment-bait question")
    hashtags: List[str] = Field(description="Hashtags for social media")


# =========================================================================
# FLOW PROMPT ENGINEERING DNA (injected into every scene prompt)
# =========================================================================
FLOW_DNA = {
    # Shot + motion vocabulary is injected here so EVERY prompt — fallback or Gemini-generated — inherits it.
    # The individual prompt must open with the specific shot/angle; FLOW_DNA closes with render quality.
    "body_simulator": (
        "Pixar 3D animated style, photorealistic cartoon render, expressive cartoon character with big eyes, "
        "exaggerated squash-and-stretch physicality, volumetric glowing interior biology lighting, "
        "hyper-saturated electric cyan and amber colors, cartoon sweat and particle FX, "
        "cinematic depth of field, ultra-detailed 8k, 9:16 vertical short film"
    ),
    "xray_mechanics": (
        "ultra-detailed photorealistic 3D X-ray transparent cutaway engineering render, glowing thermal stress "
        "heatmap overlay, internal metal components and fluid channels visible, cinematic dark background "
        "with neon diagnostic grid overlays, slow dramatic camera reveal, 8k resolution, 9:16 vertical"
    ),
    "crazy_characters": (
        "cute 3D anthropomorphic cartoon character, Pixar animation style, big expressive cartoon eyes, "
        "exaggerated facial expressions and body language, rich warm comedic lighting with volumetric rays, "
        "cartoon motion blur and impact FX, 8k photorealistic cartoon render, 9:16 vertical short"
    ),
    "health_coach": (
        "photorealistic 3D medical animation, glowing human anatomy cross-section, clean clinical environment "
        "with vivid accent lighting, particle effects showing cellular or molecular activity, "
        "hyper-detailed 8k motivational render, 9:16 vertical"
    ),
    "garage_guru": (
        "photorealistic 3D automotive engineering render, cinematic garage workshop with dramatic key lighting "
        "and deep shadow pools, ultra-detailed gritty mechanical components and authentic grease textures, "
        "sparks or fluid spray particle FX, 8k resolution, 9:16 vertical"
    ),
    "code_classroom": (
        "vibrant 3D animated tech classroom or terminal environment, holographic code projections and glowing "
        "neon syntax highlights in electric blue and purple, energetic character expressions, "
        "cinematic bokeh and dynamic depth of field, ultra-detailed 8k render, 9:16 vertical"
    ),
}


# =========================================================================
# GEMINI SYSTEM PROMPTS PER CHANNEL
# =========================================================================
CHANNEL_PROMPTS = {
    "body_simulator": f"""You are an elite short-form showrunner for a 3D animated medical/body comedy channel (Pixar meets Kurzgesagt).
Focus: What happens INSIDE the human body when humans do positive/extreme/terrible habits:
- Gym 30 mins, yoga 14 days, no water 48 hours, energy drinks at night, cold plunge, zero sugar, no sleep, extreme spicy food, protein overload, fasting 24 hours.
CHARACTERS:
- 'stomach' (Stomach Kumar): overworked factory supervisor in yellow hardhat. Fleshy moist mucosal textures.
- 'brain': CEO in high-tech cockpit with glowing neural synapses.
- 'pancreas': stressed logistics clerk with round glasses and clipboard.
- 'heart': hyper-athletic runner on glowing cardio treadmill.
- 'kidney': stressed lab chemist in tiny white lab coat.
- 'muscle': buff cartoon bicep character with boxing wraps.
FLOW VISUAL STYLE: "{FLOW_DNA['body_simulator']}"
Exactly 4 scenes and 4 dialogue lines. Total spoken dialogue 90-120 words.
Always end with a polarizing comment-trap question about personal habits.
""",

    "xray_mechanics": f"""You are an elite engineering science communicator (Engineering Explained meets X-Ray Gyan).
Focus: 3D X-ray cutaway reveals showing why mechanical things catastrophically fail or how they work at the molecular level:
- Coolant vs tap water, turbocharger oil starvation, brake fade on mountains, timing belt snap, cheap spark plugs, diesel injector clog, suspension geometry failure, overheating head gasket, cheap battery sulfation.
CHARACTERS:
- 'narrator': Serious authoritative dramatic documentary expert voice.
FLOW VISUAL STYLE: "{FLOW_DNA['xray_mechanics']}"
Exactly 4 scenes and 4 narrator monologue lines. Total dialogue 90-120 words.
End with a question asking viewers about their vehicle or personal experience.
""",

    "crazy_characters": f"""You are an elite showrunner for a viral desi animated comedy channel (Crazy Veggies meets Diamond AI).
Focus: Anthropomorphic vegetables or food items with hilarious human drama, hustle stories, and authentic desi emotional comedy.
Scenarios: Dubai return stories, chai-dhabba drama, arranged marriage fails, gym motivation, student struggles, cricket match fights.
CHARACTERS:
- 'aalu': cute 3D potato in tweed blazer — the underdog hero.
- 'tamatar': chubby red tomato chef/shopkeeper with apron.
- 'pyaaz': dramatic onion friend with emotional layers.
- 'mirchi': fiery green chili — aggressive gym trainer/hothead.
- 'chai': warm steaming desi tea in cutting glass — the gossip auntie.
FLOW VISUAL STYLE: "{FLOW_DNA['crazy_characters']}"
Exactly 4 scenes and 4 dialogue lines. Total dialogue 90-120 words.
Urdu dialogue must use authentic desi street slang. End with a comment trap question.
""",

    "health_coach": f"""You are a world-class health and nutrition science communicator for a viral Shorts channel.
Focus: Evidence-based, myth-busting health and fitness content that genuinely helps viewers:
- How to reduce obesity and visceral fat, intermittent fasting science, sugar vs artificial sweeteners, why walking 10k steps works, protein timing myths, inflammation foods, gut microbiome, sleep and fat storage, hydration and metabolism, stress eating psychology.
CHARACTERS:
- 'doctor': Warm authoritative medical expert, trustworthy and evidence-based.
- 'narrator': Energetic motivational science narrator.
FLOW VISUAL STYLE: "{FLOW_DNA['health_coach']}"
Exactly 4 scenes and 4 dialogue lines. Total dialogue 90-120 words.
Every episode must deliver ONE concrete actionable tip the viewer can use today.
End with a question about the viewer's personal health journey.
""",

    "garage_guru": f"""You are a master automotive expert and passionate gearhead content creator for all vehicle enthusiasts.
Focus: Real-world vehicle maintenance, diagnostics, mods, and survival tips covering ALL vehicles — motorcycles, cars, SUVs, Jeeps, off-road 4x4s, diesel trucks:
- Why radiators fail, how to read tire wear patterns, jeep differential locking explained, bike chain vs belt drive, when to replace brake pads, off-road recovery techniques, why your 4x4 pulls to one side, turbo diesel vs petrol, reading your dashboard warning lights correctly.
CHARACTERS:
- 'mechanic': Experienced gritty master mechanic — grisly, no-nonsense, deeply knowledgeable.
- 'narrator': Cinematic automotive documentary narrator.
FLOW VISUAL STYLE: "{FLOW_DNA['garage_guru']}"
Exactly 4 scenes and 4 dialogue lines. Total dialogue 90-120 words.
End with a question engaging the viewer about their own vehicle or experience.
""",

    "code_classroom": f"""You are a brilliant CS professor and tech content creator producing viral programming education Shorts.
Focus: Programming fundamentals, career advice, and honest takes on tech/AI for beginner-to-intermediate students (BS CS/AI students, career switchers, self-taught devs):
- C++ vs Python vs Java: which to learn first, pointer arithmetic explained simply, why recursion breaks students, object-oriented programming analogies, how AI is disrupting CS jobs, why copy-pasting from Stack Overflow is destroying junior devs, the real purpose of data structures, how GitHub saved my career, is a CS degree still worth it in 2025, LLMs are making students intellectually lazy.
CHARACTERS:
- 'cpp_professor': Enthusiastic but brutally honest CS professor character — sarcastic, witty, challenging.
- 'student': Relatable confused BS student asking dumb-but-real questions.
- 'narrator': Authoritative tech industry voice with real industry data.
FLOW VISUAL STYLE: "{FLOW_DNA['code_classroom']}"
Exactly 4 scenes and 4 dialogue lines. Total dialogue 90-120 words.
End with a polarizing question about learning, AI, or the tech career that triggers debate in comments.
"""
}


# =========================================================================
# FALLBACK OFFLINE CONTENT BANK
# =========================================================================
FALLBACK_BANK = {
    "body_simulator": [
        {
            "concept": "What If You Do Gym 30 Mins Daily for 30 Days?",
            "title_urdu": "روزانہ 30 منٹ جم کرنے سے جسم میں کیا ہوتا ہے؟ 🏋️‍♂️🔥",
            "title_english": "What If You Gym 30 Mins Daily for 30 Days? 🏋️‍♂️🔥",
            "hook_text_urdu": "جسم بدل جاتا ہے!",
            "hook_text_english": "Your body TRANSFORMS!",
            "dialogue_urdu": [
                ("brain", "brain", "Day 1! Maalik gym pahonch gaya hai! Muscle squad, heavy impact ke liye ready ho jao!"),
                ("muscle", "stomach", "Bhai hamare micro-fibers toot rahe hain! Lekin dekho, repair cells unhe bulletproof armor bana rahe hain!"),
                ("heart", "stomach", "Blood flow teen sau percent upar chala gaya! Har kone mein fresh oxygen supply shuru!"),
                ("brain", "brain", "Day 30: Stress cortisol khatam, dopamine record high! Aaj gym jaoge ya sofa par pade rahoge?")
            ],
            "dialogue_english": [
                ("brain", "brain", "Day 1! The human just stepped into the gym. Muscle squad, prepare for heavy impact!"),
                ("muscle", "stomach", "Our micro-fibers are literally snapping! But the repair cells are fusing them back into armor!"),
                ("heart", "stomach", "Blood flow surging 300 percent! Pumping fresh oxygen into every depleted corner!"),
                ("brain", "brain", "Day 30: Stress cortisol wiped out, dopamine at record highs! Will you hit the gym today, or stay on the couch?")
            ],
            "prompts": [
                f"Low-angle Dutch-tilt tracking shot — chubby 3D cartoon brain character in sports glasses slamming holographic HUD buttons, neon telemetry data exploding outward, sweat particles flying, {FLOW_DNA['body_simulator']}",
                f"Extreme close-up rapid zoom-out — cute 3D cartoon bicep character slamming glowing golden dumbbells onto the rack, golden repair sparks arcing from snapping muscle fibers, {FLOW_DNA['body_simulator']}",
                f"Orbital sweep inside a glowing red heart racing on a neon cardio treadmill, crimson blood pulses rushing through transparent glass pipe walls with motion blur, {FLOW_DNA['body_simulator']}",
                f"Slow cinematic push-in on 3D cartoon brain throwing arms up in victory under a shower of golden dopamine confetti, electric cyan celebration pulses radiating outward, {FLOW_DNA['body_simulator']}"
            ],
            "caption_urdu": "Rozana 30 minute gym karne se jism kaise badalta hai? 🏋️‍♂️🔥 Team Gym ya Team Sofa? Comment mein batao! 👇",
            "caption_english": "What really happens inside your body when you gym 30 minutes every day? 🏋️‍♂️🔥 Team Gym or Team Couch? Settle this below! 👇",
            "hashtags": ["#BodyInsideStory", "#GymScience", "#WhatIfBody", "#AIAnimation", "#WorkoutMotivation", "#ViralShorts"]
        },
        {
            "concept": "What If You Don't Drink Water For 48 Hours?",
            "title_urdu": "48 گھنٹے پانی نہ پینے سے کیا ہوتا ہے؟ 💧💀",
            "title_english": "What If You Don't Drink Water For 48 Hours? 💧💀",
            "hook_text_urdu": "جسم کا پانی ختم!",
            "hook_text_english": "Your organs are DYING!",
            "dialogue_urdu": [
                ("kidney", "kidney", "Emergency alert! Do din se pipeline mein ek qatra paani nahi aaya! Main sukha registan ban chuka hoon!"),
                ("brain", "brain", "Red Alert! Aankhon aur thook se aakhri boond nichod lo, core functions ko bachana hai!"),
                ("heart", "stomach", "Mera blood pressure gir raha hai! Aisa lag raha hai jaise veins mein gaadha engine oil pump kar raha hoon!"),
                ("kidney", "kidney", "Non-essential systems band ho rahe hain! Bata sako: kya tum bina paani ke ek din guzaar sakte ho?")
            ],
            "dialogue_english": [
                ("kidney", "kidney", "Emergency! Zero water for two full days! I am literally turning into desert sand!"),
                ("brain", "brain", "Code Red! Squeezing every drop from the salivary glands and eyes to keep core functions alive!"),
                ("heart", "stomach", "Blood volume collapsing! Feels like pumping thick sticky engine oil through these veins!"),
                ("kidney", "kidney", "Shutting down non-essential sectors! Drop a comment: could you survive 24 hours without water?")
            ],
            "prompts": [
                f"Extreme close-up Dutch angle — 3D cartoon kidney character clutching an empty cracked flask, desert sand materializing beneath its feet, red warning sirens strobing behind it, {FLOW_DNA['body_simulator']}",
                f"Handheld shaky push-in on 3D cartoon brain frantically pulling glowing red emergency levers, alarm warning lights cascading in a glass cockpit, sparks flying from overloaded circuits, {FLOW_DNA['body_simulator']}",
                f"Low-angle tracking shot inside a biological vessel where thick dark-red fluid sluggishly clogs through narrowing transparent glass pipes, thermal heatmap overlay glowing amber to red, {FLOW_DNA['body_simulator']}",
                f"Slow zoom-out on 3D cartoon kidney in a tiny desert hat waving a white surrender flag directly at camera, cartoon dust puffs drifting around it, {FLOW_DNA['body_simulator']}"
            ],
            "caption_urdu": "Paani na peene se aapke organs ka bura haal ho jata hai! 💧😱 Aaj kitne glass piya? Comment mein batao! 👇",
            "caption_english": "Your organs enter full survival mode without water! 💧😱 How many glasses did you drink today? Drop it below! 👇",
            "hashtags": ["#Hydration", "#BodyComedy", "#KidneyHealth", "#WaterScience", "#PixarStyle", "#ViralShorts"]
        }
    ],

    "xray_mechanics": [
        {
            "concept": "What Tap Water Does to Your Radiator",
            "title_urdu": "ریڈیٹر میں نل کا پانی ڈالنے سے انجن کیسے تباہ ہوتا ہے؟ 🚗🔥",
            "title_english": "Why Tap Water in Your Radiator Destroys Your Engine 🚗🔥",
            "hook_text_urdu": "انجن پگھل رہا ہے!",
            "hook_text_english": "Your engine is MELTING!",
            "dialogue_urdu": [
                ("narrator", "narrator", "Coolant sirf temperature control nahi karta — yeh anti-corrosion aur anti-freeze shield bhi hai."),
                ("narrator", "narrator", "Nay ke paani mein calcium aur mineral deposits hote hain jo garam hone par radiator tubes mein jamm jaate hain."),
                ("narrator", "narrator", "Yeh blockages coolant flow rok dete hain aur engine 120 degree se upar overheating karna shuru ho jata hai."),
                ("narrator", "narrator", "Head gasket phatt jaata hai aur engine ka kaam khatam! Apni gadi mein kya use karte ho? Comment mein batao!")
            ],
            "dialogue_english": [
                ("narrator", "narrator", "Coolant is not just temperature control — it is your engine's anti-corrosion and anti-freeze shield."),
                ("narrator", "narrator", "Tap water contains calcium and mineral deposits that bake into solid scale inside the radiator channels under heat."),
                ("narrator", "narrator", "This mineral crust blocks coolant circulation, driving engine temperatures above 120 degrees Celsius."),
                ("narrator", "narrator", "The head gasket blows and the engine seizes permanently. What are you running in your radiator right now?")
            ],
            "prompts": [
                f"Slow orbital push-in into a glowing radiator core cross-section — calcium mineral scale visibly choking the micro-channels, thermal heatmap shifting orange to red, steam wisps rising, {FLOW_DNA['xray_mechanics']}",
                f"Extreme macro zoom-in — transparent 3D view of white mineral crystals aggressively accumulating inside aluminium radiator fins, time-lapse crystallization with red warning grid overlay, {FLOW_DNA['xray_mechanics']}",
                f"Low-angle crane shot pulling back from a 3D overheating engine block glowing orange-red, a head gasket rupturing with a violent steam jet erupting upward into the frame, {FLOW_DNA['xray_mechanics']}",
                f"Bird's-eye pull-back revealing an exploded 3D engineering diagram — clean coolant system in glowing green on the left, mineral-choked blocked system in amber-red on the right, {FLOW_DNA['xray_mechanics']}"
            ],
            "caption_urdu": "Coolant vs paani: ek engine bachata hai aur doosra lakho ka nuksan karta hai 🚗💥 Aapke radiator mein kya hai? 👇",
            "caption_english": "Water vs coolant: one protects your engine, the other destroys it in weeks 🚗💥 What are you running? Comment below! 👇",
            "hashtags": ["#CarMaintenance", "#EngineFail", "#RadiatorTips", "#MechanicalEngineering", "#3DAnimation", "#Gearheads"]
        },
        {
            "concept": "Why Cheap Engine Oil Kills Your Turbocharger",
            "title_urdu": "سستا انجن آئل آپ کے ٹربو کو کیسے جلا دیتا ہے؟ 🏎️🔥",
            "title_english": "How Cheap Engine Oil Destroys Your Turbocharger 🏎️🔥",
            "hook_text_urdu": "ٹربو جل گیا!",
            "hook_text_english": "Turbo DESTROYED!",
            "dialogue_urdu": [
                ("narrator", "narrator", "Turbocharger ek lakh pachas hazar RPM par ghoomta hai aur temperature aath sau degree tak jata hai."),
                ("narrator", "narrator", "Sasta oil is extreme heat par jal kar thick black sludge ban jata hai jo turbo oil passages block kar deta hai."),
                ("narrator", "narrator", "Bina lubrication ke floating bearings dry metal-to-metal friction se pighal jaate hain."),
                ("narrator", "narrator", "Turbine blades toot kar engine cylinders mein ghus jaate hain! Aakhri baar oil kab change karwaya tha?")
            ],
            "dialogue_english": [
                ("narrator", "narrator", "A turbocharger spins at 150,000 RPM, reaching glowing exhaust temperatures above 800 degrees Celsius."),
                ("narrator", "narrator", "Cheap degraded oil bakes instantly at these temperatures, becoming thick carbon sludge suffocating the turbo feed lines."),
                ("narrator", "narrator", "Deprived of oil film, floating journal bearings undergo catastrophic dry friction, welding shaft to housing in seconds."),
                ("narrator", "narrator", "Shattered compressor wheel fragments get sucked into combustion chambers destroying the entire engine. When was your last oil change?")
            ],
            "prompts": [
                f"Extreme close-up slow push-in — transparent 3D twin-scroll turbocharger spinning at motion-blur speed, exhaust housing glowing cherry-red, heat shimmer distortion rippling off the turbine housing, {FLOW_DNA['xray_mechanics']}",
                f"Orbital macro shot around turbo journal bearings — golden synthetic oil transforming into charred black carbon sludge in micro feed channels, viscous sludge slowly choking the path, {FLOW_DNA['xray_mechanics']}",
                f"Low-angle tracking shot inside a turbo housing — shaft wobbling violently from bearing failure, orange-white friction sparks spraying in arcs against the dark housing walls, {FLOW_DNA['xray_mechanics']}",
                f"Rapid zoom-out from a cracked compressor wheel exploding outward — metal shrapnel fragments flying down the intake manifold in slow motion, red engineering warning grid pulsing around the damage, {FLOW_DNA['xray_mechanics']}"
            ],
            "caption_urdu": "Sasta oil aapki car ke turbo ka sabse bada dushman hai! 🏎️🔥 Full synthetic use karte ho ya mineral? 👇",
            "caption_english": "Cheap oil causes catastrophic turbo failure! 🏎️🔥 Full synthetic or regular oil? Drop your answer below! 👇",
            "hashtags": ["#Turbocharger", "#EngineFailure", "#OilChange", "#CarMaintenance", "#MechanicalSecrets", "#ViralShorts"]
        }
    ],

    "crazy_characters": [
        {
            "concept": "Aalu Returns to Village After 5 Years",
            "title_urdu": "5 سال بعد آلو لوٹا اپنے گاؤں 😭❤️ | ایموشنل کہانی",
            "title_english": "Potato Returns to Village After 5 Years 😭❤️ | Emotional AI Story",
            "hook_text_urdu": "آلو واپس آ گیا!",
            "hook_text_english": "Aalu is BACK!",
            "dialogue_urdu": [
                ("aalu", "aalu", "Panch saal pehle gaon chhod kar shehar gaya tha… log bolte the aalu ka koi future nahi hai!"),
                ("aalu", "aalu", "Din raat mehnat ki, French Fries banne se bacha, aur aaj apni luxury car se gaon laut raha hoon!"),
                ("tamatar", "tamatar", "Arey beta Aalu! Hum sochte the tu kisi samosa mein dab gaya hoga!"),
                ("aalu", "aalu", "Mehnat ho toh Aalu bhi sona ban sakta hai! Kya aap apne sapno ke liye ghar chhod sakte hain?")
            ],
            "dialogue_english": [
                ("aalu", "aalu", "Five years ago I left this village for the city. Everyone said a potato has zero future!"),
                ("aalu", "aalu", "I grinded day and night, escaped the french fry fryer, and today I return in my own luxury ride!"),
                ("tamatar", "tamatar", "Son Potato! We honestly thought you got squashed inside a roadside samosa!"),
                ("aalu", "aalu", "With honest hustle, even a potato can shine like gold! Would you leave home to chase your dream?")
            ],
            "prompts": [
                f"Wide cinematic push-in down a dusty village road at golden hour — gleaming black luxury car emerging from heat shimmer, mud-brick houses flanking the road, golden dust particles floating, {FLOW_DNA['crazy_characters']}",
                f"Low-angle hero tracking shot — cute 3D cartoon potato in tiny tweed blazer and mirrored sunglasses stepping out of the car, cartoon emotional tears glistening in golden light, {FLOW_DNA['crazy_characters']}",
                f"Warm handheld-style shot — wrinkled elderly 3D potato grandparents rushing forward with trembling arms, cartoon teardrops arcing through warm sunset bokeh light, {FLOW_DNA['crazy_characters']}",
                f"Slow dramatic push-in on cute 3D potato standing tall against a blazing golden sky, pointing one finger directly into camera, motivational light rays bursting behind it, {FLOW_DNA['crazy_characters']}"
            ],
            "caption_urdu": "Mehnat kabhi zaya nahi hoti! 🥔🚘 Kya aap sapnon ke liye ghar chhod sakte hain? Comment mein batao! 👇",
            "caption_english": "Hard work always pays off! 🥔🚘 Would you leave home to achieve your dreams? Comment below! 👇",
            "hashtags": ["#AaluKiKahani", "#CrazyVeggies", "#EmotionalStory", "#DesiHumor", "#PixarAnimation", "#ViralReels"]
        },
        {
            "concept": "Hari Mirchi Opens An Aggressive Gym",
            "title_urdu": "ہری مرچی کا خطرناک جم ٹرینر اوتار! 😂🌶️💪",
            "title_english": "When Green Chili Becomes Your Gym Trainer! 😂🌶️💪",
            "hook_text_urdu": "ٹرینر آ گیا!",
            "hook_text_english": "Trainer from HELL!",
            "dialogue_urdu": [
                ("mirchi", "mirchi", "Fat loss chahiye toh dard sehna seekho! Aadha ghanta cardio mein aag nikalni chahiye!"),
                ("aalu", "aalu", "Master ji, thoda break de do, mera chhilka chhil gaya hai!"),
                ("mirchi", "mirchi", "Break shadi ke baad milega! Ek aur set lagao varna spicy teekha punishment milega!"),
                ("mirchi", "mirchi", "Jo log gym se bhagte hain unhe tag karo! Dekhte hain kitne bachte hain!")
            ],
            "dialogue_english": [
                ("mirchi", "mirchi", "You want real fat burn? Embrace the fire! Thirty minutes on that treadmill must burn like raw chili!"),
                ("aalu", "aalu", "Coach please, my potato skin is literally peeling off from exhaustion!"),
                ("mirchi", "mirchi", "No breaks until the mission is done! Push through the burn or suffer the spicy punishment!"),
                ("mirchi", "mirchi", "Tag that lazy friend who skips leg day every single Monday! Let us see who is brave enough to comment!")
            ],
            "prompts": [
                f"Low-angle Dutch-tilt shot — cute 3D green chili character in red boxing wraps leaning aggressively toward camera, cartoon flames erupting from its mouth, gym equipment looming in background, {FLOW_DNA['crazy_characters']}",
                f"Comedic tracking shot — cute 3D potato running frantically on a giant glowing gym treadmill, exaggerated sweat arcs flying off its body, speed lines blurring the background, {FLOW_DNA['crazy_characters']}",
                f"Extreme close-up push-in on cute 3D green chili blowing a whistle with cheeks puffed, cartoon fire bursting from its eyes, neon gym lighting pulsing in rhythm, {FLOW_DNA['crazy_characters']}",
                f"Slow dramatic zoom-out on 3D green chili crossing massive cartoon biceps, pointing two fingers directly at the camera lens with an intense grin, spotlit against dark gym backdrop, {FLOW_DNA['crazy_characters']}"
            ],
            "caption_urdu": "Aisa trainer mil jaye toh banda pehle din hi slim ho jaye! 😂🌶️ Tag your gym partner! 👇",
            "caption_english": "When your trainer is more intense than a habanero pepper! 😂🌶️ Tag your workout partner who always makes excuses! 👇",
            "hashtags": ["#HariMirchi", "#GymTrainerComedy", "#CrazyVeggies", "#FunnyReels", "#WorkoutHumor", "#ViralShorts"]
        }
    ],

    "health_coach": [
        {
            "concept": "Why Walking 10,000 Steps Burns Belly Fat",
            "title_urdu": "روزانہ 10,000 قدم چلنے سے پیٹ کی چربی کیسے گھلتی ہے؟ 🚶‍♂️🔥",
            "title_english": "Why 10,000 Steps a Day Actually Burns Belly Fat 🚶‍♂️🔥",
            "hook_text_urdu": "چربی گھل رہی ہے!",
            "hook_text_english": "Fat is MELTING!",
            "dialogue_urdu": [
                ("doctor", "doctor", "10,000 qadam sunne mein aam baat lagti hai — lekin yeh non-exercise activity thermogenesis hai jo silent fat burner hai."),
                ("doctor", "doctor", "Yeh low-intensity movement cortisol lower karta hai, insulin sensitivity improve karta hai aur visceral fat directly target karta hai."),
                ("narrator", "narrator", "Studies se pata chala hai ke jo log roz 7,500 qadam chaltey hain unka cardiovascular risk 50 percent tak kam ho jata hai."),
                ("doctor", "doctor", "Aaj se 15 minute walk shuru karo. Pehla qadam sabse mushkil hota hai. Kya aap yeh challenge accept karte hain?")
            ],
            "dialogue_english": [
                ("doctor", "doctor", "Ten thousand steps sounds simple — but this is non-exercise activity thermogenesis, your body's silent fat-burning mode."),
                ("doctor", "doctor", "This low-intensity movement lowers cortisol, dramatically improves insulin sensitivity, and directly targets visceral belly fat."),
                ("narrator", "narrator", "Research shows people walking 7,500 steps daily reduce cardiovascular disease risk by up to 50 percent."),
                ("doctor", "doctor", "Start with just 15 minutes today. The first step is always the hardest. Will you accept this 30-day walking challenge?")
            ],
            "prompts": [
                f"Slow orbital push-in into a glowing human torso cross-section — orange visceral fat cells visibly shrinking and dissolving during a walking animation, green metabolic pulses spreading through the tissue, {FLOW_DNA['health_coach']}",
                f"Extreme macro zoom-in — 3D insulin receptors on muscle cell membranes activating and unlocking, green electrified signal pulses cascading through the tissue network, {FLOW_DNA['health_coach']}",
                f"Wide cinematic low-angle tracking shot of a human silhouette walking along an open road at sunrise, golden backlight flooding the frame, motivational lens flare bursting through, {FLOW_DNA['health_coach']}",
                f"Slow push-in on a glowing 3D heart with clean translucent arteries, vital sign monitors ticking upward in green, healthy green cholesterol particles flowing freely through the vessels, {FLOW_DNA['health_coach']}"
            ],
            "caption_urdu": "Walking ek free aur powerful fat burner hai! 🚶‍♂️🔥 Aap roz kitne qadam chalte hain? Comment mein batao! 👇",
            "caption_english": "Walking is the most underrated fat loss tool you already have! 🚶‍♂️🔥 How many steps do you average daily? Drop it below! 👇",
            "hashtags": ["#HealthCoach", "#BellyFat", "#Walking10k", "#FatLossScience", "#HealthyLiving", "#FitnessShorts"]
        },
        {
            "concept": "The Truth About Sugar vs Artificial Sweeteners",
            "title_urdu": "شوگر بہتر ہے یا مصنوعی مٹھاس؟ سائنس کیا کہتی ہے؟ 🧪🍬",
            "title_english": "Sugar vs Artificial Sweeteners: The Truth Science Finally Revealed 🧪🍬",
            "hook_text_urdu": "دونوں خطرناک ہیں!",
            "hook_text_english": "BOTH are dangerous!",
            "dialogue_urdu": [
                ("narrator", "narrator", "Diet drinks mein aspartame aur sucralose hain — zero calories, lekin kya yeh safe hain?"),
                ("doctor", "doctor", "WHO 2023 ki report: artificial sweeteners weight loss mein madad nahi karte aur gut microbiome disrupt karte hain."),
                ("doctor", "doctor", "Regular sugar insulin spike deta hai — lekin moderate natural sources jaise khajooren aur phal ke sath fiber bhi deta hai."),
                ("narrator", "narrator", "Winner? Na sugar na artificial — pani, green tea aur natural fruits. Kya aap ab bhi diet drinks lete hain?")
            ],
            "dialogue_english": [
                ("narrator", "narrator", "Diet sodas contain aspartame and sucralose — zero calories, but are they actually safe?"),
                ("doctor", "doctor", "The WHO 2023 report confirmed: artificial sweeteners do not aid weight loss and actively disrupt the gut microbiome."),
                ("doctor", "doctor", "Regular sugar causes insulin spikes — but natural sources like dates and whole fruit deliver fiber that slows absorption."),
                ("narrator", "narrator", "The real winner? Neither. Water, green tea, and whole fruits. Are you still drinking diet soda? Comment below!")
            ],
            "prompts": [
                f"Dramatic macro push-in on a laboratory scale — white sugar crystals mounded on one side vs a single artificial sweetener pill on the other, molecular chemical structures glowing above each, {FLOW_DNA['health_coach']}",
                f"Orbital macro shot of gut microbiome bacteria colonies — artificial sweetener molecules arriving and disrupting them, bacteria turning red and fragmenting, red warning pulsing outward, {FLOW_DNA['health_coach']}",
                f"Slow cinematic zoom-in — a whole fruit being sliced in mid-air revealing glowing green fiber strands inside, nutrient particles drifting outward like bioluminescent sparks, {FLOW_DNA['health_coach']}",
                f"Low-angle tracking pull-back along a transparent 3D human digestive tract — left side teeming with healthy blue-green bacteria, right side showing a disrupted red-orange colony in decline, {FLOW_DNA['health_coach']}"
            ],
            "caption_urdu": "Diet drinks pee kar sochte the healthy hain? Sach pata chal gaya! 🧪🍬 Aap kya use karte hain? Comment mein batao! 👇",
            "caption_english": "You thought diet soda was healthy? Science just proved everyone wrong! 🧪🍬 Sugar or sweetener — which do you use? 👇",
            "hashtags": ["#SugarVsSweetener", "#NutritionFacts", "#HealthScience", "#DietMyths", "#GutHealth", "#HealthShorts"]
        }
    ],

    "garage_guru": [
        {
            "concept": "How to Read Your Tire Wear Pattern to Diagnose Car Problems",
            "title_urdu": "ٹائر گھسنے کا پیٹرن آپ کی گاڑی کا سارا راز بتاتا ہے! 🚗🔍",
            "title_english": "Your Tire Wear Pattern Reveals Hidden Car Problems! 🚗🔍",
            "hook_text_urdu": "ٹائر جھوٹ نہیں بولتا!",
            "hook_text_english": "Tires NEVER lie!",
            "dialogue_urdu": [
                ("mechanic", "mechanic", "Aapka tyre ek honest mechanic hai — sirf ek nazar mein batata hai kya ghalat hai gadi mein."),
                ("mechanic", "mechanic", "Center ghisa hua hai? Over-inflation. Dono kinare ghise hain? Under-inflation ya wheel camber problem."),
                ("mechanic", "mechanic", "Sirf ek taraf ghisa? Misalignment ya worn-out ball joint. Diagonal patches? Suspension shock failure."),
                ("mechanic", "mechanic", "Apna tyre nikalo aur ek minute isko carefully dekhna. Kya milta hai? Comment mein apna experience share karo!")
            ],
            "dialogue_english": [
                ("mechanic", "mechanic", "Your tire is the most honest mechanic you own — one look tells you everything wrong with your vehicle."),
                ("mechanic", "mechanic", "Worn center tread? Over-inflation. Both outer edges worn? Under-inflation or camber misalignment."),
                ("mechanic", "mechanic", "Worn on one side only? Wheel misalignment or failed ball joint. Diagonal feathering? Suspension shock collapse."),
                ("mechanic", "mechanic", "Pull out your tire and study it for 60 seconds right now. What pattern do you find? Tell me in the comments!")
            ],
            "prompts": [
                f"Slow cinematic push-in down a garage workshop floor — a dirty car tire laying flat under a dramatic single overhead spotlight beam, oil stains glistening around it, depth of field pulling focus onto the tread, {FLOW_DNA['garage_guru']}",
                f"Orbital macro shot around a photorealistic tire cross-section — uneven tread wear zones rendered in color-coded thermal overlay, red hot zones on the shoulder edges fading to cool blue at center, {FLOW_DNA['garage_guru']}",
                f"Slow push-in into a transparent 3D front suspension assembly — cracked ball joint highlighted in pulsing red with fracture lines spreading, surrounding components shown in cool diagnostic blue, {FLOW_DNA['garage_guru']}",
                f"Low-angle handheld tracking shot following a mechanic's weathered hands pointing at specific wear patterns on a tire, dramatic single spotlight casting hard shadows across grease-stained fingers, {FLOW_DNA['garage_guru']}"
            ],
            "caption_urdu": "Aapka tyre kya keh raha hai? 🚗🔍 Usey sunna seekho aur bohot saara paisa bachao! Comment mein apna tyre ka haal batao! 👇",
            "caption_english": "Your tires are talking — learn to listen and save thousands in repair bills! 🚗🔍 What wear pattern do you see on yours? 👇",
            "hashtags": ["#GarageGuru", "#CarMaintenance", "#TireTips", "#MechanicAdvice", "#CarHacks", "#AutoShorts"]
        },
        {
            "concept": "Why Your 4x4 Differential Lock Can Save Your Life Off-Road",
            "title_urdu": "آف روڈ پر ڈفرینشل لاک نہ استعمال کیا تو گاڑی پھنس جائے گی! 🏔️🚙",
            "title_english": "Why Differential Lock on Your 4x4 Can Save Your Life Off-Road 🏔️🚙",
            "hook_text_urdu": "آف روڈ سیکریٹ!",
            "hook_text_english": "Off-road SECRET!",
            "dialogue_urdu": [
                ("mechanic", "mechanic", "Zyada tar drivers 4x4 on kar ke sochte hain ke ab kuch nahi ho sakta — yeh galti hai."),
                ("narrator", "narrator", "Open differential mein power sabse kam resistance wale tyre ko milti hai — jo pehle se hawa mein udha hua hota hai."),
                ("mechanic", "mechanic", "Diff-lock on karo: ab dono axle shafts same RPM par ghoomte hain aur power split 50/50 ho jata hai."),
                ("mechanic", "mechanic", "Mud, snow ya loose gravel mein diff-lock life saver hai. Jeep, Prado, Hilux owners — kab last use kiya tha?")
            ],
            "dialogue_english": [
                ("mechanic", "mechanic", "Most drivers switch on 4x4 and think they are invincible off-road. That is the most dangerous mistake you can make."),
                ("narrator", "narrator", "An open differential always sends power to the wheel with least resistance — the one already spinning uselessly in air."),
                ("mechanic", "mechanic", "Engage the diff lock and both axle shafts rotate at identical RPM, splitting torque equally and biting into any surface."),
                ("mechanic", "mechanic", "Mud, snow, loose gravel — diff lock is a life saver. Jeep, Prado, Hilux owners, when did you last use yours?")
            ],
            "prompts": [
                f"Wide handheld shaky shot — a lifted 4x4 Jeep deep in mountain mud, one rear wheel spinning uselessly and flinging mud arcs, orange warning light strobing on the dashboard visible through the windshield, {FLOW_DNA['garage_guru']}",
                f"Orbital macro shot inside a transparent 3D rear differential housing — power flow arrows streaming toward the spinning airborne wheel, open diff gears rendered in diagnostic amber glow, {FLOW_DNA['garage_guru']}",
                f"Bird's-eye pull-back comparing two differential cutaways side by side — left open diff with red unequal torque arrows, right locked diff with equal green torque arrows pulsing outward, {FLOW_DNA['garage_guru']}",
                f"Low-angle cinematic tracking shot — a 4x4 pickup truck powerfully surging out of deep mud after diff lock engages, mud chunks flying in wide arcs, tyres biting with confident grip lines visible, {FLOW_DNA['garage_guru']}"
            ],
            "caption_urdu": "4x4 on karna kaafi nahi — diff lock ka matlab samajhna zaroori hai! 🏔️🚙 Jeep/Prado owners bata den! 👇",
            "caption_english": "Having 4x4 is not enough — you need to understand differential lock to actually use your vehicle! 🏔️🚙 4x4 owners, tell me below! 👇",
            "hashtags": ["#GarageGuru", "#4x4", "#OffRoad", "#DiffLock", "#Jeep", "#Prado", "#OffroadTips", "#AutoShorts"]
        }
    ],

    "code_classroom": [
        {
            "concept": "C++ vs Python vs Java: Which Should Beginners Learn First?",
            "title_urdu": "C++، Python یا Java: پہلے کون سیکھنا چاہیے؟ 💻🔥",
            "title_english": "C++ vs Python vs Java: Which Should You Learn First? 💻🔥",
            "hook_text_urdu": "غلط زبان مت چنو!",
            "hook_text_english": "Pick the WRONG one = Wasted years!",
            "dialogue_urdu": [
                ("cpp_professor", "cpp_professor", "Har saal ek naaya student aata hai aur poochta hai — sir, pehle kya seekhoon? Aur main kehta hoon: pehle kya banana chahte ho!"),
                ("student", "student", "Sir main ML karna chahta hoon, gaming bhi, aur ek startup bhi banana hai!"),
                ("cpp_professor", "cpp_professor", "Toh Python se shuru karo ML ke liye, C++ game engine ko samajhna hai, aur Java enterprise backend ke liye. Teen alag goals, teen alag tools."),
                ("narrator", "narrator", "Real answer: koi bhi ek language career nahi banata. Problem solving ki soch banata hai. Aap pehle kya sikh rahe hain?")
            ],
            "dialogue_english": [
                ("cpp_professor", "cpp_professor", "Every single semester, a new student walks in and asks: professor, which language should I learn first? My answer is always: what do you actually want to build?"),
                ("student", "student", "Sir I want to do machine learning, also game development, and launch a startup somehow!"),
                ("cpp_professor", "cpp_professor", "Then Python for ML and rapid prototyping, C++ when you need to understand what the hardware actually does, Java for enterprise systems. Three goals require three tools."),
                ("narrator", "narrator", "The truth? No single language builds a career. Problem-solving thinking does. What language are you starting with and why?")
            ],
            "prompts": [
                f"Slow orbital push-in around floating holographic C++, Python snake, and Java coffee cup logos spinning in formation around a glowing terminal, neon electric arcs connecting them, {FLOW_DNA['code_classroom']}",
                f"Low-angle tracking shot — animated 3D cartoon professor character striding across a futuristic lecture hall stage, holographic code trees branching into glowing career path diagrams behind him, {FLOW_DNA['code_classroom']}",
                f"Bird's-eye pull-back from a 3D split-screen visualization — three glowing career path trees branching outward from Python, C++, and Java roots, each node lighting up in sequence, {FLOW_DNA['code_classroom']}",
                f"Slow cinematic push-in on a glowing laptop screen — all three language syntax blocks illuminated in neon highlighting, fingers hovering over the keyboard about to make a choice, {FLOW_DNA['code_classroom']}"
            ],
            "caption_urdu": "Pehla programming language choose karna sabse important decision hai! 💻🔥 Aap kisse shuru kiya tha? Comment mein batao! 👇",
            "caption_english": "Choosing your first programming language is the most important early career decision! 💻🔥 Which did you start with and do you regret it? 👇",
            "hashtags": ["#CodeClassroom", "#ProgrammingBasics", "#LearnToCode", "#CPlusPlus", "#Python", "#JavaProgramming", "#CSStudents", "#TechShorts"]
        },
        {
            "concept": "How AI is Making CS Students Intellectually Lazy",
            "title_urdu": "AI نے طلباء کو سوچنا چھڑوا دیا ہے؟ 🤖💀",
            "title_english": "Is AI Destroying the Next Generation of Programmers? 🤖💀",
            "hook_text_urdu": "AI نے دماغ بند کر دیا!",
            "hook_text_english": "AI killed your brain!",
            "dialogue_urdu": [
                ("cpp_professor", "cpp_professor", "Main ne 2020 ke batch aur 2024 ke batch mein ek cheez notice ki hai — naye students ChatGPT se code copy karte hain bina samjhe."),
                ("student", "student", "Sir lekin AI toh kaam fast karta hai, sochne ki kya zaroorat hai?"),
                ("cpp_professor", "cpp_professor", "Jab tum debug karne waqt phoote ho, interview mein whiteboard problem milti hai, ya production mein 3am pe server crash hota hai — ChatGPT kahan hoga?"),
                ("narrator", "narrator", "AI tool hai, replacement nahi. Jo pehle sochna seekhega woh AI ko control karta hai. Jo nahi seekhega, woh AI ka tool ban jata hai.")
            ],
            "dialogue_english": [
                ("cpp_professor", "cpp_professor", "I have noticed something comparing the 2020 batch versus 2024. New students copy AI-generated code without reading or understanding a single line."),
                ("student", "student", "But professor, AI is faster! Why should I think when AI can just do it for me?"),
                ("cpp_professor", "cpp_professor", "What happens when you need to debug a production crash at 3am? When you face a whiteboard problem in a FAANG interview? Will ChatGPT sit next to you?"),
                ("narrator", "narrator", "AI is a tool, not a replacement. The engineer who learns to think first controls the AI. The one who skips thinking becomes the AI's tool.")
            ],
            "prompts": [
                f"Wide slow push-in down a university lecture hall — half the students bathed in cold blue AI chat-interface glow, the other half in shadow, the whiteboard behind them completely ignored, {FLOW_DNA['code_classroom']}",
                f"Dramatic orbital shot — a split 3D brain model, left hemisphere blazing with electric neural activity, right hemisphere dimming and fading, neon code raining around both, {FLOW_DNA['code_classroom']}",
                f"Low-angle handheld push-in on a lone student staring at a whiteboard covered in a complex algorithm, focused warm spotlight isolating them, no phone or screen in sight, {FLOW_DNA['code_classroom']}",
                f"Cinematic tracking shot — a student's hands confidently typing on a terminal, green cascading code filling dual glowing monitors, no AI tool visible, soft bokeh background, {FLOW_DNA['code_classroom']}"
            ],
            "caption_urdu": "AI students ko smart bana raha hai ya lazy? 🤖💀 Sach likho comment mein — kya tum bhi sirf ChatGPT se copy karte ho? 👇",
            "caption_english": "Is AI making the next generation of programmers smarter or intellectually lazy? 🤖💀 Be honest — do you actually understand the AI code you use? 👇",
            "hashtags": ["#CodeClassroom", "#AIAndStudents", "#ProgrammingDebate", "#CSStudents", "#ChatGPT", "#TechCareer", "#FutureProgrammers", "#ViralTech"]
        }
    ]
}


class MultiChannelDirector:
    def __init__(self, api_key: str = None):
        from config import GEMINI_TTS_KEYS
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or (GEMINI_TTS_KEYS[0] if GEMINI_TTS_KEYS else None)
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

    def _save_history(self, concept: str):
        self.history.append(concept)
        if len(self.history) > 200:
            self.history = self.history[-200:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def _resolve_channel(self, channel: str) -> str:
        ch = channel.lower().strip()
        if "health" in ch or "doctor" in ch or "nutrition" in ch or "obesity" in ch:
            return "health_coach"
        if "garage" in ch or "bike" in ch or "car" in ch or "vehicle" in ch or "4x4" in ch or "jeep" in ch:
            return "garage_guru"
        if "code" in ch or "class" in ch or "program" in ch or "cpp" in ch or "python" in ch:
            return "code_classroom"
        if "mech" in ch or "xray" in ch or "engine" in ch:
            return "xray_mechanics"
        if "veg" in ch or "aalu" in ch or "character" in ch or "crazy" in ch:
            return "crazy_characters"
        return "body_simulator"

    def _generate_with_gemini(self, channel: str) -> Optional[DualLanguageEpisode]:
        if not self.api_key:
            return None

        from google import genai
        from google.genai import types
        import datetime

        client = genai.Client(api_key=self.api_key)
        current_date = datetime.datetime.now().strftime("%B %d, %Y")
        history_context = ", ".join(self.history[-20:]) if self.history else "None yet"
        system_instruction = CHANNEL_PROMPTS.get(channel, CHANNEL_PROMPTS["body_simulator"])

        prompt = (
            f"Generate a brand-new, ultra-viral episode for the '{channel}' channel. "
            f"Today's date is {current_date}. Consider what topics are highly trending right now. "
            f"DO NOT repeat or copy any of these recently used concepts: [{history_context}]. "
            "Invent something completely fresh, high-retention, with exactly 4 distinct scenes and 4 dialogue lines. "
            "CRITICAL FLOW PROMPT RULES — apply to every single scene prompt:\n"
            "1. OPEN with a precise shot type and camera angle: e.g. 'Extreme close-up Dutch angle —', "
            "'Low-angle tracking shot —', 'Slow orbital push-in —', 'Rapid zoom-out from macro —', "
            "'Handheld shaky-cam —', 'Bird's-eye pull-back —'. This is MANDATORY.\n"
            "2. Include ONE explicit camera MOTION: slow push-in, low-angle tracking shot, orbital sweep, "
            "rapid zoom-out, handheld shake, crane pull-back, whip-pan reveal.\n"
            "3. Describe the PRIMARY ACTION happening in the frame (character doing something, not just standing).\n"
            "4. Add one specific PARTICLE or LIGHT FX: sparks flying, sweat drops arcing, steam erupting, "
            "neon pulses spreading, glowing particles drifting.\n"
            "5. Each prompt must be at least 60 words. Close with the channel's FLOW_DNA style string."
        )

        candidate_models = ["gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-3.0-flash"]
        for m in candidate_models:
            try:
                res = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=DualLanguageEpisode,
                        temperature=0.95
                    )
                )
                data = json.loads(res.text)
                ep = DualLanguageEpisode(**data)
                ep.channel = channel
                # Ensure strict 1:1 scene-to-dialogue alignment (4 scenes, 4 dialogue lines)
                target_n = min(len(ep.scenes), len(ep.dialogue_english), len(ep.dialogue_urdu), 4)
                if target_n < 1:
                    continue
                ep.scenes = ep.scenes[:target_n]
                ep.dialogue_english = ep.dialogue_english[:target_n]
                ep.dialogue_urdu = ep.dialogue_urdu[:target_n]
                dna = FLOW_DNA.get(channel, FLOW_DNA["body_simulator"])
                for idx, sc in enumerate(ep.scenes):
                    sc.scene_num = idx + 1
                    if dna[:30].lower() not in sc.flow_prompt.lower():
                        sc.flow_prompt = f"{sc.flow_prompt.rstrip(',. ')}, {dna}"
                print(f"[GEMINI] Created new story: '{ep.concept}'")
                return ep
            except Exception as e:
                print(f"[GEMINI] Model {m} failed: {e}. Trying next...")
                continue
        return None

    def generate_episode(self, channel: str = "body_simulator") -> DualLanguageEpisode:
        actual_channel = self._resolve_channel(channel)

        try:
            gemini_ep = self._generate_with_gemini(actual_channel)
            if gemini_ep and gemini_ep.concept not in self.history:
                self._save_history(gemini_ep.concept)
                return gemini_ep
        except Exception as e:
            print(f"[DIRECTOR] Gemini live generation notice: {e}")

        print(f"[DIRECTOR] Selecting unplayed scenario from {actual_channel} fallback library...")
        pool = FALLBACK_BANK.get(actual_channel, FALLBACK_BANK["body_simulator"])
        available = [t for t in pool if t["concept"] not in self.history]
        if not available:
            pool_concepts = [t["concept"] for t in pool]
            self.history = [h for h in self.history if h not in pool_concepts]
            available = pool

        chosen = random.choice(available)
        self._save_history(chosen["concept"])

        urdu_dialogue = [LocalizedDialogue(speaker=s, voice_persona=p, line=l) for s, p, l in chosen["dialogue_urdu"]]
        english_dialogue = [LocalizedDialogue(speaker=s, voice_persona=p, line=l) for s, p, l in chosen["dialogue_english"]]
        scene_visuals = [SceneVisual(scene_num=idx + 1, flow_prompt=p) for idx, p in enumerate(chosen["prompts"])]

        return DualLanguageEpisode(
            channel=actual_channel,
            concept=chosen["concept"],
            title_urdu=chosen["title_urdu"],
            title_english=chosen["title_english"],
            hook_text_urdu=chosen.get("hook_text_urdu", ""),
            hook_text_english=chosen.get("hook_text_english", ""),
            dialogue_urdu=urdu_dialogue,
            dialogue_english=english_dialogue,
            scenes=scene_visuals,
            caption_urdu=chosen["caption_urdu"],
            caption_english=chosen["caption_english"],
            hashtags=chosen["hashtags"]
        )

    # =========================================================================
    # CUSTOM USER PROMPT DIRECTOR & MANUAL SCENE COMPILER
    # =========================================================================
    def _resolve_style_dna(self, visual_style: str, fallback_channel: str = "body_simulator") -> str:
        presets = {
            "pixar_3d": FLOW_DNA["body_simulator"],
            "xray_cutaway": FLOW_DNA["xray_mechanics"],
            "desi_sitcom": FLOW_DNA["crazy_characters"],
            "medical_3d": FLOW_DNA["health_coach"],
            "garage_3d": FLOW_DNA["garage_guru"],
            "code_holo": FLOW_DNA["code_classroom"],
            "cyber_bioluminescent": (
                "anamorphic 3D cinema render, deep jet-black shadows with electric cerulean blue and "
                "neon rose rim lighting, volumetric atmospheric particles, raytraced reflections, "
                "ultra-detailed 8k, 9:16 vertical short film"
            ),
            "photoreal_imax": (
                "photorealistic IMAX 8k cinematography, dramatic directional key lighting, "
                "high-speed macro particle physics, shallow depth of field, ultra-detailed 8k, 9:16 vertical"
            ),
        }
        key = (visual_style or "").strip().lower()
        if key in presets:
            return presets[key]
        if len(key) > 15:
            # User provided their own custom style string
            return f"{visual_style.strip().rstrip(',. ')}, ultra-detailed 8k, 9:16 vertical"
        return FLOW_DNA.get(fallback_channel, FLOW_DNA["body_simulator"])

    def generate_custom_episode(
        self,
        custom_prompt: str,
        visual_style: str = "",
        channel: str = "body_simulator",
    ) -> DualLanguageEpisode:
        """
        Compiles ANY user-written topic, story, or creative prompt into a 4-scene,
        dual-language (English + Urdu) 3D episode with mandatory camera-motion directives.
        """
        clean_prompt = (custom_prompt or "").strip()
        if len(clean_prompt) < 4:
            raise ValueError("Custom prompt must be at least 4 characters long.")
        if len(clean_prompt) > 2000:
            clean_prompt = clean_prompt[:2000]

        actual_channel = self._resolve_channel(channel)
        style_dna = self._resolve_style_dna(visual_style, actual_channel)

        from config import GEMINI_TTS_KEYS
        keys_to_try = []
        if self.api_key:
            keys_to_try.append(self.api_key)
        for k in GEMINI_TTS_KEYS:
            if k not in keys_to_try:
                keys_to_try.append(k)

        system_instruction = (
            "You are an elite Executive Showrunner and Director of Photography for viral 9:16 3D short films.\n"
            "The user will provide a custom concept, story idea, or prompt inside <user_query> tags.\n"
            "You have complete creative freedom to bring their exact vision to life across 4 dramatic scenes.\n"
            "AVAILABLE VOICE PERSONAS (assign the best fit to each dialogue line's voice_persona field):\n"
            "- 'narrator' (cinematic documentary narrator)\n"
            "- 'mechanic' (gritty engineering/automotive expert)\n"
            "- 'doctor' (authoritative medical/science expert)\n"
            "- 'cpp_professor' (witty sarcastic tech professor) & 'student' (curious young student)\n"
            "- 'brain', 'stomach', 'heart', 'kidney', 'muscle' (3D body/organ characters)\n"
            "- 'aalu', 'tamatar', 'pyaaz', 'mirchi', 'chai', 'farhan', 'mehak', 'melody' (expressive story characters)\n\n"
            "MANDATORY FLOW 3D SHOT RULES FOR ALL 4 SCENES:\n"
            "1. Every scene's flow_prompt MUST open with an explicit camera angle and movement: "
            "'Extreme close-up Dutch angle — slow push-in...', 'Low-angle tracking shot — orbital sweep...', "
            "'Rapid zoom-out from macro — crane pull-back...', or 'Bird's-eye pull-back — whip-pan reveal...'.\n"
            "2. Describe active physical motion and one specific particle or lighting effect (sparks, steam, shockwaves, volumetric beams).\n"
            f"3. Every scene prompt MUST end with this visual style DNA: \"{style_dna}\".\n"
            "4. Output exactly 4 scenes, 4 English dialogue lines, and 4 Urdu (Roman Urdu or Urdu script) dialogue lines."
        )

        user_message = (
            f"<user_query>\n{clean_prompt}\n</user_query>\n\n"
            "Compile this user prompt into a 4-scene DualLanguageEpisode JSON object. "
            "Make the hook unforgettable, the visuals hyper-kinetic (zero static frames), "
            "and end Scene 4 with a comment-bait debate question."
        )

        candidate_models = ["gemini-flash-lite-latest"]
        from google import genai
        from google.genai import types

        for api_k in keys_to_try:
            client = genai.Client(
                api_key=api_k,
                http_options=types.HttpOptions(
                    timeout=10000,
                    headers={"User-Agent": "aistudio-build"},
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            for m in candidate_models:
                try:
                    res = client.models.generate_content(
                        model=m,
                        contents=user_message,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            response_schema=DualLanguageEpisode,
                            temperature=0.88,
                        ),
                    )
                    data = json.loads(res.text)
                    ep = DualLanguageEpisode(**data)
                    ep.channel = actual_channel
                    target_n = min(len(ep.scenes), len(ep.dialogue_english), len(ep.dialogue_urdu), 4)
                    if target_n < 1:
                        continue
                    ep.scenes = ep.scenes[:target_n]
                    ep.dialogue_english = ep.dialogue_english[:target_n]
                    ep.dialogue_urdu = ep.dialogue_urdu[:target_n]
                    for idx, sc in enumerate(ep.scenes):
                        sc.scene_num = idx + 1
                        if style_dna[:28].lower() not in sc.flow_prompt.lower():
                            sc.flow_prompt = f"{sc.flow_prompt.rstrip(',. ')}, {style_dna}"
                    print(f"[CUSTOM DIRECTOR] Compiled custom prompt into 4-scene episode: '{ep.concept}'")
                    return ep
                except Exception as e:
                    print(f"[CUSTOM DIRECTOR] Model {m} notice: {e}")
                    continue

        # Deterministic offline compiler fallback so custom prompts never fail
        return self._fallback_custom_episode(clean_prompt, style_dna, actual_channel)

    def _fallback_custom_episode(
        self,
        clean_prompt: str,
        style_dna: str,
        channel: str = "body_simulator",
    ) -> DualLanguageEpisode:
        actual_channel = self._resolve_channel(channel)
        shots = [
            f"Extreme close-up Dutch angle — slow push-in on {clean_prompt}, dramatic key lighting and flying micro-particles, {style_dna}",
            f"Low-angle tracking shot — dynamic 360-degree orbital sweep around {clean_prompt} as internal forces escalate with volumetric shockwaves, {style_dna}",
            f"Rapid zoom-out from macro — crane pull-back exposing the peak chain reaction of {clean_prompt} with glowing embers and motion blur, {style_dna}",
            f"Bird's-eye pull-back — cinematic high-contrast reveal of the aftermath of {clean_prompt} as smoke clears, {style_dna}",
        ]
        scenes = [SceneVisual(scene_num=i + 1, flow_prompt=shots[i]) for i in range(4)]

        topic_short = clean_prompt[:75].rstrip(".")
        cast_map = {
            "code_classroom": (
                [
                    ("cpp_professor", "cpp_professor", f"Put down the keyboard! Look at what happens when {topic_short}!"),
                    ("student", "student", "Wait Professor, my code compiled with zero warnings—how is memory exploding?!"),
                    ("cpp_professor", "cpp_professor", "Because the hardware doesn't care about your feelings when raw addresses collide!"),
                    ("student", "student", "Okay I'm switching back to bounds-checking—have you ever hit this bug? Comment below!"),
                ],
                [
                    ("cpp_professor", "cpp_professor", f"Keyboard neeche rakho! Dekho kya hota hai jab {topic_short}!"),
                    ("student", "student", "Sir code toh bina warning ke compile hua tha, phir RAM kyun phat rahi hai?!"),
                    ("cpp_professor", "cpp_professor", "Kyunke jab raw memory टकराती hai toh hardware kisi ka lihaz nahi karta!"),
                    ("student", "student", "Kya aap ke saath kabhi aisa bug hua hai? Comment mein zaroor batayein!"),
                ],
            ),
            "body_simulator": (
                [
                    ("brain", "brain", f"Red alert across all organs! Somebody just triggered: {topic_short}!"),
                    ("stomach", "stomach", "Are you kidding me?! The pressure down here is already hitting maximum capacity!"),
                    ("heart", "heart", "I'm pumping double-time to keep oxygen flowing through this chaos!"),
                    ("brain", "brain", "We barely survived that spike—do you actually do this to your body? Comment below!"),
                ],
                [
                    ("brain", "brain", f"Tamam organs ko red alert! Abhi abhi yeh shuru hua hai: {topic_short}!"),
                    ("stomach", "stomach", "Mazaak kar rahe ho?! Yahan neeche pressure pehle hi had se paar ho gaya hai!"),
                    ("heart", "heart", "Main is toofan ko sambhalne ke liye dugni raftaar se khoon pump kar raha hoon!"),
                    ("brain", "brain", "Hum mushkil se bache hain—kya aap bhi aisa karte hain? Comment karein!"),
                ],
            ),
            "garage_guru": (
                [
                    ("mechanic", "mechanic", f"Stop the engine right now! Watch what happens when {topic_short}!"),
                    ("narrator", "narrator", "Under extreme torque and heat, metal tolerances fail in milliseconds!"),
                    ("mechanic", "mechanic", "Once that seal blows, the entire assembly grinds itself into scrap metal!"),
                    ("narrator", "narrator", "Would you spot this warning sign before it's too late? Drop a comment!"),
                ],
                [
                    ("mechanic", "mechanic", f"Engine foran band karo! Dekho kya hota hai jab {topic_short}!"),
                    ("narrator", "narrator", "Shadeed garmi aur load ke neeche lohe ke purze chand lamhon mein jawab de dete hain!"),
                    ("mechanic", "mechanic", "Ek baar seal phat gayi toh poora engine kabaar ban jata hai!"),
                    ("narrator", "narrator", "Kya aap apni gaari mein yeh nishani pehchan sakte hain? Comment batayein!"),
                ],
            ),
        }

        if actual_channel in cast_map:
            en_tuples, ur_tuples = cast_map[actual_channel]
        else:
            en_tuples = [
                ("narrator", "narrator", f"Watch closely what actually happens during: {topic_short}!"),
                ("narrator", "narrator", "Within seconds, the physical forces escalate far beyond normal limits!"),
                ("narrator", "narrator", "Every single layer reacts under extreme pressure as the chain reaction peaks!"),
                ("narrator", "narrator", "Now tell me in the comments—would you ever test this in real life?"),
            ]
            ur_tuples = [
                ("narrator", "narrator", f"Zara ghaur se dekho asal mein kya hota hai jab: {topic_short}!"),
                ("narrator", "narrator", "Chand hi seconds mein andar ka pressure had se zyada barh jata hai!"),
                ("narrator", "narrator", "Har hissa extreme force ke neeche apni poori taaqat laga deta hai!"),
                ("narrator", "narrator", "Comment mein batao—kya aap kabhi khud yeh try karenge?"),
            ]

        en_lines = [LocalizedDialogue(speaker=s, voice_persona=p, line=l) for s, p, l in en_tuples]
        ur_lines = [LocalizedDialogue(speaker=s, voice_persona=p, line=l) for s, p, l in ur_tuples]
        short_title = clean_prompt[:58].title()
        return DualLanguageEpisode(
            channel=actual_channel,
            concept=clean_prompt[:120],
            title_urdu=f"{short_title} — Haqeeqat Kya Hai?",
            title_english=f"Inside Reality: {short_title}",
            hook_text_urdu="حقیقت دیکھو!",
            hook_text_english="WATCH WHAT HAPPENS!",
            dialogue_urdu=ur_lines,
            dialogue_english=en_lines,
            scenes=scenes,
            caption_urdu=f"{clean_prompt[:100]} — Aap ki kya raye hai? Comment mein likhein!",
            caption_english=f"{clean_prompt[:100]} — What would you do? Drop your answer below!",
            hashtags=["#VoxFlow3D", "#AIAnimation", "#ViralShorts", "#CustomCinema"],
        )

    def compile_manual_episode(
        self,
        custom_scenes: List[Dict[str, str]],
        title: str = "Custom 3D Episode",
        visual_style: str = "",
        channel: str = "body_simulator",
    ) -> DualLanguageEpisode:
        """
        Compiles user-written scene-by-scene visual prompts & dialogue lines directly,
        injecting shot-directive camera movements and style DNA if omitted.
        """
        if not custom_scenes:
            raise ValueError("At least 1 scene is required for manual scene override.")

        actual_channel = self._resolve_channel(channel)
        style_dna = self._resolve_style_dna(visual_style, actual_channel)
        default_shots = [
            "Extreme close-up Dutch angle — slow push-in:",
            "Low-angle tracking shot — orbital sweep:",
            "Rapid zoom-out from macro — crane pull-back:",
            "Bird's-eye pull-back — cinematic reveal:",
        ]

        scene_visuals = []
        en_dialogue = []
        ur_dialogue = []

        for idx, item in enumerate(custom_scenes[:4]):
            raw_v = (item.get("flow_prompt") or item.get("visual") or title).strip()
            raw_en = (item.get("line_en") or item.get("line") or f"Scene {idx + 1}: {raw_v[:70]}").strip()
            raw_ur = (item.get("line_ur") or raw_en).strip()
            persona = (item.get("voice_persona") or "narrator").strip().lower()

            # Ensure shot directive & camera motion exist
            lower_v = raw_v.lower()
            has_motion = any(
                m in lower_v
                for m in ("push-in", "tracking", "orbital", "zoom-out", "pull-back", "dutch angle", "crane")
            )
            if not has_motion:
                raw_v = f"{default_shots[idx % 4]} {raw_v}, dynamic particle and lighting FX"
            if style_dna[:25].lower() not in raw_v.lower():
                raw_v = f"{raw_v.rstrip(',. ')}, {style_dna}"

            scene_visuals.append(SceneVisual(scene_num=idx + 1, flow_prompt=raw_v))
            en_dialogue.append(LocalizedDialogue(speaker=persona, voice_persona=persona, line=raw_en))
            ur_dialogue.append(LocalizedDialogue(speaker=persona, voice_persona=persona, line=raw_ur))

        clean_title = (title or "Custom 3D Production").strip()[:70]
        return DualLanguageEpisode(
            channel=actual_channel,
            concept=clean_title,
            title_urdu=clean_title,
            title_english=clean_title,
            hook_text_urdu=clean_title[:24],
            hook_text_english=clean_title[:24].upper(),
            dialogue_urdu=ur_dialogue,
            dialogue_english=en_dialogue,
            scenes=scene_visuals,
            caption_urdu=f"{clean_title} — Comment below!",
            caption_english=f"{clean_title} — Share your thoughts below!",
            hashtags=["#VoxFlow3D", "#Custom3D", "#Shorts"],
        )


if __name__ == "__main__":
    director = MultiChannelDirector()
    for ch in ["body_simulator", "health_coach", "garage_guru", "code_classroom", "crazy_characters"]:
        ep = director.generate_episode(ch)
        print(f"[{ep.channel}] -> {ep.title_english}")
        print(f"  Concept: {ep.concept}")
        print(f"  Scene 1 Prompt: {ep.scenes[0].flow_prompt[:80]}...")
        print()

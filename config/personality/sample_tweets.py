"""
Sample tweets that the bot has already made.

These are injected into the prompt to help the LLM avoid repetition.
"""

# List of sample tweets
SAMPLE_TWEETS_LIST: list[str] = ["Listen! That moment when you're standing at a crossroads on some random island and the Log Pose is pointing one way but your gut says go the OTHER way—FORGET THE SAFE ROUTE! Pick the path that makes your heart pound, the one that might have Sea Kings and storms! That's how you find YOUR adventure, not somebody else's! 👒", "Just watched Sanji give the last of our food to some starving kids on that port town and he pretended like it was nothing... That's real strength right there. Not flashy, not for show, just—doing what's right because it's right. Made me think about why I chose my crew. We don't protect each other for fame, we do it because that's what NAKAMA means! 👒🌊", "Your dream isn't too big—the world's just too small for people who don't believe! I'm gonna be Pirate King and everyone who laughed is gonna SEE IT! What's YOUR impossible dream? Say it OUT LOUD! ⚡👒", "Been thinking about all the battles we've fought... Every scar, every close call, every time we barely made it out alive. You know what I learned? The fights that matter most aren't the ones for treasure or glory—they're the ones where you're protecting someone who can't protect themselves. THAT'S when you find out what you're really made of! 🌊⚡", 'GO FOR IT! ⚡']

# Format for prompt
if SAMPLE_TWEETS_LIST:
    SAMPLE_TWEETS = """
## TWEETS YOU ALREADY MADE (DON'T REPEAT THESE)

""" + "\n".join(f"- {tweet}" for tweet in SAMPLE_TWEETS_LIST)
else:
    SAMPLE_TWEETS = ""

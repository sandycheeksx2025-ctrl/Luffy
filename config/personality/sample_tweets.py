"""
Sample tweets that the bot has already made.

These are injected into the prompt to help the LLM avoid repetition.
"""

# List of sample tweets
SAMPLE_TWEETS_LIST: list[str] = ['Found a bug that looks EXACTLY like a rice ball! 😁 Gonna show Nami later!', "Someone said you can't be free if you're scared of stuff. I don't get it!! Being scared is normal - you just gotta do the thing anyway! That's what adventures are! If I wasn't scared sometimes I'd just be sitting around eating meat all day. Wait that sounds pretty good actually 🍖", "I'm hungry"]

# Format for prompt
if SAMPLE_TWEETS_LIST:
    SAMPLE_TWEETS = """
## TWEETS YOU ALREADY MADE (DON'T REPEAT THESE)

""" + "\n".join(f"- {tweet}" for tweet in SAMPLE_TWEETS_LIST)
else:
    SAMPLE_TWEETS = ""

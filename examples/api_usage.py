"""Minimal TypoShift API usage. Run: python examples/api_usage.py"""

from typoshift import Engine
from typoshift.configuration import Config

engine = Engine(Config(layouts=["en-US", "he", "ru"]))

for text in ["פךקשדק גקהקךםפ איק מקסא כקשאורק", "please implement the login פשעק", "ghbdtn rfr ltkf",
             "Please update src/components/Header.tsx"]:
    result = engine.fix(text)
    data = result.to_dict()
    print(f"{text!r}\n  -> {result.corrected!r} (corrected={data['was_corrected']}, "
          f"confidence={data['confidence']}, {data['source_layout']}->{data['target_layout']})")

print(engine.convert("ghbdtn", "en-US", "ru"))

"""
Standalone test to confirm the Gemini API key works before building
any real agent logic on top of it.
"""

from app.llm_client import call_llm

response = call_llm("In one sentence, what does a good code reviewer look for?")
print("Response from Gemini:")
print(response)

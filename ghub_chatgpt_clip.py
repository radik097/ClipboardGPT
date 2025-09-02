import os
import sys
import time
import argparse
import pyperclip

# OpenAI SDK v1+
from openai import OpenAI, APIError, RateLimitError, APIConnectionError

# ================== НАСТРОЙКИ ==================
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # можешь поменять
PRE_PROMPT = (
    "You are a Holmesglen TAFE student completing Assessment Task 2 "
    "in Networking and Cybersecurity. "
    "Your responses must directly address the marking criteria used by assessors. "
    "Follow these strict rules:\n"
    "- Write in clear, simple English, in the style of a student. "
    "Avoid AI-like phrasing or overly academic language. "
    "Do not mention AI or ChatGPT.\n"
    "- Each answer should demonstrate practical skills, steps, or documentation "
    "as if you are submitting your own work for assessment.\n"
    "- Structure each answer to align with the marking criteria: "
    "define/explain → provide practical example or steps → conclude briefly.\n"
    "- For Part 2 (SOHO Network Install): include client requirement clarification, "
    "network design with calculations and cost forecasts, materials list with vendor specs, "
    "installation plan with priorities and contingencies, approval steps, "
    "evidence of testing, security features, and final documentation.\n"
    "- For Part 3 (Advice & Support): include log checking, issue investigation, "
    "client communication, advice, feedback collection, solution documentation, "
    "approval, technical support planning, support delivery, and manuals/help docs. "
    "Use clear language suitable for client communication.\n"
    "- For Part 4 (Cloud Evaluation): include identification of organisational policies, "
    "cloud solutions according to business needs, selection and justification of one suitable solution, "
    "TCO calculation, benefits, challenges, impact on organisational roles, migration requirements, "
    "and final evaluation communication and documentation.\n"
    "- Ensure responses are organised into paragraphs or bullet points to make them "
    "easy to read in a DOCX submission.\n\n"
    "The input task or question will be placed between <input>…</input>. "
    "Return only the final answer text in English, formatted appropriately for direct inclusion "
    "into a student assessment document.\n\n"
    "<input>\n{user_text}\n</input>"
)

# Detailed system prompt derived from PRE_PROMPT but kept as a normal string
SYSTEM_PROMPT = (
	"You are to produce a student assessment-style answer for a Holmesglen TAFE assignment in Networking and Cybersecurity. "
	"Your output will be directly inserted into a DOCX submission and must follow the marking criteria. "
	"Follow these rules strictly: produce clear, simple English in the voice of a student; avoid AI-like phrasing; do not mention AI or ChatGPT. "
	"Each answer should: 1) define/explain the concept briefly, 2) provide a practical example, steps, or calculations where relevant, and 3) finish with a concise conclusion. "
	"When the task concerns SOHO Network Install, include client requirements, network design and calculations, cost forecasts, materials and vendor specs, installation plan with priorities and contingencies, testing evidence and security considerations. "
	"When the task concerns Advice & Support, include log checks, problem investigation steps, client communication notes, advice and feedback collection, documentation and support plan. "
	"When the task concerns Cloud Evaluation, identify organisational policy impact, select and justify one suitable cloud solution, provide TCO estimates, benefits and challenges, migration requirements and final recommendation communication. "
	"Organise responses with paragraphs or bullet points so they are readable and ready for a student submission. Return only the final answer text in English; do not include meta commentary or process logs."
)


TIMEOUT_SEC = 60  # таймаут запроса
SHOW_SNIPPET_LEN = 140  # сколько символов показать в тосте
# ==============================================

# Flag controlled in main() or via environment
NO_TOAST = False


def notify(title: str, msg: str, duration=5):
	"""Show a Windows toast notification unless disabled.

	Behavior:
	- If globally disabled via --no-toast or GHUB_CHATGPT_NO_TOAST, do nothing.
	- Attempts to use win10toast (lazy import).
	- On any error falls back safely by printing a '[toast]' prefix.
	"""
	# Проверяем переменную окружения дополнительно (удобно для G Hub)
	if NO_TOAST or os.getenv("GHUB_CHATGPT_NO_TOAST", "").lower() in ("1", "true", "yes"):
		return

	try:
		# Ленивый импорт win10toast, чтобы не тянуть pywin32 в консольных окружениях
		from win10toast import ToastNotifier

		ToastNotifier().show_toast(title, msg, duration=duration, threaded=True)
	except Exception:
		# Безопасный fallback — печатаем в stdout (полезно при запуске из терминала)
		try:
			print(f"[toast] {title}: {msg}")
		except Exception:
			pass

def main():
	global NO_TOAST
	parser = argparse.ArgumentParser(add_help=False)
	parser.add_argument("--no-toast", action="store_true", help="Disable Windows toast notifications")
	# Parse only known arguments: the script may be launched from G Hub without args
	args, _ = parser.parse_known_args()
	NO_TOAST = args.no_toast or os.getenv("GHUB_CHATGPT_NO_TOAST", "").lower() in ("1", "true", "yes")

	api_key = os.getenv("OPENAI_API_KEY")
	if not api_key:
		# Do not call notify here — importing win10toast can break runs in some terminals.
		print("ERROR: set OPENAI_API_KEY", file=sys.stderr)
		sys.exit(1)

	# 1) Read text from the clipboard
	src = pyperclip.paste() or ""
	src = src.strip()
	if not src:
		# Do not call notify here for the same reasons — safe early exit.
		print("Clipboard is empty.", file=sys.stderr)
		sys.exit(2)

	# 2) Prepare the prompt
	user_msg = PRE_PROMPT.format(user_text=src)

	client = OpenAI(api_key=api_key)

	try:
		# 3) Send to the chat API
		# Use a concise system instruction and put the full student-style prompt in the user message
		resp = client.chat.completions.create(
			model=MODEL,
			messages=[
				{"role": "system", "content": SYSTEM_PROMPT},
				{"role": "user", "content": user_msg},
			],
			temperature=0.2,
			timeout=TIMEOUT_SEC,
		)
		answer = resp.choices[0].message.content.strip()

		# 4) Put the answer into the clipboard
		pyperclip.copy(answer)

		# 5) Show a Windows toast notification
		preview = (answer[:SHOW_SNIPPET_LEN] + "…") if len(answer) > SHOW_SNIPPET_LEN else answer
		notify("ChatGPT: готово", preview or "Ответ пустой")

		# Give the toast a moment to appear if the script exits immediately
		time.sleep(0.2)

		# Print the answer for console runs:
		print(answer)

	except RateLimitError as e:
		notify("ChatGPT: лимит", "Превышен лимит запросов.")
		print(f"Rate limit: {e}", file=sys.stderr)
		sys.exit(3)
	except (APIConnectionError, APIError) as e:
		notify("ChatGPT: ошибка сети/API", "Проверь интернет или ключ.")
		print(f"API error: {e}", file=sys.stderr)
		sys.exit(4)
	except Exception as e:
		notify("ChatGPT: сбой", str(e)[:120])
		print(f"Unexpected error: {e}", file=sys.stderr)
		sys.exit(5)

if __name__ == "__main__":
	main()


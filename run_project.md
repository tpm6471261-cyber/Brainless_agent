# Brainless Agent ko run karne ki step-by-step guide

Yeh guide local development aur owner-operated automation ke liye hai. Brainless Agent ek visible, persistent **Google Chrome** profile use karta hai. Login, CAPTCHA, MFA, payment confirmation, ya security challenge user ko khud complete karna hota hai; project in protections ko bypass nahi karta.

## 1. Prerequisites

- Python 3.11 ya newer (`python --version`)
- Git
- Official Google Chrome (recommended)
- Voice ke liye working microphone aur AssemblyAI API key (optional)
- Linux par GUI/display session; headless server par visible browser aur microphone kaam nahi karenge bina desktop/display setup ke

Repository root se sab commands chalayein:

```bash
cd /path/to/Brainless_agent
```

## 2. Virtual environment aur dependencies

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`app/config/providers.yaml` ka default `channel: chrome` hai, isliye normal runs installed Google Chrome use karte hain. `playwright install chromium` Playwright tooling/tests ke liye useful hai, lekin Google account login ke liye official Chrome install hona chahiye.

## 3. Local configuration

Example file ko local `.env` banane ke liye copy kar sakte hain:

```bash
cp .env.example .env
```

`.env` Git se ignored hai. **Important:** application `.env` ko automatically load nahi karti; production secrets process environment, service manager, ya secret manager se dein. Bash mein local file ko current shell mein load karne ka safe pattern:

```bash
set -a
source .env
set +a
```

Dashboard token optional hai. Agar set nahi kiya gaya to runtime cryptographically secure token automatically generate karke terminal mein print karega. Stable deployment token chahiye to kam se kam 16 characters ka token set karein:

```bash
export BRAINLESS_DASHBOARD_TOKEN="replace-with-a-long-random-local-token"
```

Windows PowerShell:

```powershell
$env:BRAINLESS_DASHBOARD_TOKEN = "replace-with-a-long-random-local-token"
```

Optional AssemblyAI voice configuration:

```bash
export ASSEMBLYAI_API_KEY="your-assemblyai-key"
export VOICE_MODE="push_to_talk"
```

API key commit na karein. Local dashboard ke **Voice → Configure AssemblyAI** form se key dene par woh sirf current process memory mein rahegi aur restart par clear ho jayegi.

## 4. Google account ko persistent Chrome profile mein login karna

Automation-launched Chromium/Chrome par Google kabhi-kabhi “This browser or app may not be secure” dikha sakta hai. Iska supported solution extension, cookie import, user-agent spoofing, ya security bypass nahi hai. Official Chrome ko **automation ke bahar** same dedicated profile ke saath ek baar open karke manually login karein.

Pehle Brainless Agent aur is profile ko use karne wale sab Chrome processes band karein. Phir repository root se apne OS ka command chalayein.

### Linux

```bash
google-chrome --user-data-dir="$PWD/data/browser-profile" --no-first-run
```

Kuch distributions par executable `google-chrome-stable` ho sakta hai:

```bash
google-chrome-stable --user-data-dir="$PWD/data/browser-profile" --no-first-run
```

### macOS

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="$PWD/data/browser-profile" --no-first-run
```

### Windows PowerShell

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --user-data-dir="$PWD\data\browser-profile" --no-first-run
```

Chrome mein required Google/chatbot accounts manually sign in karein, CAPTCHA/MFA khud complete karein, phir **poora Chrome close** karein. Ab `python run.py`, `python run_gui.py`, aur dashboard runtime isi `data/browser-profile` ko reuse karenge.

> Dedicated automation profile use karein—apna daily Chrome profile nahi. Ek profile ko do running Chrome processes mein ek saath open karne se profile-lock/corruption errors aa sakte hain.

### Kya Chrome extension banana chahiye?

Google login fix karne ke liye extension **na zaroori hai, na safe solution**. Extension Google authentication restrictions ko bypass nahi kar sakti aur usse password, cookies, tokens, ya session data handle nahi karna chahiye. Future mein tab/context bridge extension ban sakti hai, lekin usse authenticated localhost/native-messaging boundary, explicit permissions, runtime policy, aur audit trail chahiye. Current project ke liye official Chrome + dedicated persistent profile supported approach hai.

## 5. Project run modes

### CLI

```bash
python run.py cli
```

Task enter karein. Login/security page aaye to browser mein manually complete karke terminal mein Enter press karein.

### Desktop GUI

```bash
python run_gui.py
```

GUI se task, providers, pause/resume, emergency stop, login continuation, aur local history manage hoti hai.

### Web Command Center

```bash
python run.py
```

Windows PowerShell:

```powershell
python run.py
```

`run.py` ab Command Center start karta hai, secure token terminal mein print karta hai, aur default browser mein `http://127.0.0.1:8765` open karta hai. Printed token login dialog mein enter karein. Auto-open disable karna ho to `BRAINLESS_DASHBOARD_AUTO_OPEN=false` set karein. Legacy interactive task CLI ke liye `python run.py cli` use karein. Dashboard ko internet par directly expose na karein; remote use ke liye authenticated TLS reverse proxy lagayein.

### Agent ko screen area samjhana

1. Dashboard mein **Perception** page kholein.
2. **Guide agent on screen** select karein.
3. Area ka semantic naam (jaise `Search box`) aur type (`Text box`, `Button`, etc.) dein.
4. Desktop overlay aane par required control ke around mouse se rectangle drag karein. Cancel ke liye `Esc` press karein.
5. Runtime marked screenshot aur global bounds ko `user_guidance` perception source ke roop mein record karega.

Yeh hint khud click/type nahi karta. Agent ka proposed action ab bhi target resolution, governor, policy, permission, tool execution, re-observation, aur verification se guzarta hai. Selection 20 seconds mein cancel ho jati hai aur local graphical desktop session required hai.

Perception page ka **Desktop windows** section active window ke saath `normal`, `minimized`, `maximized`, aur `fullscreen` states dikhata hai. Native window enumeration abhi Windows par supported hai. Unsupported OS par runtime fake state banane ke bajay source ko unavailable rakhta hai.

### Jab requested skill available na ho

Example: user `Edit my video and add subtitles` mission create karta hai. Runtime pehle registered tools aur reusable agents check karta hai. Agar real `video.edit` adapter nahi hai, original mission safely pause hota hai aur ek separate constrained research mission free/open-source local tools ya agents compare karta hai. Dashboard Overview par capability gap aur missing tool visible hote hain.

Discovery ka matlab automatic trust ya installation nahi hai. Research mission purchase, signup, installation, private-file upload, aur external-agent execution nahi kar sakta. Candidate ko use karne se pehle real runtime adapter, permissions, policy/approval, sandboxing, and output verification required hain. Isliye personal agent new capabilities dhoondh sakta hai, lekin unavailable ability ka fake success claim nahi karega.

## 6. Voice setup aur push-to-talk

1. `assemblyai[extras]` `requirements.txt` ke saath install hota hai.
2. OS microphone permission Python/terminal ko dein.
3. `ASSEMBLYAI_API_KEY` environment mein set karein, ya authenticated Voice page se current session ke liye configure karein.
4. Dashboard start karein.
5. Voice page par **Hold to talk** press karke bolein, release karke finalized turn bhejein.

Recommended cost-safe default `push_to_talk` hai. Partial transcript sirf UI update karta hai; runtime command finalized turn se hi banti hai. Voice input tools ko directly call nahi karta—intent mission/operator, policy, permissions, execution, observation, aur verification pipeline se guzarta hai.

## 7. First automation checklist

1. Official Chrome installed aur `app/config/providers.yaml` mein `channel: chrome` confirm karein.
2. Dedicated profile se Google/ChatGPT/Gemini/Claude login bootstrap karein.
3. Chrome completely close karke profile lock release karein.
4. Stable deployment chahiye to dashboard token export karein; local run mein generated token use kar sakte hain.
5. Optional voice key configure karein.
6. `python run.py` start karein aur terminal mein printed token se connect karein.
7. Dashboard Health, Voice, Perception, Agents, Missions, Tasks, Approvals, aur Events pages check karein.
8. Pehle harmless task run karein, jaise `Open Chrome and report the current page title`.
9. Approval-required ya destructive command ko production data par test na karein; isolated test environment use karein.
10. Shutdown ke liye terminal mein `Ctrl+C` use karein aur Chrome/session cleanup complete hone dein.

## 8. Verification aur tests

Environment verify karein:

```bash
python -c "from app.config.settings import load_settings; print(load_settings().browser)"
python -c "from playwright.async_api import async_playwright; print('Playwright import: OK')"
```

Automated suite:

```bash
python -m pytest -q
```

Browser login aur real provider websites manual integration checks hain, kyunki unhe owner account, local display, aur provider security challenges chahiye.

## 9. Troubleshooting

| Problem | Safe resolution |
| --- | --- |
| `Executable doesn't exist` / Chrome launch failure | Official Google Chrome install karein; `channel: chrome` verify karein. Playwright tooling ke liye `python -m playwright install chromium` dobara chalayein. |
| Google login rejected | Agent stop karein, official Chrome ko same dedicated `--user-data-dir` se manually launch karke login karein, Chrome close karein, phir agent run karein. Security detection bypass flags/extensions use na karein. |
| `profile in use` / `SingletonLock` | Same `data/browser-profile` use karne wale sab Chrome/agent processes cleanly close karein. Lock file ko running process ke dauran delete na karein. |
| Profile corrupt lag raha hai | Runtime stop karein, `data/browser-profile` ka backup/rename karein, fresh profile create karke manually sign in karein. |
| Dashboard `401` | UI aur process mein exact same `BRAINLESS_DASHBOARD_TOKEN` use karein. |
| Dashboard start par token error | Token at least 16 characters ka set karein. |
| Voice `not_configured` | AssemblyAI key environment ya authenticated Voice form se set karein. |
| Microphone unavailable | OS permission/input device check karein aur dependencies reinstall karein. Headless container mein host audio forwarding required hai. |
| CAPTCHA/MFA/human-required | User takeover karke challenge manually complete karein; bypass attempt na karein. |
| `prompt input was not found` | Page ko load hone ke liye bounded wait milta hai aur runtime hidden/disabled duplicate composers skip karta hai. Pehle login/onboarding popup complete karein. Error mein safe page host/title aur editable-candidate count dekhein; ready page par failure rahe to provider UI change ke liye adapter selectors inspect/update karein. |

## 10. Security boundary

```text
User/Voice -> structured intent -> mission/operator -> proposal validator
           -> governor/policy -> permissions -> tool registry -> execution
           -> perception -> verification -> result/dashboard
```

AssemblyAI, webpage content, OCR text, dashboard projections, aur LLM output execution authority nahi hain. LLM sirf proposal deta hai; runtime authorize aur execute karta hai. Passwords/tokens ko prompts, logs, screenshots, repository, extension, ya child-agent context mein na daalein.
